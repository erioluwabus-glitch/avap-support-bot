"""
Student handlers for verified user features
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode, ChatType

from avap_bot.services.supabase_service import (
    find_verified_by_telegram, check_verified_user,
    find_pending_by_email_or_phone, promote_pending_to_verified
)
from avap_bot.services.sheets_service import (
    append_submission, append_win, append_question,
    get_student_submissions, get_student_wins, get_student_questions
)
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.validators import validate_email, validate_phone

logger = logging.getLogger(__name__)

# Conversation states
VERIFY_IDENTIFIER = range(1)
SUBMIT_MODULE, SUBMIT_TYPE, SUBMIT_FILE = range(1, 4)
SHARE_WIN_TYPE, SHARE_WIN_FILE = range(4, 6)
ASK_QUESTION = range(6, 7)

ASSIGNMENT_GROUP_ID = int(os.getenv("ASSIGNMENT_GROUP_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))
LANDING_PAGE_LINK = os.getenv("LANDING_PAGE_LINK", "https://t.me/avapsupportbot")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle /start command. Check for verification and start verification if needed."""
    user = update.effective_user
    
    # Check if user is already verified
    verified_user = await check_verified_user(user.id)
    if verified_user:
        await _show_main_menu(update, context, verified_user)
        return ConversationHandler.END

    # If not verified, start the verification process
    await update.message.reply_text(
        "👋 **Welcome to AVAP Support Bot!**\n\n"
        "To get started, please verify your account.\n"
        "Please enter your email address or phone number that you used to register for the course:",
        parse_mode=ParseMode.MARKDOWN
    )
    return VERIFY_IDENTIFIER


