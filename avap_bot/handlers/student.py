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
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

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
    verified_user = check_verified_user(user.id)
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
        pending_records = find_pending_by_email_or_phone(email=email, phone=phone)

        if not pending_records:
            await update.message.reply_text(
                "❌ Your details were not found in the verification list. Please contact an admin to get added."
            )
            return ConversationHandler.END

        # For simplicity, take the first match if there are multiple
        pending_record = pending_records[0]
        pending_id = pending_record['id']

        # Promote the pending user to verified
        verified_user = promote_pending_to_verified(pending_id, user.id)
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
    # Only show menu in private chats (DMs), not in groups
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        ["📝 Submit Assignment", "🏆 Share Win"],
        ["📊 Check Status", "❓ Ask Question"]
    ], resize_keyboard=True, one_time_keyboard=False)
    
    await update.message.reply_text(
        f"🎉 **Welcome back, {verified_user['name']}!**\n\n"
        "Choose an option below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def submit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle submit assignment message"""
    if not await _is_verified(update):
        await update.message.reply_text("❌ You need to be verified to submit assignments.")
        return ConversationHandler.END
    
    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        [f"Module {i}" for i in range(1, 7)],
        [f"Module {i}" for i in range(7, 13)],
        ["❌ Cancel"]
    ], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "📝 **Submit Assignment**\n\n"
        "Select the module for your assignment:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SUBMIT_MODULE


