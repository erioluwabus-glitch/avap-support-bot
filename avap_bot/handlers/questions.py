"""
Question answering handlers for admin to answer student questions
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import update_question_status
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Conversation states
ANSWER_TEXT = range(1)

QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle answer button click from questions group"""
    query = update.callback_query
    await query.answer()
    
    if not _is_admin(update):
        await query.edit_message_text("❌ Only admins can answer questions.")
        return ConversationHandler.END
    
    # Extract telegram_id and username from callback data (format: answer_{telegram_id}_{username})
    parts = query.data.split("_")
    if len(parts) >= 3:
        telegram_id = int(parts[1])
        username = parts[2]
    else:
        # Fallback for old format
        username = parts[1]
        telegram_id = None
    
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
    return ANSWER_TEXT


async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle answer submission"""
    try:
        username = context.user_data.get('question_username')
        telegram_id = context.user_data.get('question_telegram_id')
        
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
            await _send_answer_to_student(
                context, 
                telegram_id, 
                answer_text, 
                answer_file_id, 
                answer_file_type
            )
        else:
            await update.message.reply_text(
                f"⚠️ Could not send answer to student (telegram_id not found).\n"
                f"Student username: @{username}",
                parse_mode=ParseMode.MARKDOWN
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to submit answer: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Answer submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to submit answer. Please try again.")
        return ConversationHandler.END


async def _send_answer_to_student(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    answer_text: str,
    answer_file_id: Optional[str] = None,
    answer_file_type: Optional[str] = None
):
    """Send answer to student"""
    try:
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
        
        # If there is a file answer, send it as a separate message
        if answer_file_id and answer_file_type:
            if answer_file_type == 'voice':
                await context.bot.send_voice(chat_id=telegram_id, voice=answer_file_id)
            elif answer_file_type == 'video':
                await context.bot.send_video(chat_id=telegram_id, video=answer_file_id)
            elif answer_file_type == 'document':
                await context.bot.send_document(chat_id=telegram_id, document=answer_file_id)
        
        logger.info(f"Sent answer to student {telegram_id}")
        
    except Exception as e:
        logger.exception(f"Failed to send answer to student {telegram_id}: {e}")
        raise


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handler
answer_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(answer_callback, pattern="^answer_")],
    states={
        ANSWER_TEXT: [MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, answer_text)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True,
    conversation_timeout=600
)


def register_handlers(application):
    """Register all question answering handlers with the application"""
    application.add_handler(answer_conv)

    # Add global callback handler to fix per_message=False warning
    # Note: answer_ callbacks are also handled globally in answer.py
    application.add_handler(CallbackQueryHandler(answer_callback, pattern="^answer_"))

