"""
Grading handlers for assignment evaluation
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from services.sheets_service import update_submission_grade, add_grade_comment
from utils.run_blocking import run_blocking
from services.notifier import notify_admin_telegram

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
        await update.message.reply_text("❌ Could not extract submission information.")
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
        await _notify_student_grade(context.user_data['submission_info'], context.user_data.get('grade'), None)
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
        comment_file_name = None
        
        if update.message.document:
            comment_file_id = update.message.document.file_id
            comment_file_name = update.message.document.file_name
            comment_text = f"Document: {comment_file_name}"
        elif update.message.voice:
            comment_file_id = update.message.voice.file_id
            comment_file_name = f"comment_voice_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.ogg"
            comment_text = "Voice comment"
        elif update.message.video:
            comment_file_id = update.message.video.file_id
            comment_file_name = update.message.video.file_name or f"comment_video_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
            comment_text = "Video comment"
        elif update.message.text:
            comment_text = update.message.text
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
        await _notify_student_grade(submission_info, grade, comment_text, comment_file_id)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to add comment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Comment addition failed: {str(e)}")
        await update.message.reply_text("❌ Failed to add comment. Please try again.")
        return ConversationHandler.END


async def _notify_student_grade(submission_info: Dict[str, Any], grade: int, comment: Optional[str], comment_file_id: Optional[str] = None):
    """Notify student about their grade"""
    try:
        telegram_id = submission_info.get('telegram_id')
        if not telegram_id:
            return
        
        message = (
            f"📝 **Assignment Graded!**\n\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {grade}/10\n"
        )
        
        if comment:
            message += f"Comment: {comment}\n"
        
        # Send notification (this would need bot context in real implementation)
        logger.info("Would notify student %s about grade %s", telegram_id, grade)
        
    except Exception as e:
        logger.exception("Failed to notify student about grade: %s", e)


def _extract_submission_info(message) -> Optional[Dict[str, Any]]:
    """Extract submission info from forwarded message"""
    try:
        # This is a simplified extraction - in real implementation,
        # you'd parse the forwarded message text to extract username, module, etc.
        text = message.text or message.caption or ""
        
        # Simple regex extraction (would need more robust parsing)
        import re
        username_match = re.search(r'@(\w+)', text)
        module_match = re.search(r'Module: (\d+)', text)
        type_match = re.search(r'Type: (\w+)', text)
        
        if username_match and module_match and type_match:
            return {
                'username': username_match.group(1),
                'module': module_match.group(1),
                'type': type_match.group(1),
                'telegram_id': 0  # Would need to be extracted or looked up
            }
        
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
    entry_points=[CommandHandler("grade", grade_assignment)],
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