async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle module selection"""
    message_text = update.message.text
    
    if message_text == "❌ Cancel":
        await update.message.reply_text("❌ Assignment submission cancelled.")
        return ConversationHandler.END
    
    module = message_text.split()[-1]  # Extract number from "Module X"
    context.user_data['submit_module'] = module
    
    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        ["📝 Text", "🎤 Audio"],
        ["🎥 Video", "❌ Cancel"]
    ], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        f"📝 **Module {module} Assignment**\n\n"
        "What type of submission is this?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SUBMIT_TYPE


async def submit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle submission type selection"""
    message_text = update.message.text
    
    if message_text == "❌ Cancel":
        await update.message.reply_text("❌ Assignment submission cancelled.")
        return ConversationHandler.END
    
    # Extract type from button text (remove emoji)
    submission_type = message_text.replace("📝 ", "").replace("🎤 ", "").replace("🎥 ", "").lower()
    context.user_data['submit_type'] = submission_type
    
    await update.message.reply_text(
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
        elif update.message.text and update.message.text.strip():
            # Text submission - use the actual text content
            file_id = None
            file_name = f"text_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
            # Store the text content for later use
            context.user_data['text_content'] = update.message.text.strip()
        elif update.message.text and not update.message.text.strip():
            # Empty text message
            await update.message.reply_text("❌ Please send your text content. Don't send empty messages.")
            return SUBMIT_FILE
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

        # Add text content for text submissions
        if submission_type == 'text' and 'text_content' in context.user_data:
            submission_data['text_content'] = context.user_data['text_content']
        
        # Save to Google Sheets
        await run_blocking(append_submission, submission_data)
        
        # Forward to assignment group
        if ASSIGNMENT_GROUP_ID:
            if submission_type == 'text' and 'text_content' in context.user_data:
                # For text submissions, include the actual content
                forward_text = (
                    f"📝 **New Assignment Submission**\n\n"
                    f"Student: @{username}\n"
                    f"Telegram ID: {user_id}\n"
                    f"Module: {module}\n"
                    f"Type: {submission_type.title()}\n\n"
                    f"**Content:**\n{context.user_data['text_content'][:500]}{'...' if len(context.user_data['text_content']) > 500 else ''}"
                )
            else:
                # For file submissions, show file info
                forward_text = (
                    f"📝 **New Assignment Submission**\n\n"
                    f"Student: @{username}\n"
                    f"Telegram ID: {user_id}\n"
                    f"Module: {module}\n"
                    f"Type: {submission_type.title()}\n"
                    f"File: {file_name}\n"
                    f"File ID: `{file_id}`"
                )

            if file_id:
                # For file submissions, send the file with caption
                await context.bot.send_document(ASSIGNMENT_GROUP_ID, file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
            else:
                # For text submissions, send the text message
                await context.bot.send_message(ASSIGNMENT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
        
        await update.message.reply_text(
            f"✅ **Assignment Submitted Successfully!**\n\n"
            f"Module: {module}\n"
            f"Type: {submission_type.title()}\n"
            f"Status: Pending Review\n\n"
            f"You'll be notified when it's graded.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Show main menu after successful submission
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit assignment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Assignment submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit assignment. Please try again.")

        # Show main menu after failure
        verified_user = check_verified_user(update.effective_user.id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END


async def share_win_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle share win message"""
    if not await _is_verified(update):
        await update.message.reply_text("❌ You need to be verified to share wins.")
        return ConversationHandler.END
    
    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        ["📝 Text", "🎤 Audio"],
        ["🎥 Video", "❌ Cancel"]
    ], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "🏆 **Share Your Win**\n\n"
        "What type of win are you sharing?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return SHARE_WIN_TYPE


async def share_win_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle win type selection"""
    message_text = update.message.text
    
    if message_text == "❌ Cancel":
        await update.message.reply_text("❌ Win sharing cancelled.")
        return ConversationHandler.END
    
    # Extract type from button text (remove emoji)
    win_type = message_text.replace("📝 ", "").replace("🎤 ", "").replace("🎥 ", "").lower()
    context.user_data['win_type'] = win_type
    
    await update.message.reply_text(
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
        text_content = None
        
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
            text_content = update.message.text
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
            'text_content': text_content,
            'shared_at': datetime.now(timezone.utc)
        }
        
        # Save to Google Sheets
        await run_blocking(append_win, win_data)
        
        # Forward to support group
        if SUPPORT_GROUP_ID:
            if text_content:
                # For text wins, include the actual text content
                forward_text = (
                    f"🏆 **New Win Shared**\n\n"
                    f"Student: @{username}\n"
                    f"Type: {win_type.title()}\n\n"
                    f"**Content:**\n{text_content}"
                )
            else:
                # For file wins, show file info
                forward_text = (
                    f"🏆 **New Win Shared**\n\n"
                    f"Student: @{username}\n"
                    f"Type: {win_type.title()}\n"
                    f"File: {file_name}\n"
                    f"File ID: `{file_id}`"
                )

            if file_id:
                # For file wins, send the file with caption
                await context.bot.send_document(SUPPORT_GROUP_ID, file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
            else:
                # For text wins, send the text message
                await context.bot.send_message(SUPPORT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
        
        await update.message.reply_text(
            f"🎉 **Win Shared Successfully!**\n\n"
            f"Type: {win_type.title()}\n"
            f"Thank you for sharing your success!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Show main menu after successful win sharing
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to share win: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Win sharing failed: {str(e)}")
        await update.message.reply_text("❌ Failed to share win. Please try again.")

        # Show main menu after failure
        verified_user = check_verified_user(update.effective_user.id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle status check message"""
    if not await _is_verified(update):
        await update.message.reply_text("❌ You need to be verified to check status.")
        return
    
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        
        # Get student data with error handling
        try:
            submissions = await run_blocking(get_student_submissions, username)
            wins = await run_blocking(get_student_wins, username)
            questions = await run_blocking(get_student_questions, username)
        except Exception as e:
            logger.warning(f"Failed to get data from Google Sheets: {e}")
            # Use empty lists as fallback
            submissions = []
            wins = []
            questions = []

            # Show a warning in the status message
            status_text += "\n\n⚠️ **Note:** Some data may not be available due to system maintenance."

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
        completed_modules = set()
        for sub in submissions:
            module = sub.get('module', '')
            if module and module.isdigit():
                completed_modules.add(module)

        all_modules = set(str(i) for i in range(1, 13))
        modules_left = all_modules - completed_modules

        # Create status text
        status_text = (
            f"📊 **Your Status**\n\n"
            f"👤 Student: @{username}\n"
            f"🏆 Badge: {badge_status}\n\n"
            f"📝 Assignments: {total_submissions}/12\n"
            f"🏆 Wins Shared: {total_wins}\n"
            f"❓ Questions Asked: {total_questions}\n\n"
            f"📚 Modules Progress:\n"
            f"✅ Completed: {', '.join(sorted(completed_modules)) if completed_modules else 'None'}\n"
            f"⏳ Remaining: {len(modules_left)} modules"
        )

        # Add modules left details if not too many
        if len(modules_left) <= 6:
            status_text += f"\n📖 Left to complete: {', '.join(sorted(modules_left)) if modules_left else 'All done! 🎉'}"

        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception("Failed to get status: %s", e)
        await update.message.reply_text(
            "❌ Failed to get status. Please try again.\n"
            "If the problem persists, contact an admin."
        )


async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ask question message"""
    if not await _is_verified(update):
        await update.message.reply_text("❌ You need to be verified to ask questions.")
        return ConversationHandler.END
    
    await update.message.reply_text(
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
            file_name = None
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
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Answer", callback_data=f"answer_{user_id}_{username}")
            ]])
            
            if file_id:
                # For voice and video, try to forward the original message first
                if question_text == "Voice question":
                    try:
                        # Forward the voice message to preserve the original
                        await update.message.forward(QUESTIONS_GROUP_ID)
                        # Send the answer button as a separate message
                        await context.bot.send_message(QUESTIONS_GROUP_ID,
                            f"❓ **New Voice Question**\n\n"
                            f"Student: @{username}\n"
                            f"Telegram ID: {user_id}\n"
                            f"Voice message forwarded above.",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                    except Exception as e:
                        # Fallback to sending as voice if forwarding fails
                        await context.bot.send_voice(QUESTIONS_GROUP_ID, file_id,
                            caption=f"❓ **New Voice Question**\n\n"
                                   f"Student: @{username}\n"
                                   f"Telegram ID: {user_id}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                elif question_text == "Video question":
                    try:
                        # Forward the video message to preserve the original
                        await update.message.forward(QUESTIONS_GROUP_ID)
                        # Send the answer button as a separate message
                        await context.bot.send_message(QUESTIONS_GROUP_ID,
                            f"❓ **New Video Question**\n\n"
                            f"Student: @{username}\n"
                            f"Telegram ID: {user_id}\n"
                            f"Video message forwarded above.",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                    except Exception as e:
                        # Fallback to sending as video if forwarding fails
                        await context.bot.send_video(QUESTIONS_GROUP_ID, file_id,
                            caption=f"❓ **New Video Question**\n\n"
                                   f"Student: @{username}\n"
                                   f"Telegram ID: {user_id}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard
                        )
                else:
                    # Send as document for other file types with inline keyboard
                    await context.bot.send_document(QUESTIONS_GROUP_ID, file_id,
                        caption=f"❓ **New Question**\n\n"
                               f"Student: @{username}\n"
                               f"Telegram ID: {user_id}\n"
                               f"Question: Document: {file_name}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
            else:
                # Text question - send as message
                await context.bot.send_message(QUESTIONS_GROUP_ID,
                    f"❓ **New Question**\n\n"
                    f"Student: @{username}\n"
                    f"Telegram ID: {user_id}\n"
                    f"Question: {question_text}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
        
        await update.message.reply_text(
            f"✅ **Question Submitted!**\n\n"
            f"Your question has been forwarded to the support team.\n"
            f"You'll receive an answer soon.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Show main menu after successful question submission
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit question: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Question submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit question. Please try again.")

        # Show main menu after failure
        verified_user = check_verified_user(update.effective_user.id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")

    # Show main menu after cancellation
    verified_user = check_verified_user(update.effective_user.id)
    if verified_user:
        await _show_main_menu(update, context, verified_user)

    return ConversationHandler.END


async def support_group_ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask command from support group"""
    # Only process if message is from support group
    if update.message.chat.id != SUPPORT_GROUP_ID:
        return
    
    user = update.effective_user
    username = user.username or "unknown"
    
    # Check if user is verified
    verified_user = check_verified_user(user.id)
    if not verified_user:
        await update.message.reply_text(
            "❌ You must be a verified student to ask questions.\n"
            "Please send /start to the bot in private to verify.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get the question from the command
    # Format: /ask <question text>
    message_text = update.message.text
    if not message_text or len(message_text.split(maxsplit=1)) < 2:
        await update.message.reply_text(
            "❓ **Usage:** `/ask <your question>`\n"
            "Example: `/ask How do I submit an assignment?`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    question_text = message_text.split(maxsplit=1)[1]
    
    try:
        # Prepare question data
        question_data = {
            'username': username,
            'telegram_id': user.id,
            'question_text': question_text,
            'file_id': None,
            'file_name': None,
            'asked_at': datetime.now(timezone.utc),
            'status': 'Pending'
        }
        
        # Save to Google Sheets
        await run_blocking(append_question, question_data)
        
        # Forward to questions group
        if QUESTIONS_GROUP_ID:
            forward_text = (
                f"❓ **New Question from Support Group**\n\n"
                f"Student: @{username}\n"
                f"Telegram ID: {user.id}\n"
                f"Question: {question_text}\n"
            )
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Answer", callback_data=f"answer_{user.id}_{username}")
            ]])
            
            # Send to questions group for admin to answer
            await context.bot.send_message(
                QUESTIONS_GROUP_ID, 
                forward_text, 
                parse_mode=ParseMode.MARKDOWN, 
                reply_markup=keyboard
            )
        
        # Confirm in support group
        await update.message.reply_text(
            f"✅ Your question has been forwarded to the support team, @{username}!\n"
            f"You'll get an answer soon.",
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=update.message.message_id
        )
        
        logger.info(f"Support group question from {username}: {question_text}")
        
    except Exception as e:
        logger.exception("Failed to submit support group question: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Support group question failed: {str(e)}")
        await update.message.reply_text(
            "❌ Failed to submit question. Please try again or contact admin.",
            reply_to_message_id=update.message.message_id
        )


async def _is_verified(update: Update) -> bool:
    """Check if user is verified by checking Supabase."""
    return check_verified_user(update.effective_user.id) is not None


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    user = update.effective_user

    # Check if user is verified
    verified_user = check_verified_user(user.id)

    if verified_user:
        help_text = (
            "🎯 **AVAP Support Bot Help**\n\n"
            "📝 **Submit Assignment** - Submit your course assignments\n"
            "🏆 **Share Win** - Share your achievements and wins\n"
            "📊 **Check Status** - View your progress and statistics\n"
            "❓ **Ask Question** - Get help from support team\n\n"
            "💡 **Tips:**\n"
            "- Use the buttons below to navigate\n"
            "- For questions, you can send text, voice, or video messages\n"
            "- Your progress is automatically tracked\n\n"
            "Need more help? Contact an admin!"
        )
    else:
        help_text = (
            "👋 **AVAP Support Bot Help**\n\n"
            "To get started, you need to verify your account.\n"
            "Please send your email or phone number that you used during registration.\n\n"
            "Once verified, you'll have access to:\n"
            "📝 Submit assignments\n"
            "🏆 Share your wins\n"
            "📊 Check your status\n"
            "❓ Ask questions\n\n"
            "Contact an admin if you need help with verification!"
        )

    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def faq_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /faq command"""
    if not await _is_verified(update):
        await update.message.reply_text("❌ You need to be verified to access FAQs.")
        return

    try:
        from avap_bot.services.supabase_service import get_faqs

        # Get FAQs from database
        faqs = get_faqs()

        if not faqs:
            await update.message.reply_text(
                "📚 **FAQ**\n\n"
                "No FAQs are available at the moment.\n"
                "Please contact an admin if you need help!",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Show first few FAQs with option to browse more
        faq_text = "📚 **Frequently Asked Questions**\n\n"

        for i, faq in enumerate(faqs[:5], 1):  # Show first 5 FAQs
            faq_text += f"**{i}. {faq['question']}**\n"
            faq_text += f"{faq['answer'][:100]}{'...' if len(faq['answer']) > 100 else ''}\n\n"

        if len(faqs) > 5:
            faq_text += f"📖 And {len(faqs) - 5} more FAQs available.\n"
            faq_text += "Contact admin for specific questions!"

        await update.message.reply_text(faq_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception("Failed to get FAQs: %s", e)
        await update.message.reply_text("❌ Failed to load FAQs. Please try again later.")


# Conversation handlers

# Main verification and start conversation
start_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_handler)],
    states={
        VERIFY_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_identifier_handler)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True
)

submit_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"📝 Submit Assignment"), submit_handler)],
    states={
        SUBMIT_MODULE: [MessageHandler(filters.Regex(r"Module \d+") | filters.Regex(r"❌ Cancel"), submit_module)],
        SUBMIT_TYPE: [MessageHandler(filters.Regex(r"📝 Text|🎤 Audio|🎥 Video|❌ Cancel"), submit_type)],
        SUBMIT_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, submit_file)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True
)

share_win_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"🏆 Share Win"), share_win_handler)],
    states={
        SHARE_WIN_TYPE: [MessageHandler(filters.Regex(r"📝 Text|🎤 Audio|🎥 Video|❌ Cancel"), share_win_type)],
        SHARE_WIN_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, share_win_file)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True
)

ask_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"❓ Ask Question"), ask_handler)],
    states={
        ASK_QUESTION: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, ask_question)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True
)


def register_handlers(application):
    """Register all student handlers with the application"""
    # Add command handlers
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("faq", faq_handler))
    application.add_handler(start_conv)
    
    # Add conversation handlers
    application.add_handler(submit_conv)
    application.add_handler(share_win_conv)
    application.add_handler(ask_conv)
    
    # Add message handlers for status
    application.add_handler(MessageHandler(filters.Regex(r"📊 Check Status"), status_handler))
    
    # Add support group /ask handler (only processes messages from support group)
    application.add_handler(CommandHandler("ask", support_group_ask_handler, filters=filters.ChatType.SUPERGROUP | filters.ChatType.GROUP))
