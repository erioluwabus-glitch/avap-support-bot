"""
Study Groups Matching feature for AVAP bot.
Pairs students for study collaboration and group formation.
"""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from avap_bot.utils.db_access import add_to_match_queue, get_match_queue, remove_from_match_queue
from avap_bot.utils.matching import pair_students, create_match_message, should_match_students, get_match_stats

logger = logging.getLogger(__name__)

# Environment variables
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
MATCH_SIZE = int(os.getenv("MATCH_SIZE", "2"))

async def match_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /match command from verified users."""
    # Only work in private chats
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use this command in a private chat with the bot.")
        return
    
    user = update.effective_user
    username = user.username or user.full_name or "Unknown"
    
    # Add user to match queue
    success = await add_to_match_queue(user.id, username)
    
    if not success:
        await update.message.reply_text("❌ Failed to add you to the match queue. Please try again.")
        return
    
    # Get current queue
    queue = await get_match_queue()
    
    if len(queue) < MATCH_SIZE:
        await update.message.reply_text(
            f"✅ Added to study match queue! Currently {len(queue)} student(s) waiting. "
            f"We need {MATCH_SIZE} students to form a group."
        )
        return
    
    # Check if we should match now
    if should_match_students(queue):
        await process_matches(context.bot, queue)
    else:
        await update.message.reply_text(
            f"✅ Added to study match queue! Currently {len(queue)} student(s) waiting. "
            f"Matches are processed every few minutes."
        )

async def process_matches(bot, queue):
    """Process matches when enough students are available."""
    try:
        # Group students
        groups = pair_students(queue, MATCH_SIZE)
        
        if not groups:
            return
        
        # Process each group
        for group in groups:
            telegram_ids = [student['telegram_id'] for student in group]
            
            # Send match message to each student in the group
            for student in group:
                try:
                    message = create_match_message(group)
                    await bot.send_message(
                        chat_id=student['telegram_id'],
                        text=message
                    )
                except Exception as e:
                    logger.exception(f"Failed to send match message to {student['telegram_id']}: {e}")
            
            # Remove matched students from queue
            await remove_from_match_queue(telegram_ids)
            
            logger.info(f"Matched group: {[s['username'] for s in group]}")
    
    except Exception as e:
        logger.exception(f"Failed to process matches: {e}")

async def match_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view match queue status."""
    # Check admin access
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin access required.")
        return
    
    queue = await get_match_queue()
    stats = get_match_stats(queue)
    
    message = f"📊 Match Queue Status\n\n"
    message += f"👥 Students in queue: {stats['total']}\n"
    message += f"⏱️ Average wait time: {stats['waiting_time']:.1f} minutes\n"
    message += f"🕐 Oldest wait: {stats['oldest_wait']:.1f} minutes\n"
    message += f"🕐 Newest wait: {stats['newest_wait']:.1f} minutes\n"
    message += f"🎯 Match size: {MATCH_SIZE}\n\n"
    
    if queue:
        message += "👥 Current queue:\n"
        for i, student in enumerate(queue[:10], 1):  # Show first 10
            message += f"{i}. @{student['username']} (waiting {stats['oldest_wait']:.1f}m)\n"
        
        if len(queue) > 10:
            message += f"... and {len(queue) - 10} more students"
    else:
        message += "No students currently in queue."
    
    await update.message.reply_text(message)

async def force_match_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to force process matches."""
    # Check admin access
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin access required.")
        return
    
    queue = await get_match_queue()
    
    if len(queue) < MATCH_SIZE:
        await update.message.reply_text(f"Not enough students in queue. Need {MATCH_SIZE}, have {len(queue)}.")
        return
    
    await process_matches(context.bot, queue)
    await update.message.reply_text("✅ Forced match processing completed.")

def register_handlers(application: Application):
    """Register group matching handlers."""
    application.add_handler(CommandHandler("match", match_handler))
    application.add_handler(CommandHandler("match_status", match_status_handler))
    application.add_handler(CommandHandler("force_match", force_match_handler))
