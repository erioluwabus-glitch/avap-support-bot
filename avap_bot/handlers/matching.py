"""
Student matching handlers for peer connections
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set
from collections import defaultdict

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from services.supabase_service import get_supabase
from services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# In-memory matching queue (in production, use Redis or database)
matching_queue: Set[int] = set()
matched_pairs: Dict[int, int] = {}  # user_id -> matched_user_id

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


async def match_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /match command for student pairing"""
    user_id = update.effective_user.id
    
    # Check if user is verified
    if not await _is_verified_student(user_id):
        await update.message.reply_text(
            "❌ You must be a verified student to use the matching feature.\n"
            "Please contact an admin for verification.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if already in queue
    if user_id in matching_queue:
        await update.message.reply_text(
            "⏳ You're already in the matching queue. Please wait for a match!",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if already matched
    if user_id in matched_pairs:
        matched_user_id = matched_pairs[user_id]
        await update.message.reply_text(
            f"✅ You're already matched with another student!\n"
            f"Your match: @{await _get_username(matched_user_id)}",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add to queue
    matching_queue.add(user_id)
    
    await update.message.reply_text(
        "🔍 **Looking for a match...**\n\n"
        "You've been added to the matching queue. "
        "I'll notify you when I find another student to pair you with!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Try to find a match
    await _try_match_students(context.bot)


async def _try_match_students(bot):
    """Try to match students in the queue"""
    try:
        if len(matching_queue) < 2:
            return
        
        # Get two students from queue
        student1 = matching_queue.pop()
        student2 = matching_queue.pop()
        
        # Create match
        matched_pairs[student1] = student2
        matched_pairs[student2] = student1
        
        # Notify both students
        await _notify_match(bot, student1, student2)
        await _notify_match(bot, student2, student1)
        
        logger.info("Matched students: %s and %s", student1, student2)
        
    except Exception as e:
        logger.exception("Failed to match students: %s", e)
        await notify_admin_telegram(bot, f"❌ Matching failed: {str(e)}")


async def _notify_match(bot, user_id: int, matched_user_id: int):
    """Notify student about their match"""
    try:
        username = await _get_username(matched_user_id)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Start Chat", callback_data=f"start_chat_{matched_user_id}")],
            [InlineKeyboardButton("🔄 Find Another Match", callback_data="find_another")]
        ])
        
        await bot.send_message(
            user_id,
            f"🎉 **Match Found!**\n\n"
            f"You've been matched with: @{username}\n\n"
            f"You can now start chatting and collaborating!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception("Failed to notify match: %s", e)


async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start chat callback"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("start_chat_"):
        matched_user_id = int(query.data.split("_")[2])
        username = await _get_username(matched_user_id)
        
        await query.edit_message_text(
            f"💬 **Chat Started!**\n\n"
            f"You're now connected with @{username}\n\n"
            f"Start your conversation and collaborate on your learning journey!",
            parse_mode=ParseMode.MARKDOWN
        )


async def find_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle find another match callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Remove from current match
    if user_id in matched_pairs:
        matched_user_id = matched_pairs[user_id]
        del matched_pairs[user_id]
        if matched_user_id in matched_pairs:
            del matched_pairs[matched_user_id]
    
    # Add back to queue
    matching_queue.add(user_id)
    
    await query.edit_message_text(
        "🔍 **Looking for another match...**\n\n"
        "You've been added back to the matching queue. "
        "I'll notify you when I find another student!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Try to find a new match
    await _try_match_students(context.bot)


async def _is_verified_student(user_id: int) -> bool:
    """Check if user is a verified student"""
    try:
        client = get_supabase()
        result = client.table('verified_users').select('id').eq('telegram_id', user_id).eq('status', 'verified').execute()
        return len(result.data) > 0
    except Exception as e:
        logger.exception("Failed to check verification status: %s", e)
        return False


async def _get_username(user_id: int) -> str:
    """Get username for user ID"""
    try:
        # In a real implementation, you'd fetch this from Telegram API or database
        return f"user_{user_id}"
    except Exception as e:
        logger.exception("Failed to get username: %s", e)
        return "Unknown User"


def register_handlers(application):
    """Register all matching handlers with the application"""
    # Add command handler
    application.add_handler(CommandHandler("match", match_student))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(start_chat, pattern="^start_chat_"))
    application.add_handler(CallbackQueryHandler(find_another, pattern="^find_another$"))


