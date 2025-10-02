"""
Grading handlers for assignment evaluation
"""
import os
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import update_submission_grade, add_grade_comment
from avap_bot.services.supabase_service import update_assignment_grade, get_assignment_by_id
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# Conversation states
GRADE_SCORE, GRADE_COMMENT = range(2)

ASSIGNMENT_GROUP_ID = int(os.getenv("ASSIGNMENT_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


async def grade_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle assignment grading"""
    if not _is_admin(update):
        await update.message.reply_text("❌ Only admins can grade assignments.")
        return ConversationHandler.END
    
    # Extract submission info from forwarded message
    submission_info = _extract_submission_info(update.message)
    if not submission_info:
        await update.message.reply_text("❌ Could not extract submission information. Make sure the forwarded message contains the student's username, telegram ID, module, and type.")
        return ConversationHandler.END
    
    context.user_data['submission_info'] = submission_info
    
    # Show grading buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{i}", callback_data=f"grade_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(f"{i}", callback_data=f"grade_{i}") for i in range(6, 11)],
        [InlineKeyboardButton("❌ Cancel", callback_data="grade_cancel")]
    ])
    
    await update.message.reply_text(
        f"📝 **Grade Assignment**\n\n"
        f"Student: @{submission_info['username']}\n"
        f"Module: {submission_info['module']}\n"
        f"Type: {submission_info['type']}\n\n"
        f"Select a grade (1-10):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    return GRADE_SCORE


async def grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle grade selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "grade_cancel":
        await query.edit_message_text("❌ Grading cancelled.")
        return ConversationHandler.END
    
    score = int(query.data.split("_")[1])
    submission_info = context.user_data['submission_info']
    context.user_data['grade'] = score
    
    try:
        # Update grade in Google Sheets
        await run_blocking(update_submission_grade, submission_info['username'], submission_info['module'], score)
        
        # Replace buttons with comment options
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Add Comments", callback_data="add_comment")],
            [InlineKeyboardButton("✅ No Comments", callback_data="no_comment")]
        ])
        
        await query.edit_message_text(
            f"✅ **Assignment Graded!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {score}/10\n\n"
            f"Would you like to add comments?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        return GRADE_COMMENT
        
    except Exception as e:
        logger.exception("Failed to grade assignment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Grading failed: {str(e)}")
        await query.edit_message_text("❌ Failed to grade assignment. Please try again.")
        return ConversationHandler.END


async def grade_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle comment decision"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "no_comment":
        await query.edit_message_text(
            f"✅ **Grading Complete!**\n\n"
            f"Student: @{context.user_data['submission_info']['username']}\n"
            f"Module: {context.user_data['submission_info']['module']}\n"
            f"Grade: {context.user_data.get('grade', 'N/A')}/10\n"
            f"Comments: None",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify student
        await _notify_student_grade(context, context.user_data['submission_info'], context.user_data.get('grade'), None)
        return ConversationHandler.END
    
    # Ask for comment
    await query.edit_message_text(
        f"💬 **Add Comments**\n\n"
        f"Please provide your comments (text, audio, or video):",
        parse_mode=ParseMode.MARKDOWN
    )
    return GRADE_COMMENT


async def add_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle comment submission"""
    try:
        submission_info = context.user_data['submission_info']
        grade = context.user_data.get('grade', 0)
        
        # Get comment content
        comment_text = None
        comment_file_id = None
        comment_file_type = None

        if update.message.text:
            comment_text = update.message.text
        elif update.message.voice:
            comment_file_id = update.message.voice.file_id
            comment_file_type = "voice"
            comment_text = "(Voice comment attached)"
        elif update.message.video:
            comment_file_id = update.message.video.file_id
            comment_file_type = "video"
            comment_text = "(Video comment attached)"
        elif update.message.document:
            comment_file_id = update.message.document.file_id
            comment_file_type = "document"
            comment_text = f"(Document comment attached: {update.message.document.file_name})"
        else:
            await update.message.reply_text("❌ Unsupported comment type. Please send text, document, audio, or video.")
            return GRADE_COMMENT
        
        # Add comment to Google Sheets
        await run_blocking(add_grade_comment, submission_info['username'], submission_info['module'], comment_text)
        
        await update.message.reply_text(
            f"✅ **Comment Added!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {grade}/10\n"
            f"Comment: {comment_text}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify student
        await _notify_student_grade(context, submission_info, grade, comment_text, comment_file_id, comment_file_type)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to add comment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Comment addition failed: {str(e)}")
        await update.message.reply_text("❌ Failed to add comment. Please try again.")
        return ConversationHandler.END


async def _notify_student_grade(context: ContextTypes.DEFAULT_TYPE, submission_info: Dict[str, Any], grade: int, comment: Optional[str], comment_file_id: Optional[str] = None, comment_file_type: Optional[str] = None):
    """Notify student about their grade"""
    try:
        telegram_id = submission_info.get('telegram_id')
        if not telegram_id:
            logger.warning("Could not notify student: telegram_id is missing from submission info.")
            await notify_admin_telegram(context.bot, f"Could not notify @{submission_info.get('username')}, telegram_id missing.")
            return
        
        message = (
            f"🎉 **Your assignment has been graded!**\n\n"
            f"**Module:** {submission_info['module']}\n"
            f"**Grade:** {grade}/10\n"
        )
        
        if comment:
            message += f"\n**Comments:**\n{comment}"
        else:
            message += "\n**Comments:**\nNo comments provided."

        # Send the main notification text
        await context.bot.send_message(chat_id=telegram_id, text=message, parse_mode=ParseMode.MARKDOWN)

        # If there is a file comment, send it as a separate message
        if comment_file_id and comment_file_type:
            if comment_file_type == 'voice':
                await context.bot.send_voice(chat_id=telegram_id, voice=comment_file_id)
            elif comment_file_type == 'video':
                await context.bot.send_video(chat_id=telegram_id, video=comment_file_id)
            elif comment_file_type == 'document':
                await context.bot.send_document(chat_id=telegram_id, document=comment_file_id)

        logger.info("Notified student %s about grade %s", telegram_id, grade)
        
    except Exception as e:
        logger.exception("Failed to notify student about grade: %s", e)
        await notify_admin_telegram(context.bot, f"Failed to notify student {telegram_id} about grade. Error: {e}")


def _extract_submission_info(message) -> Optional[Dict[str, Any]]:
    """Extract submission info from forwarded message"""
    try:
        text = message.text or message.caption or ""
        
        # Regex extraction for all required fields
        username_match = re.search(r"Student: @(\w+)", text)
        telegram_id_match = re.search(r"Telegram ID: (\d+)", text)
        module_match = re.search(r"Module: (\d+)", text)
        type_match = re.search(r"Type: (\w+)", text)
        
        if username_match and module_match and type_match and telegram_id_match:
            return {
                'username': username_match.group(1),
                'telegram_id': int(telegram_id_match.group(1)),
                'module': module_match.group(1),
                'type': type_match.group(1),
            }
        
        logger.warning("Could not extract all required info from message text: %s", text)
        return None
        
    except Exception as e:
        logger.exception("Failed to extract submission info: %s", e)
        return None


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handler
grade_conv = ConversationHandler(
    entry_points=[CommandHandler("grade", grade_assignment, filters=filters.Chat(chat_id=ASSIGNMENT_GROUP_ID))],
    states={
        GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="^grade_|^grade_cancel$")],
        GRADE_COMMENT: [
            CallbackQueryHandler(grade_comment, pattern="^add_comment$|^no_comment$"),
            MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, add_comment)
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    per_message=False
)


def register_handlers(application):
    """Register all grading handlers with the application"""
    # Add conversation handler
    application.add_handler(grade_conv)
