"""
Student handlers for verified user features
"""
import os
import logging
import asyncio
import random
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode, ChatType

from avap_bot.services.supabase_service import (
    find_verified_by_telegram, check_verified_user,
    find_pending_by_email_or_phone, promote_pending_to_verified, add_question
)
from avap_bot.services.sheets_service import (
    append_submission, append_win, append_question,
    get_student_submissions, get_student_wins, get_student_questions
)
from avap_bot.handlers.grading import create_grading_keyboard, view_grades_handler
# AI features disabled - no longer using AI services
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.validators import validate_email, validate_phone
from avap_bot.utils.chat_utils import should_disable_inline_keyboards, create_keyboard_for_chat
from avap_bot.features.cancel_feature import get_cancel_fallback_handler
import time
import requests

logger = logging.getLogger(__name__)


async def send_message_with_retry(bot, chat_id: int, text: str, max_attempts: int = 3, **kwargs) -> bool:
    """Send message with exponential backoff retry on rate limiting"""
    attempt = 0
    while attempt < max_attempts:
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                # Rate limited - respect Retry-After header if available
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"Rate limited sending message, waiting {wait_time}s (attempt {attempt + 1}/{max_attempts})")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to send message: {e}")
                break
        attempt += 1

    logger.error(f"Failed to send message after {max_attempts} attempts")
    return False


# Conversation states
VERIFY_IDENTIFIER = range(1)
SUBMIT_MODULE, SUBMIT_TYPE, SUBMIT_FILE = range(1, 4)
SHARE_WIN_TYPE, SHARE_WIN_FILE = range(4, 6)
ASK_QUESTION = range(6, 7)