async def verify_identifier_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's email/phone input for verification."""
    identifier = update.message.text.strip().lower()
    user = update.effective_user

    is_email = validate_email(identifier)
    is_phone = validate_phone(identifier)

    if not is_email and not is_phone:
        await update.message.reply_text(
            "❌ That doesn't look like a valid email or phone number. Please try again:"
        )
        return VERIFY_IDENTIFIER

    try:
        # Find a pending verification record
        email = identifier if is_email else None
        phone = identifier if is_phone else None
        pending_records = await find_pending_by_email_or_phone(email=email, phone=phone)

        if not pending_records:
            await update.message.reply_text(
                "❌ Your details were not found in the verification list. Please contact an admin to get added."
            )
            return ConversationHandler.END

        # For simplicity, take the first match if there are multiple
        pending_record = pending_records[0]
        pending_id = pending_record['id']

        # Promote the pending user to verified
        verified_user = await promote_pending_to_verified(pending_id, user.id, user.username)
        if not verified_user:
            raise Exception("Failed to promote user to verified status.")

        logger.info(f"User {user.id} ({verified_user['name']}) successfully verified.")

        # Approve chat join request if the group ID is set
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.approve_chat_join_request(chat_id=SUPPORT_GROUP_ID, user_id=user.id)
                logger.info(f"Approved join request for user {user.id} to support group.")
            except Exception as e:
                logger.error(f"Failed to approve join request for user {user.id}: {e}")

        await update.message.reply_text(
            f"🎉 **Congratulations, {verified_user['name']}! You are now verified!**\n\n"
            f"Welcome to the AVAP community. You now have access to all the bot features.\n\n"
            f"Here is the landing page link: {LANDING_PAGE_LINK}",
            parse_mode=ParseMode.MARKDOWN
        )
        await _show_main_menu(update, context, verified_user)
        return ConversationHandler.END

    except Exception as e:
        logger.exception(f"Verification failed for identifier '{identifier}': {e}")
        await notify_admin_telegram(context.bot, f"Verification failed for user {user.full_name} ({user.id}) with identifier '{identifier}'. Error: {e}")
        await update.message.reply_text(
            "❌ An error occurred during verification. The admin has been notified. Please try again later."
        )
        return ConversationHandler.END


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, verified_user: Dict[str, Any]):
    """Display the main menu for verified users."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Submit Assignment", callback_data="submit")],
        [InlineKeyboardButton("🏆 Share Win", callback_data="share_win")],
        [InlineKeyboardButton("📊 Check Status", callback_data="status")],
        [InlineKeyboardButton("❓ Ask Question", callback_data="ask")]
    ])
    
    await update.message.reply_text(
        f"🎉 **Welcome back, {verified_user['name']}!**\n\n"
        "Choose an option below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def submit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle submit assignment callback"""
    query = update.callback_query
    await query.answer()
    
    if not await _is_verified(update):
        await query.edit_message_text("❌ You need to be verified to submit assignments.")
        return ConversationHandler.END
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Module {i}", callback_data=f"module_{i}") for i in range(1, 7)],
        [InlineKeyboardButton(f"Module {i}", callback_data=f"module_{i}") for i in range(7, 13)],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await query.edit_message_text(
        "📝 **Submit Assignment**\n\n"
        "Select the module for your assignment:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SUBMIT_MODULE


async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle module selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Submission cancelled.")
        return ConversationHandler.END
    
    module = query.data.split("_")[1]
    context.user_data['submit_module'] = module
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Text", callback_data="type_text")],
        [InlineKeyboardButton("🎤 Audio", callback_data="type_audio")],
        [InlineKeyboardButton("🎥 Video", callback_data="type_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await query.edit_message_text(
        f"📝 **Module {module} Assignment**\n\n"
        "What type of submission is this?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SUBMIT_TYPE


async def submit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle submission type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Submission cancelled.")
        return ConversationHandler.END
    
    submission_type = query.data.split("_")[1]
    context.user_data['submit_type'] = submission_type
    
    await query.edit_message_text(
        f"📝 **Module {context.user_data['submit_module']} - {submission_type.title()}**\n\n"
        "Please send your assignment file or text:",
        parse_mode=ParseMode.MARKDOWN
    )
    return SUBMIT_FILE


async def submit_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle file submission"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        module = context.user_data['submit_module']
        submission_type = context.user_data['submit_type']
        
        # Get file info
        file_id = None
        file_name = None
        
        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
        elif update.message.voice:
            file_id = update.message.voice.file_id
            file_name = f"voice_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.ogg"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_name = update.message.video.file_name or f"video_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
        elif update.message.text:
            # Text submission
            file_id = None
            file_name = f"text_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
        else:
            await update.message.reply_text("❌ Unsupported file type. Please send text, document, audio, or video.")
            return SUBMIT_FILE
        
        # Prepare submission data
        submission_data = {
            'username': username,
            'telegram_id': user_id,
            'module': module,
            'type': submission_type,
            'file_id': file_id,
            'file_name': file_name,
            'submitted_at': datetime.now(timezone.utc),
            'status': 'Pending'
        }
        
        # Save to Google Sheets
        await run_blocking(append_submission, submission_data)
        
        # Forward to assignment group
        if ASSIGNMENT_GROUP_ID:
            forward_text = (
                f"📝 **New Assignment Submission**\n\n"
                f"Student: @{username}\n"
                f"Telegram ID: {user_id}\n"
                f"Module: {module}\n"
                f"Type: {submission_type.title()}\n"
                f"File: {file_name}\n"
                f"File ID: `{file_id}`" if file_id else "Text submission"
            )
            
            if file_id:
                if submission_type == "text":
                    await context.bot.send_message(ASSIGNMENT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await context.bot.send_document(ASSIGNMENT_GROUP_ID, file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await context.bot.send_message(ASSIGNMENT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
        
        await update.message.reply_text(
            f"✅ **Assignment Submitted Successfully!**\n\n"
            f"Module: {module}\n"
            f"Type: {submission_type.title()}\n"
            f"Status: Pending Review\n\n"
            f"You'll be notified when it's graded.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit assignment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Assignment submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit assignment. Please try again.")
        return ConversationHandler.END


async def share_win_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle share win callback"""
    query = update.callback_query
    await query.answer()
    
    if not await _is_verified(update):
        await query.edit_message_text("❌ You need to be verified to share wins.")
        return ConversationHandler.END
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Text", callback_data="win_text")],
        [InlineKeyboardButton("🎤 Audio", callback_data="win_audio")],
        [InlineKeyboardButton("🎥 Video", callback_data="win_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await query.edit_message_text(
        "🏆 **Share Your Win**\n\n"
        "What type of win are you sharing?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SHARE_WIN_TYPE


async def share_win_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle win type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Win sharing cancelled.")
        return ConversationHandler.END
    
    win_type = query.data.split("_")[1]
    context.user_data['win_type'] = win_type
    
    await query.edit_message_text(
        f"🏆 **Share {win_type.title()} Win**\n\n"
        "Please share your win (text, audio, or video):",
        parse_mode=ParseMode.MARKDOWN
    )
    return SHARE_WIN_FILE


async def share_win_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle win file submission"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        win_type = context.user_data['win_type']
        
        # Get file info
        file_id = None
        file_name = None
        
        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
        elif update.message.voice:
            file_id = update.message.voice.file_id
            file_name = f"win_voice_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.ogg"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_name = update.message.video.file_name or f"win_video_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
        elif update.message.text:
            file_id = None
            file_name = f"win_text_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
        else:
            await update.message.reply_text("❌ Unsupported file type. Please send text, document, audio, or video.")
            return SHARE_WIN_FILE
        
        # Prepare win data
        win_data = {
            'username': username,
            'telegram_id': user_id,
            'type': win_type,
            'file_id': file_id,
            'file_name': file_name,
            'shared_at': datetime.now(timezone.utc)
        }
        
        # Save to Google Sheets
        await run_blocking(append_win, win_data)
        
        # Forward to support group
        if SUPPORT_GROUP_ID:
            forward_text = (
                f"🏆 **New Win Shared**\n\n"
                f"Student: @{username}\n"
                f"Type: {win_type.title()}\n"
                f"File: {file_name}\n"
                f"File ID: `{file_id}`" if file_id else "Text win"
            )
            
            if file_id:
                if win_type == "text":
                    await context.bot.send_message(SUPPORT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await context.bot.send_document(SUPPORT_GROUP_ID, file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await context.bot.send_message(SUPPORT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
        
        await update.message.reply_text(
            f"🎉 **Win Shared Successfully!**\n\n"
            f"Type: {win_type.title()}\n"
            f"Thank you for sharing your success!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to share win: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Win sharing failed: {str(e)}")
        await update.message.reply_text("❌ Failed to share win. Please try again.")
        return ConversationHandler.END


async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle status check callback"""
    query = update.callback_query
    await query.answer()
    
    if not await _is_verified(update):
        await query.edit_message_text("❌ You need to be verified to check status.")
        return
    
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        
        # Get student data
        submissions = await run_blocking(get_student_submissions, username)
        wins = await run_blocking(get_student_wins, username)
        questions = await run_blocking(get_student_questions, username)
        
        # Calculate stats
        total_submissions = len(submissions)
        total_wins = len(wins)
        total_questions = len(questions)
        
        # Check badge eligibility
        badge_status = "🥉 New Student"
        if total_submissions >= 3 and total_wins >= 3:
            badge_status = "🥇 Top Student"
        elif total_submissions >= 1 or total_wins >= 1:
            badge_status = "🥈 Active Student"
        
        # Calculate modules left
        completed_modules = set(sub['module'] for sub in submissions)
        all_modules = set(str(i) for i in range(1, 13))
        modules_left = all_modules - completed_modules
        
        status_text = (
            f"📊 **Your Status**\n\n"
            f"👤 Student: @{username}\n"
            f"🏆 Badge: {badge_status}\n\n"
            f"📝 Assignments: {total_submissions}/12\n"
            f"🏆 Wins Shared: {total_wins}\n"
            f"❓ Questions Asked: {total_questions}\n\n"
            f"📚 Modules Left: {len(modules_left)}\n"
            f"Completed: {', '.join(sorted(completed_modules)) if completed_modules else 'None'}\n"
            f"Remaining: {', '.join(sorted(modules_left)) if modules_left else 'All done!'}"
        )
        
        await query.edit_message_text(status_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.exception("Failed to get status: %s", e)
        await query.edit_message_text("❌ Failed to get status. Please try again.")


async def ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ask question callback"""
    query = update.callback_query
    await query.answer()
    
    if not await _is_verified(update):
        await query.edit_message_text("❌ You need to be verified to ask questions.")
        return ConversationHandler.END
    
    await query.edit_message_text(
        "❓ **Ask a Question**\n\n"
        "Please type your question (text, audio, or video):",
        parse_mode=ParseMode.MARKDOWN
    )
    return ASK_QUESTION


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question submission"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        
        # Get question content
        file_id = None
        file_name = None
        question_text = None
        
        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
            question_text = f"Document: {file_name}"
        elif update.message.voice:
            file_id = update.message.voice.file_id
            file_name = f"question_voice_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.ogg"
            question_text = "Voice question"
        elif update.message.video:
            file_id = update.message.video.file_id
            file_name = update.message.video.file_name or f"question_video_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
            question_text = "Video question"
        elif update.message.text:
            question_text = update.message.text
        else:
            await update.message.reply_text("❌ Unsupported question type. Please send text, document, audio, or video.")
            return ASK_QUESTION
        
        # Prepare question data
        question_data = {
            'username': username,
            'telegram_id': user_id,
            'question_text': question_text,
            'file_id': file_id,
            'file_name': file_name,
            'asked_at': datetime.now(timezone.utc),
            'status': 'Pending'
        }
        
        # Save to Google Sheets
        await run_blocking(append_question, question_data)
        
        # Forward to questions group
        if QUESTIONS_GROUP_ID:
            forward_text = (
                f"❓ **New Question**\n\n"
                f"Student: @{username}\n"
                f"Question: {question_text}\n"
                f"File: {file_name}\n"
                f"File ID: `{file_id}`" if file_id else "Text question"
            )
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Answer", callback_data=f"answer_{username}")
            ]])
            
            if file_id:
                if question_text == "Voice question" or question_text == "Video question":
                    await context.bot.send_document(QUESTIONS_GROUP_ID, file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                else:
                    await context.bot.send_message(QUESTIONS_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
            else:
                await context.bot.send_message(QUESTIONS_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        
        await update.message.reply_text(
            f"✅ **Question Submitted!**\n\n"
            f"Your question has been forwarded to the support team.\n"
            f"You'll receive an answer soon.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit question: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Question submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit question. Please try again.")
        return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


async def _is_verified(update: Update) -> bool:
    """Check if user is verified by checking Supabase."""
    return await check_verified_user(update.effective_user.id) is not None


# Conversation handlers

# Main verification and start conversation
start_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_handler)],
    states={
        VERIFY_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_identifier_handler)],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)

submit_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(submit_callback, pattern="^submit$")],
    states={
        SUBMIT_MODULE: [CallbackQueryHandler(submit_module, pattern="^module_|^cancel$")],
        SUBMIT_TYPE: [CallbackQueryHandler(submit_type, pattern="^type_|^cancel$")],
        SUBMIT_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, submit_file)],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)

share_win_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(share_win_callback, pattern="^share_win$")],
    states={
        SHARE_WIN_TYPE: [CallbackQueryHandler(share_win_type, pattern="^win_|^cancel$")],
        SHARE_WIN_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, share_win_file)],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)

ask_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_callback, pattern="^ask$")],
    states={
        ASK_QUESTION: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, ask_question)],
    },
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)


def register_handlers(application):
    """Register all student handlers with the application"""
    # Add command handlers
    application.add_handler(start_conv)
    
    # Add conversation handlers
    application.add_handler(submit_conv)
    application.add_handler(share_win_conv)
    application.add_handler(ask_conv)
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(status_callback, pattern="^status$"))
