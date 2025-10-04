"""
Answer handlers for responding to student questions
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.supabase_service import update_question_answer, get_faqs
from avap_bot.services.sheets_service import update_question_status
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Conversation states
ANSWER_CONTENT = range(1)

QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


async def answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /answer command for responding to questions"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    # Check if this is a forwarded question
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Please reply to a forwarded question to answer it.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    # Extract question info from forwarded message
    question_info = _extract_question_info(update.message.reply_to_message)
    if not question_info:
        await update.message.reply_text("❌ Could not extract question information.")
        return ConversationHandler.END
    
    context.user_data['question_info'] = question_info
    
    # Show answer type options
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Text Answer", callback_data="answer_text")],
        [InlineKeyboardButton("🎤 Voice Answer", callback_data="answer_voice")],
        [InlineKeyboardButton("🎥 Video Answer", callback_data="answer_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="answer_cancel")]
    ])
    
    await update.message.reply_text(
        f"❓ **Answer Question**\n\n"
        f"Student: @{question_info.get('username', 'unknown')}\n"
        f"Question: {question_info.get('question', 'N/A')[:100]}...\n\n"
        f"Choose answer type:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    
    return ANSWER_CONTENT


async def answer_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle answer type selection"""
    query = update.callback_query
    await query.answer()
    
    answer_type = query.data.replace("answer_", "")
    
    if answer_type == "cancel":
        await query.edit_message_text("❌ Answer cancelled.")
        return ConversationHandler.END
    
    context.user_data['answer_type'] = answer_type
    
    if answer_type == "text":
        await query.edit_message_text(
            "📝 **Text Answer**\n\n"
            "Please type your answer:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif answer_type == "voice":
        await query.edit_message_text(
            "🎤 **Voice Answer**\n\n"
            "Please send a voice message:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif answer_type == "video":
        await query.edit_message_text(
            "🎥 **Video Answer**\n\n"
            "Please send a video:",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return ANSWER_CONTENT


async def answer_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle answer content submission"""
    try:
        question_info = context.user_data.get('question_info')
        answer_type = context.user_data.get('answer_type')
        
        if not question_info or not answer_type:
            await update.message.reply_text("❌ Missing question information. Please try again.")
            return ConversationHandler.END
        
        # Get answer content based on type
        if answer_type == "text":
            answer_content = update.message.text
            file_id = None
        elif answer_type == "voice":
            if not update.message.voice:
                await update.message.reply_text("❌ Please send a voice message.")
                return ANSWER_CONTENT
            answer_content = "Voice message"
            file_id = update.message.voice.file_id
        elif answer_type == "video":
            if not update.message.video:
                await update.message.reply_text("❌ Please send a video.")
                return ANSWER_CONTENT
            answer_content = "Video message"
            file_id = update.message.video.file_id
        else:
            await update.message.reply_text("❌ Invalid answer type.")
            return ConversationHandler.END
        
        # Update question with answer in Supabase
        question_id = question_info.get('question_id')
        if question_id:
            success = await run_blocking(update_question_answer, question_id, answer_content)
            if not success:
                logger.warning("Failed to update question answer in Supabase")
        
        # Update Google Sheets
        await run_blocking(update_question_status, question_info.get('username'), 'answered')
        
        # Send answer to student
        student_id = question_info.get('student_id')
        if student_id:
            try:
                if file_id:
                    # Send media with text
                    if answer_type == "voice":
                        await context.bot.send_voice(
                            student_id,
                            voice=file_id,
                            caption=f"📝 **Answer to your question:**\n\n{answer_content}"
                        )
                    elif answer_type == "video":
                        await context.bot.send_video(
                            student_id,
                            video=file_id,
                            caption=f"📝 **Answer to your question:**\n\n{answer_content}"
                        )
                else:
                    # Send text only
                    await context.bot.send_message(
                        student_id,
                        f"📝 **Answer to your question:**\n\n{answer_content}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                await update.message.reply_text(
                    f"✅ **Answer sent successfully!**\n\n"
                    f"Student: @{question_info.get('username', 'unknown')}\n"
                    f"Type: {answer_type.title()}\n"
                    f"Content: {answer_content[:100]}{'...' if len(answer_content) > 100 else ''}",
                    parse_mode=ParseMode.MARKDOWN
                )
                
            except Exception as e:
                logger.exception("Failed to send answer to student: %s", e)
                await update.message.reply_text(
                    f"⚠️ Answer saved but failed to send to student: {str(e)}"
                )
        else:
            await update.message.reply_text(
                f"✅ **Answer saved!**\n\n"
                f"Note: Could not send to student (no student ID found)",
                parse_mode=ParseMode.MARKDOWN
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to process answer: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Answer processing failed: {str(e)}")
        await update.message.reply_text("❌ Failed to process answer. Please try again.")
        return ConversationHandler.END


def _extract_question_info(message) -> Optional[Dict[str, Any]]:
    """Extract question information from forwarded message"""
    try:
        # This is a simplified extraction - in real implementation,
        # you'd parse the message text more carefully
        text = message.text or message.caption or ""
        
        # Look for patterns in the forwarded message
        # This would need to be customized based on how questions are formatted
        # when forwarded from the student handler
        
        return {
            'question_id': None,  # Would need to be extracted from message
            'student_id': None,   # Would need to be extracted from message
            'username': 'unknown',
            'question': text[:200] + "..." if len(text) > 200 else text
        }
        
    except Exception as e:
        logger.exception("Failed to extract question info: %s", e)
        return None


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handler
answer_conv = ConversationHandler(
    entry_points=[CommandHandler("answer", answer_question)],
    states={
        ANSWER_CONTENT: [
            CallbackQueryHandler(answer_type_callback, pattern="^answer_"),
            MessageHandler(filters.TEXT | filters.VOICE | filters.VIDEO, answer_content)
        ],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True
)


def register_handlers(application):
    """Register all answer handlers with the application"""
    # Add conversation handler
    application.add_handler(answer_conv)
    
    # Add callback query handler for answer type selection
    application.add_handler(CallbackQueryHandler(answer_type_callback, pattern="^answer_"))