ASSIGNMENT_GROUP_ID = int(os.getenv("ASSIGNMENT_GROUP_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))

# Debug: Log group IDs at startup
logger = logging.getLogger(__name__)
logger.info(f"Group IDs configured - ASSIGNMENT: {ASSIGNMENT_GROUP_ID}, SUPPORT: {SUPPORT_GROUP_ID}, QUESTIONS: {QUESTIONS_GROUP_ID}")
LANDING_PAGE_LINK = os.getenv("LANDING_PAGE_LINK", "https://t.me/avapsupportbot")


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle /start command. Check for verification and start verification if needed."""
    try:
        user = update.effective_user
        user_id = user.id
        logger.info(f"Start command received from user {user_id} ({user.username})")

        # Check if user is already verified
        verified_user = check_verified_user(user_id)
        if verified_user:
            logger.info(f"User {user_id} is already verified, showing main menu")
            await _show_main_menu(update, context, verified_user)
            return ConversationHandler.END

        # If not verified, start the verification process
        logger.info(f"User {user_id} is not verified, starting verification process")
        await update.message.reply_text(
            "👋 **Welcome to AVAP Support Bot!**\n\n"
            "To get started, please verify your account.\n"
            "Please enter your email address or phone number that you used to register for the course:",
            parse_mode=ParseMode.MARKDOWN
        )
        return VERIFY_IDENTIFIER
    except Exception as e:
        logger.exception(f"Error in start_handler for user {user_id}: {e}")
        try:
            # Check if we have a valid message to reply to
            if update.message and update.message.message_id:
                await update.message.reply_text(
                    "❌ Sorry, there was an error processing your request. Please try again later.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Send a new message instead of replying if original message is not available
                await update.effective_chat.send_message(
                    "❌ Sorry, there was an error processing your request. Please try again later.",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as reply_error:
            logger.error(f"Failed to send error message: {reply_error}")
            # Last resort - try to send to the chat directly
            try:
                await update.effective_chat.send_message(
                    "❌ An error occurred. Please try using /start again."
                )
            except Exception as final_error:
                logger.error(f"Completely failed to send error message: {final_error}")
        return ConversationHandler.END


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
        logger.info(f"Searching for pending verification: email={email}, phone={phone}")
        pending_records = find_pending_by_email_or_phone(email=email, phone=phone)

        logger.info(f"Found {len(pending_records)} pending records")
        if not pending_records:
            await update.message.reply_text(
                "❌ Your details were not found in the verification list. Please contact an admin to get added."
            )
            return ConversationHandler.END

        # For simplicity, take the first match if there are multiple
        pending_record = pending_records[0]
        pending_id = pending_record['id']

        # Promote the pending user to verified
        logger.info(f"Promoting user {user_id} with pending_id {pending_id}")
        verified_user = await promote_pending_to_verified(pending_id, user_id)
        if not verified_user:
            raise Exception("Failed to promote user to verified status.")

        logger.info(f"User {user_id} ({verified_user['name']}) successfully verified with status: {verified_user.get('status')}")

        # Approve chat join request if the group ID is set
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.approve_chat_join_request(chat_id=SUPPORT_GROUP_ID, user_id=user_id)
                logger.info(f"Approved join request for user {user_id} to support group.")
            except Exception as e:
                error_msg = str(e)
                if "User_already_participant" in error_msg:
                    logger.info(f"User {user_id} is already a participant in the support group (expected).")
                elif "Hide_requester_missing" in error_msg:
                    logger.info(f"User {user_id} didn't request to join the support group, or request already processed.")
                else:
                    logger.error(f"Failed to approve join request for user {user_id}: {e}")

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
        await notify_admin_telegram(context.bot, f"Verification failed for user {user.full_name} ({user_id}) with identifier '{identifier}'. Error: {e}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text(
                    "❌ An error occurred during verification. The admin has been notified. Please try again later."
                )
            else:
                await update.effective_chat.send_message(
                    "❌ An error occurred during verification. The admin has been notified. Please try again later."
                )
        except Exception as reply_error:
            logger.error(f"Failed to send verification error message: {reply_error}")
        return ConversationHandler.END


async def _show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, verified_user: Dict[str, Any]):
    """Display the main menu for verified users."""
    try:
        # Only show menu in private chats (DMs), not in groups
        if update.effective_chat.type != ChatType.PRIVATE:
            logger.info(f"Main menu request from group chat {update.effective_chat.id} - ignoring")
            return

        from telegram import ReplyKeyboardMarkup

        keyboard = ReplyKeyboardMarkup([
            ["📝 Submit Assignment", "🏆 Share Win"],
            ["📊 View Grades", "📊 Check Status"],
            ["❓ Ask Question"]
        ], resize_keyboard=True, one_time_keyboard=False)

        await update.message.reply_text(
            f"🎉 **Welcome back, {verified_user['name']}!**\n\n"
            "Choose an option below:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.exception(f"Error in _show_main_menu for user {update.effective_user.id}: {e}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text(
                    "❌ Sorry, there was an error showing the main menu. Please try again.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.effective_chat.send_message(
                    "❌ Sorry, there was an error showing the main menu. Please try again.",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as reply_error:
            logger.error(f"Failed to send main menu error message: {reply_error}")


async def submit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle assignment submission - only for verified users"""
    # Check if user is verified
    if not await _is_verified(update):
        await update.message.reply_text(
            "❌ You must be a verified student to submit assignments.\n"
            "Please send /start to verify your account first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        [f"Module {i}" for i in range(1, 7)],
        [f"Module {i}" for i in range(7, 13)],
        ["❌ Cancel"]
    ], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_markdown(
        "📝 **Submit Assignment**\n\n"
        "Select the module for your assignment:",
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

    await update.message.reply_markdown(
        f"📝 **Module {module} Assignment**\n\n"
        "What type of submission is this?",
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
    
    # Remove keyboard and ask for content
    await update.message.reply_markdown(
        f"📝 **Module {context.user_data['submit_module']} - {submission_type.title()}**\n\n"
        "Please send your assignment file or text:"
    )
    return SUBMIT_FILE


async def submit_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle file submission"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        module = context.user_data['submit_module']
        submission_type = context.user_data['submit_type']
        
        # Check for duplicate module submission
        from avap_bot.services.sheets_service import get_student_submissions
        existing_submissions = await run_blocking(get_student_submissions, username, module, user_id)
        
        if existing_submissions:
            await update.message.reply_text(
                f"❌ **Duplicate Submission Detected!**\n\n"
                f"You have already submitted Module {module}.\n"
                f"Found {len(existing_submissions)} previous submission(s) for this module.\n\n"
                f"Please choose a different module or contact support if you need to resubmit.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
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
        
        # Generate unique submission ID
        submission_id = f"sub_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
        
        # Prepare submission data
        submission_data = {
            'submission_id': submission_id,
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
        if ASSIGNMENT_GROUP_ID and ASSIGNMENT_GROUP_ID != 0:
            logger.info(f"Forwarding assignment to group {ASSIGNMENT_GROUP_ID} (configured)")
            # First, forward the original student message
            try:
                if file_id and (update.message.document or update.message.voice or update.message.video):
                    # Forward the file message
                    await update.message.forward(ASSIGNMENT_GROUP_ID)
                elif submission_type == 'text' and 'text_content' in context.user_data:
                    # For text submissions, create a new message with the content and forward it
                    text_message = await context.bot.send_message(
                        update.message.chat_id,
                        f"📝 **Assignment Submission**\n\n{context.user_data['text_content'][:1000]}{'...' if len(context.user_data['text_content']) > 1000 else ''}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await text_message.forward(ASSIGNMENT_GROUP_ID)
                    # Delete the temporary message
                    await text_message.delete()
                else:
                    # Fallback: forward the original message
                    await update.message.forward(ASSIGNMENT_GROUP_ID)
            except Exception as forward_error:
                logger.warning(f"Failed to forward original message: {forward_error}")

            # Then send assignment details for grading with inline buttons
            assignment_details = (
                f"📝 **New Assignment Submission**\n\n"
                f"Student: @{username}\n"
                f"Telegram ID: {user_id}\n"
                f"Module: {module}\n"
                f"Type: {submission_type.title()}\n"
                f"File: {file_name if file_name else 'Text submission'}\n"
                f"Status: Pending Review"
            )

            # Create inline keyboard for grading
            keyboard = create_grading_keyboard(submission_id)
            logger.info(f"Created grading keyboard for submission {submission_id} with {len(keyboard.inline_keyboard)} rows")

            # Check if inline keyboards should be disabled for group chats
            if should_disable_inline_keyboards(update, ASSIGNMENT_GROUP_ID, allow_admin_operations=True):
                logger.info("Disabling inline keyboard for assignment group chat")
                keyboard = None

            # Send assignment details with retry on rate limiting
            try:
                await send_message_with_retry(
                    context.bot,
                    ASSIGNMENT_GROUP_ID,
                    assignment_details,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard if keyboard else None
                )
                logger.info(f"Successfully sent assignment details to group {ASSIGNMENT_GROUP_ID}")
            except Exception as e:
                logger.error(f"Failed to send assignment details to group: {e}")
                # Still continue since assignment was saved

            await update.message.reply_text(
                f"✅ **Assignment Submitted Successfully!**\n\n"
                f"Module: {module}\n"
                f"Type: {submission_type.title()}\n"
                f"Status: Pending Review\n\n"
                f"You'll be notified when it's graded.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            logger.warning("ASSIGNMENT_GROUP_ID not configured - assignments will not be forwarded for grading!")
            await notify_admin_telegram(context.bot, f"⚠️ ASSIGNMENT_GROUP_ID not configured. Assignment from @{username} (Module {module}) not forwarded for grading.")
            await update.message.reply_text(
                f"⚠️ **Assignment Saved!**\n\n"
                f"Your submission has been recorded in our system.\n"
                f"However, admin notifications are not properly configured.\n"
                f"An admin will need to check the system manually for new submissions.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Clear conversation state and show main menu
        context.user_data.clear()
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit assignment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Assignment submission failed: {str(e)}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text("❌ Failed to submit assignment. Please try again.")
            else:
                await update.effective_chat.send_message("❌ Failed to submit assignment. Please try again.")
        except Exception as reply_error:
            logger.error(f"Failed to send assignment error message: {reply_error}")

        # Show main menu after failure
        verified_user = check_verified_user(update.effective_user.id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END


async def share_win_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle share win - only for verified users"""
    # Check if user is verified
    if not await _is_verified(update):
        await update.message.reply_text(
            "❌ You must be a verified student to share wins.\n"
            "Please send /start to verify your account first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    from telegram import ReplyKeyboardMarkup

    keyboard = ReplyKeyboardMarkup([
        ["📝 Text", "🎤 Audio"],
        ["🎥 Video", "❌ Cancel"]
    ], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_markdown(
        "🏆 **Share Your Win**\n\n"
        "What type of win are you sharing?",
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
    
    # Remove keyboard and ask for content
    await update.message.reply_markdown(
        f"🏆 **Share {win_type.title()} Win**\n\n"
        "Please share your win (text, audio, or video):"
    )
    return SHARE_WIN_FILE


async def share_win_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle win file submission"""
    try:
        user_id = update.effective_user.id
        # Use display name (first_name + last_name) instead of username
        user_display_name = update.effective_user.full_name or update.effective_user.first_name or "Unknown User"
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
            'win_id': f"win_{user_id}_{int(datetime.now(timezone.utc).timestamp())}",
            'username': user_display_name,  # Use display name instead of username
            'telegram_id': user_id,
            'type': win_type,
            'file_id': file_id,
            'file_name': file_name,
            'text_content': text_content,
            'shared_at': datetime.now(timezone.utc)
        }
        
        # Save to Google Sheets
        await run_blocking(append_win, win_data)
        
        # Forward to support group with engaging comments
        if SUPPORT_GROUP_ID:
            # Added random compliments to make share win more motivating
            COMPLIMENTS = [
                "Congratulations on your incredible success! You're inspiring everyone around you.",
                "Your hard work and dedication have truly paid off—keep shining!",
                "What an amazing achievement! This motivates us all to push harder.",
                "You've turned your dreams into reality. Proud of you—let's see more wins!",
                "Outstanding job! Your perseverance is a lesson for the whole group.",
                "This win is well-deserved. You're setting the bar high for everyone!",
                "Incredible effort! Sharing this encourages others to chase their goals too.",
                "Way to go! Your success story is fueling motivation in the group.",
                "Bravo on this milestone! Can't wait to celebrate more with you.",
                "You've nailed it! This is proof that persistence pays off—thanks for sharing.",
                "Fantastic achievement! You're a role model for us all.",
                "Huge congrats! Your win is sparking inspiration across the community.",
                "Impressive work! Keep sharing—these stories drive us forward.",
                "Well done! This encourages everyone to aim higher.",
                "Epic win! Your journey motivates and uplifts the entire group."
            ]

            comment = random.choice(COMPLIMENTS)

            if text_content:
                # For text wins, include the actual text content with engaging intro
                # Escape special Markdown characters to prevent parsing errors
                escaped_content = text_content.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                escaped_name = user_display_name.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                forward_text = (
                    f"🎉 **{escaped_name}** shared their win!\n\n"
                    f"{comment}\n\n"
                    f"**Their Story:**\n{escaped_content}"
                )
            elif win_type == 'audio':
                # For audio wins, show audio-specific message
                escaped_name = user_display_name.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                forward_text = (
                    f"🎉 **{escaped_name}** shared their win!\n\n"
                    f"{comment}\n\n"
                    f"🎤 **Audio Win Shared**\n"
                    f"Listen to their inspiring story!"
                )
            elif win_type == 'video':
                # For video wins, show video-specific message
                escaped_name = user_display_name.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                forward_text = (
                    f"🎉 **{escaped_name}** shared their win!\n\n"
                    f"{comment}\n\n"
                    f"🎥 **Video Win Shared**\n"
                    f"Watch their amazing achievement!"
                )
            else:
                # For document wins, show file info with engaging intro
                # Escape special Markdown characters in file name
                escaped_file_name = (file_name or "").replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                escaped_name = user_display_name.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                forward_text = (
                    f"🎉 **{escaped_name}** shared their win!\n\n"
                    f"{comment}\n\n"
                    f"**Achievement Details:**\n"
                    f"📁 File: {escaped_file_name}\n"
                    f"🆔 ID: `{file_id}`"
                )

            if file_id:
                # For file wins, send the appropriate file type with caption
                if win_type == 'audio' and update.message.voice:
                    # Send voice message properly
                    await context.bot.send_voice(SUPPORT_GROUP_ID, voice=file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
                elif win_type == 'video' and update.message.video:
                    # Send video message properly
                    await context.bot.send_video(SUPPORT_GROUP_ID, video=file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
                else:
                    # Send as document for other file types
                    await context.bot.send_document(SUPPORT_GROUP_ID, document=file_id, caption=forward_text, parse_mode=ParseMode.MARKDOWN)
            else:
                # For text wins, send the text message with retry
                await send_message_with_retry(context.bot, SUPPORT_GROUP_ID, forward_text, parse_mode=ParseMode.MARKDOWN)
        
        await update.message.reply_text(
            f"🎉 **Win Shared Successfully!**\n\n"
            f"Type: {win_type.title()}\n"
            f"Thank you for sharing your success!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Clear conversation state and show main menu
        context.user_data.clear()
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to share win: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Win sharing failed: {str(e)}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text("❌ Failed to share win. Please try again.")
            else:
                await update.effective_chat.send_message("❌ Failed to share win. Please try again.")
        except Exception as reply_error:
            logger.error(f"Failed to send share win error message: {reply_error}")

        # Show main menu after failure
        verified_user = check_verified_user(update.effective_user.id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle check status - only for verified users"""
    # Check if user is verified
    if not await _is_verified(update):
        await update.message.reply_text(
            "❌ You must be a verified student to check status.\n"
            "Please send /start to verify your account first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        
        # Get student data with error handling
        try:
            submissions = await run_blocking(get_student_submissions, username, None, user_id)
            wins = await run_blocking(get_student_wins, username)
            # Use Supabase version for questions (requires telegram_id)
            from avap_bot.services.supabase_service import get_student_questions as get_supabase_questions
            questions = await run_blocking(get_supabase_questions, user_id)
        except Exception as e:
            logger.exception(f"Failed to get student data: {e}")
            # Use empty lists as fallback
            submissions = []
            wins = []
            questions = []
            # Initialize status_text for the warning case
            status_text = ""

            # Show a warning in the status message
            status_text += "\n\n⚠️ **Note:** Unable to retrieve some data. Please try again later."

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
            if module:
                # Convert to string if it's not already, then check if it's a digit
                module_str = str(module)
                if module_str.isdigit():
                    completed_modules.add(module_str)

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
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text(
                    "❌ Failed to get status. Please try again.\n"
                    "If the problem persists, contact an admin."
                )
            else:
                await update.effective_chat.send_message(
                    "❌ Failed to get status. Please try again.\n"
                    "If the problem persists, contact an admin."
                )
        except Exception as reply_error:
            logger.error(f"Failed to send status error message: {reply_error}")


async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ask question - only for verified users"""
    # Check if user is verified
    if not await _is_verified(update):
        await update.message.reply_text(
            "❌ You must be a verified student to ask questions.\n"
            "Please send /start to verify your account first.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    await update.message.reply_markdown(
        "❓ **Ask a Question**\n\n"
        "Please type your question (text, audio, or video):"
    )
    return ASK_QUESTION


async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle question submission"""
    try:
        # Force memory cleanup before processing question
        from avap_bot.utils.memory_monitor import log_memory_usage
        log_memory_usage("before ask question processing")
        
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
        
        # AI features disabled - questions go directly to admin

        # Store question in database for future FAQ matching
        def _add_question_pending():
            return add_question(user_id, username, question_text, file_id, file_name, None, 'pending')
        await run_blocking(_add_question_pending)
        
        # Force memory cleanup after processing (even if no AI answer found) - only if AI is enabled
        try:
            # AI features disabled
        except Exception as e:
            logger.warning(f"Failed to clear AI model cache: {e}")
        log_memory_usage("after question processing")

        # Prepare question data for forwarding to admins
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

        # Forward to questions group (where admins monitor questions)
        logger.info(f"QUESTIONS_GROUP_ID: {QUESTIONS_GROUP_ID} (type: {type(QUESTIONS_GROUP_ID)})")
        logger.info(f"Checking if forwarding is needed - QUESTIONS_GROUP_ID is truthy: {bool(QUESTIONS_GROUP_ID)}")
        if QUESTIONS_GROUP_ID and QUESTIONS_GROUP_ID != 0:
            logger.info(f"Forwarding question to questions group {QUESTIONS_GROUP_ID}")
            try:
                # Check if inline keyboards should be disabled (when message comes from group or going to group)
                if should_disable_inline_keyboards(update, QUESTIONS_GROUP_ID, allow_admin_operations=True):
                    logger.info("Disabling inline keyboard for group chat")
                    keyboard = None
                else:
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
                            # Send voice question with retry on rate limiting
                            await send_message_with_retry(
                                context.bot,
                                QUESTIONS_GROUP_ID,
                                f"❓ **New Voice Question**\n\n"
                                f"Student: @{username}\n"
                                f"Telegram ID: {user_id}\n"
                                f"Voice message forwarded above.",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard if keyboard else None
                            )
                        except Exception as e:
                            # Fallback to sending as voice if forwarding fails
                            await context.bot.send_voice(QUESTIONS_GROUP_ID, file_id,
                                caption=f"❓ **New Voice Question**\n\n"
                                       f"Student: @{username}\n"
                                       f"Telegram ID: {user_id}",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard if keyboard else None
                            )
                    elif question_text == "Video question":
                        try:
                            # Forward the video message to preserve the original
                            await update.message.forward(QUESTIONS_GROUP_ID)
                            # Send the answer button as a separate message
                            # Send video question with retry on rate limiting
                            await send_message_with_retry(
                                context.bot,
                                QUESTIONS_GROUP_ID,
                                f"❓ **New Video Question**\n\n"
                                f"Student: @{username}\n"
                                f"Telegram ID: {user_id}\n"
                                f"Video message forwarded above.",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard if keyboard else None
                            )
                        except Exception as e:
                            # Fallback to sending as video if forwarding fails
                            await context.bot.send_video(QUESTIONS_GROUP_ID, file_id,
                                caption=f"❓ **New Video Question**\n\n"
                                       f"Student: @{username}\n"
                                       f"Telegram ID: {user_id}",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard if keyboard else None
                            )
                    else:
                        # Send as document for other file types with inline keyboard
                        await context.bot.send_document(QUESTIONS_GROUP_ID, file_id,
                            caption=f"❓ **New Question**\n\n"
                                   f"Student: @{username}\n"
                                   f"Telegram ID: {user_id}\n"
                                   f"Question: Document: {file_name}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard if keyboard else None
                        )
                else:
                    # Text question - send as message
                    # Send question with retry on rate limiting
                    await send_message_with_retry(
                        context.bot,
                        QUESTIONS_GROUP_ID,
                        f"❓ **New Question**\n\n"
                        f"Student: @{username}\n"
                        f"Telegram ID: {user_id}\n"
                        f"Question: {question_text}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard if keyboard else None
                    )

                await update.message.reply_text(
                    f"✅ **Question Submitted!**\n\n"
                    f"Your question has been forwarded to the support team.\n"
                    f"You'll receive an answer soon.",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                logger.info(f"Successfully forwarded question to questions group {QUESTIONS_GROUP_ID}")
                
            except Exception as e:
                logger.exception(f"Failed to forward question to questions group {QUESTIONS_GROUP_ID}: {e}")
                await update.message.reply_text(
                    f"⚠️ **Question Saved!**\n\n"
                    f"Your question has been recorded in our system.\n"
                    f"However, there was an issue forwarding it to the support team.\n"
                    f"An admin will check the system for new questions.",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            # QUESTIONS_GROUP_ID not configured - question saved but not forwarded
            logger.warning(f"QUESTIONS_GROUP_ID not configured or is 0: {QUESTIONS_GROUP_ID} - question saved but not forwarded")
            await update.message.reply_text(
                f"⚠️ **Question Saved!**\n\n"
                f"Your question has been recorded in our system.\n"
                f"However, admin notifications are not properly configured.\n"
                f"An admin will need to check the system manually for new questions.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Clear conversation state and show main menu
        context.user_data.clear()
        verified_user = check_verified_user(user_id)
        if verified_user:
            await _show_main_menu(update, context, verified_user)

        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit question: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Question submission failed: {str(e)}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text("❌ Failed to submit question. Please try again.")
            else:
                await update.effective_chat.send_message("❌ Failed to submit question. Please try again.")
        except Exception as reply_error:
            logger.error(f"Failed to send question error message: {reply_error}")

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
    chat_id = update.message.chat.id
    chat_type = update.message.chat.type
    logger.info(f"Support group ask handler triggered - Chat ID: {chat_id}, Chat Type: {chat_type}, Expected SUPPORT_GROUP_ID: {SUPPORT_GROUP_ID}")

    # Debug: Check if SUPPORT_GROUP_ID is properly configured
    if SUPPORT_GROUP_ID == 0:
        logger.error(f"SUPPORT_GROUP_ID is not properly configured: {SUPPORT_GROUP_ID}")
        await update.message.reply_text(
            "❌ Support group configuration error. Please contact an admin.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if chat_id != SUPPORT_GROUP_ID:
        logger.warning(f"Ignoring /ask command from chat {chat_id} - not the support group")
        return
    
    user = update.effective_user
    username = user.username or "unknown"
    
    # Check if user is verified
    logger.info(f"Checking verification for user {user_id} ({username})")
    verified_user = check_verified_user(user_id)
    if not verified_user:
        logger.warning(f"User {user_id} is not verified, rejecting /ask command")
        await update.message.reply_text(
            "❌ You must be a verified student to ask questions.\n"
            "Please send /start to the bot in private to verify.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    logger.info(f"User {user_id} is verified, proceeding with /ask command")
    
    # Get the question from the command
    # Format: /ask <question text>
    message_text = update.message.text
    logger.info(f"Processing /ask command: {message_text}")

    if not message_text or len(message_text.split(maxsplit=1)) < 2:
        logger.warning(f"Invalid /ask command format: {message_text}")
        await update.message.reply_text(
            "❓ **Usage:** `/ask <your question>`\n"
            "Example: `/ask How do I submit an assignment?`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    question_text = message_text.split(maxsplit=1)[1]
    logger.info(f"Parsed question: {question_text}")
    
    try:
        # Check for similar questions and auto-answer if found using individual AI functions
        try:
            ai_result = None
            
            # First try FAQ matching
            faq_match = await find_faq_match(question_text, user_id=user_id)
            if faq_match:
                ai_result = {
                    'answer': faq_match['answer'],
                    'source': 'faq',
                    'question': faq_match['question']
                }
            else:
                # Try similar answered questions
                similar_answer = await find_similar_answered_question(question_text, user_id=user_id)
                if similar_answer:
                    ai_result = {
                        'answer': similar_answer['answer'],
                        'source': 'similar',
                        'question': similar_answer['question_text']
                    }
            
            if ai_result:
                answer = ai_result['answer']
                source = ai_result['source']
                similar_question = ai_result.get('question', question_text)
                
                # Determine the appropriate message based on source
                if source == 'faq':
                    title = "💡 **Quick Answer Found!**"
                    subtitle = "I found a similar question in our FAQ database and provided the answer above."
                elif source == 'similar':
                    title = "🔄 **Similar Question Found!**"
                    subtitle = "I found a similar question that was previously answered and provided that answer above."
                
                # Escape special Markdown characters to prevent parsing errors
                escaped_question = question_text.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                escaped_answer = answer.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                escaped_similar = similar_question.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                
                # Send the answer
                if source == 'ai':
                    message_text = f"{title}\n\n**Your Question:** {escaped_question}\n\n**Answer:** {escaped_answer}"
                else:
                    message_text = f"{title}\n\n**Your Question:** {escaped_question}\n\n**Similar Question:** {escaped_similar}\n\n**Answer:** {escaped_answer}"
                
                await context.bot.send_message(
                    user_id,
                    message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=update.message.message_id
                )
                
                await update.message.reply_text(
                    f"✅ **Question answered automatically!**\n\n"
                    f"{subtitle}\n"
                    f"If this doesn't fully address your question, please ask again for admin assistance.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=update.message.message_id
                )

                # Store question in database for future FAQ matching
                def _add_question_with_answer():
                    return add_question(user_id, username, question_text, None, None, answer, 'answered')
                await run_blocking(_add_question_with_answer)

                # Save the question for tracking
                question_data = {
                    'username': username,
                    'telegram_id': user_id,
                    'question_text': question_text,
                    'file_id': None,
                    'file_name': None,
                    'asked_at': datetime.now(timezone.utc),
                    'status': 'Auto-answered',
                    'answer': answer
                }
                await run_blocking(append_question, question_data)
                return

        except Exception as e:
            logger.exception("Error in support group auto-answer check: %s", e)
            # Continue with normal flow if auto-answer fails

        # Prepare question data for forwarding to admins
        question_data = {
            'username': username,
            'telegram_id': user_id,
            'question_text': question_text,
            'file_id': None,
            'file_name': None,
            'asked_at': datetime.now(timezone.utc),
            'status': 'Pending'
        }

        # Save to Google Sheets
        await run_blocking(append_question, question_data)

        # Forward to questions group (where admins monitor questions)
        if QUESTIONS_GROUP_ID and QUESTIONS_GROUP_ID != 0:
            forward_text = (
                f"❓ **New Question from Support Group**\n\n"
                f"Student: @{username}\n"
                f"Telegram ID: {user_id}\n"
                f"Question: {question_text}\n"
            )

            # Check if inline keyboards should be disabled (when message comes from group or going to group)
            if should_disable_inline_keyboards(update, QUESTIONS_GROUP_ID, allow_admin_operations=True):
                logger.info("Disabling inline keyboard for group chat")
                keyboard = None
            else:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("💬 Answer", callback_data=f"answer_{user_id}_{username}")
                ]])

            # Send to questions group for admin to answer
            try:
                await context.bot.send_message(
                    QUESTIONS_GROUP_ID,
                    forward_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard if keyboard else None
                )
                logger.info(f"Successfully forwarded support group question to questions group {QUESTIONS_GROUP_ID}")
            except Exception as e:
                logger.exception(f"Failed to forward support group question to questions group {QUESTIONS_GROUP_ID}: {e}")
                await update.message.reply_text(
                    f"⚠️ Your question has been recorded, @{username}!\n"
                    f"However, there was an issue forwarding it to the support team.\n"
                    f"An admin will check the system for new questions.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=update.message.message_id
                )
                return

            # Confirm in support group
            await update.message.reply_text(
                f"✅ Your question has been forwarded to the support team, @{username}!\n"
                f"You'll get an answer soon.",
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=update.message.message_id
            )
        else:
            # QUESTIONS_GROUP_ID not configured - question saved but not forwarded
            await update.message.reply_text(
                f"⚠️ Your question has been recorded, @{username}!\n"
                f"However, admin notifications are not properly configured.\n"
                f"An admin will need to check the system manually for new questions.",
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=update.message.message_id
            )

        logger.info(f"Support group question processed successfully from {username}: {question_text}")

    except Exception as e:
        logger.exception("Failed to submit support group question: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Support group question failed: {str(e)}")
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text(
                    "❌ Failed to submit question. Please try again or contact admin.",
                    reply_to_message_id=update.message.message_id
                )
            else:
                await update.effective_chat.send_message(
                    "❌ Failed to submit question. Please try again or contact admin."
                )
        except Exception as reply_error:
            logger.error(f"Failed to send support question error message: {reply_error}")


async def _is_verified(update: Update) -> bool:
    """Check if user is verified by checking Supabase."""
    return check_verified_user(update.effective_user.id) is not None


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    user = update.effective_user
    user_id = user.id

    # Check if user is verified
    verified_user = check_verified_user(user_id)

    if verified_user:
        help_text = (
            "🎯 **AVAP Support Bot Help**\n\n"
            "📝 **Submit Assignment** - Submit your course assignments\n"
            "🏆 **Share Win** - Share your achievements and wins\n"
            "📊 **View Grades** - Check your graded assignments and comments\n"
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
        try:
            if update.message and update.message.message_id:
                await update.message.reply_text("❌ Failed to load FAQs. Please try again later.")
            else:
                await update.effective_chat.send_message("❌ Failed to load FAQs. Please try again later.")
        except Exception as reply_error:
            logger.error(f"Failed to send FAQ error message: {reply_error}")


# Conversation handlers

# Main verification and start conversation
start_conv = ConversationHandler(
    entry_points=[CommandHandler("start", start_handler, filters.ChatType.PRIVATE)],
    states={
        VERIFY_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, verify_identifier_handler)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False,
    conversation_timeout=300  # Reduced from 600 to 300 seconds (5 minutes)
)

submit_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"📝 Submit Assignment") & filters.ChatType.PRIVATE, submit_handler)],
    states={
        SUBMIT_MODULE: [MessageHandler(filters.Regex(r"Module \d+") | filters.Regex(r"❌ Cancel"), submit_module)],
        SUBMIT_TYPE: [MessageHandler(filters.Regex(r"📝 Text|🎤 Audio|🎥 Video|❌ Cancel"), submit_type)],
        SUBMIT_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, submit_file)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False,
    conversation_timeout=300  # Reduced from 600 to 300 seconds (5 minutes)
)

share_win_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"🏆 Share Win") & filters.ChatType.PRIVATE, share_win_handler)],
    states={
        SHARE_WIN_TYPE: [MessageHandler(filters.Regex(r"📝 Text|🎤 Audio|🎥 Video|❌ Cancel"), share_win_type)],
        SHARE_WIN_FILE: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, share_win_file)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False,
    conversation_timeout=300  # Reduced from 600 to 300 seconds (5 minutes)
)

ask_conv = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"❓ Ask Question") & filters.ChatType.PRIVATE, ask_handler)],
    states={
        ASK_QUESTION: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, ask_question)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False,
    conversation_timeout=300  # Reduced from 600 to 300 seconds (5 minutes)
)


def register_handlers(application):
    """Register all student handlers with the application"""
    # Add command handlers (restricted to private chats)
    application.add_handler(CommandHandler("help", help_handler, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("faq", faq_handler, filters.ChatType.PRIVATE))
    application.add_handler(start_conv)
    
    # Add conversation handlers
    application.add_handler(submit_conv)
    application.add_handler(share_win_conv)
    application.add_handler(ask_conv)
    
    # Add message handlers for status and grades (only in private chats)
    application.add_handler(MessageHandler(
        filters.Regex(r"📊 Check Status") & filters.ChatType.PRIVATE,
        status_handler
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"📊 View Grades") & filters.ChatType.PRIVATE,
        view_grades_handler
    ))
    
    # Add support group /ask handler (only processes messages from support group)
    application.add_handler(CommandHandler("ask", support_group_ask_handler))
