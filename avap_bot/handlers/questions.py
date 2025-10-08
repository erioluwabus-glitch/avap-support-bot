"""
Question answering handlers for admin to answer student questions
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import update_question_status
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle answer button click from questions group"""
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Answer callback received from user {update.effective_user.id}")
    logger.info(f"Admin check for user {update.effective_user.id}: {_is_admin(update)}")
    
    if not _is_admin(update):
        logger.warning(f"Non-admin user {update.effective_user.id} tried to answer question")
        await query.edit_message_text("❌ Only admins can answer questions.")
        return
    
    logger.info(f"Admin check passed for user {update.effective_user.id}")
    
    # Extract telegram_id and username from callback data (format: answer_{telegram_id}_{username})
    parts = query.data.split("_")
    logger.info(f"Answer callback data: {query.data}, parts: {parts}")
    
    if len(parts) >= 3:
        try:
            telegram_id = int(parts[1])
            username = parts[2]
            logger.info(f"Parsed telegram_id: {telegram_id}, username: {username}")
        except ValueError as e:
            logger.error(f"Failed to parse telegram_id from '{parts[1]}': {e}")
            username = parts[1] if len(parts) > 1 else "unknown"
            telegram_id = None
    else:
        # Fallback for old format
        username = parts[1] if len(parts) > 1 else "unknown"
        telegram_id = None
        logger.warning(f"Using fallback format for callback data: {query.data}")
    
    # Store question info in context for the answer handler
    context.user_data['question_username'] = username
    context.user_data['question_telegram_id'] = telegram_id
    context.user_data['question_message_id'] = query.message.message_id
    context.user_data['question_text'] = query.message.text or query.message.caption
    
    await query.edit_message_text(
        f"{query.message.text or query.message.caption}\n\n"
        f"💬 **Answering this question...**\n"
        f"Please send your answer (text, audio, or video):",
        parse_mode=ParseMode.MARKDOWN
    )
    
    logger.info(f"Question info stored for {username}, waiting for answer")


async def handle_answer_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle answer message from admin"""
    try:
        logger.info(f"Answer message handler called from user {update.effective_user.id}")
        
        # Check if this is an admin answering a question
        if not _is_admin(update):
            logger.info(f"User {update.effective_user.id} is not admin, ignoring message")
            return  # Not an admin, ignore
        
        # Check if we have question info stored
        username = context.user_data.get('question_username')
        telegram_id = context.user_data.get('question_telegram_id')
        
        logger.info(f"Question info in context: username={username}, telegram_id={telegram_id}")
        
        if not username or not telegram_id:
            logger.info("No question info found in context, ignoring message")
            return
        
        logger.info(f"Processing answer from admin {update.effective_user.id} for question from {username}")
        
        # Process the answer using the existing logic
        await answer_text(update, context)
        
    except Exception as e:
        logger.exception(f"Failed to handle answer message: {e}")


async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle answer submission"""
    try:
        logger.info(f"Answer text handler called from user {update.effective_user.id}")
        username = context.user_data.get('question_username')
        telegram_id = context.user_data.get('question_telegram_id')
        
        logger.info(f"Answer submission - username: {username}, telegram_id: {telegram_id}")
        
        # Get answer content
        answer_text = None
        answer_file_id = None
        answer_file_type = None
        
        if update.message.text:
            answer_text = update.message.text
        elif update.message.voice:
            answer_file_id = update.message.voice.file_id
            answer_file_type = "voice"
            answer_text = "(Voice answer attached)"
        elif update.message.video:
            answer_file_id = update.message.video.file_id
            answer_file_type = "video"
            answer_text = "(Video answer attached)"
        elif update.message.document:
            answer_file_id = update.message.document.file_id
            answer_file_type = "document"
            answer_text = f"(Document answer attached: {update.message.document.file_name})"
        else:
            await update.message.reply_text("❌ Unsupported answer type. Please send text, audio, or video.")
            return ANSWER_TEXT
        
        # Update question status in Google Sheets
        await run_blocking(update_question_status, username, answer_text)
        
        # Send confirmation to admin
        await update.message.reply_text(
            f"✅ **Answer Sent!**\n\n"
            f"Student: @{username}\n"
            f"Answer: {answer_text[:100]}{'...' if len(answer_text) > 100 else ''}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send answer to student
        if telegram_id:
            success = await _send_answer_to_student(
                context, 
                telegram_id, 
                answer_text, 
                answer_file_id, 
                answer_file_type
            )
            
            if not success:
                await update.message.reply_text(
                    f"⚠️ **Answer saved but failed to send to student!**\n\n"
                    f"Student: @{username}\n"
                    f"Telegram ID: {telegram_id}\n\n"
                    f"Please try sending the answer manually to the student.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"⚠️ Could not send answer to student (telegram_id not found).\n"
                f"Student username: @{username}",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Clear the question info from context after successful processing
        context.user_data.pop('question_username', None)
        context.user_data.pop('question_telegram_id', None)
        context.user_data.pop('question_message_id', None)
        context.user_data.pop('question_text', None)
        
    except Exception as e:
        logger.exception("Failed to submit answer: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Answer submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit answer. Please try again.")


async def _send_answer_to_student(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    answer_text: str,
    answer_file_id: Optional[str] = None,
    answer_file_type: Optional[str] = None
):
    """Send answer to student"""
    try:
        logger.info(f"Attempting to send answer to student {telegram_id}")
        
        message = (
            f"✅ **Your question has been answered!**\n\n"
            f"**Answer:**\n{answer_text}"
        )
        
        # Send the main answer text
        await context.bot.send_message(
            chat_id=telegram_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"Successfully sent text answer to student {telegram_id}")
        
        # If there is a file answer, send it as a separate message
        if answer_file_id and answer_file_type:
            if answer_file_type == 'voice':
                await context.bot.send_voice(chat_id=telegram_id, voice=answer_file_id)
            elif answer_file_type == 'video':
                await context.bot.send_video(chat_id=telegram_id, video=answer_file_id)
            elif answer_file_type == 'document':
                await context.bot.send_document(chat_id=telegram_id, document=answer_file_id)
        
        logger.info(f"Successfully sent answer to student {telegram_id}")
        return True
        
    except Exception as e:
        logger.exception(f"Failed to send answer to student {telegram_id}: {e}")
        return False


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID




def register_handlers(application):
    """Register all question answering handlers with the application"""
    # Register callback handler for answer button clicks
    application.add_handler(CallbackQueryHandler(answer_callback, pattern="^answer_"))
    
    # Register message handler for answer submissions
    application.add_handler(MessageHandler(
        filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, 
        handle_answer_message
    ))

