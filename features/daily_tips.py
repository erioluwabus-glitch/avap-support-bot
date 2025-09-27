"""
Daily Tips feature for AVAP bot.
Posts daily inspirational tips to support group and optionally to verified users.
"""
import logging
import os
import asyncio
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from avap_bot.utils.db_access import get_random_daily_tip, add_daily_tip, get_verified_users, send_with_backoff
from avap_bot.utils.translator import translate

logger = logging.getLogger(__name__)

# Environment variables
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0")) if os.getenv("SUPPORT_GROUP_ID") else None
DAILY_TIPS_TO_DMS = os.getenv("DAILY_TIPS_TO_DMS", "false").lower() == "true"
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

# Fallback tips if database is empty
FALLBACK_TIPS = [
    "Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill",
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Don't watch the clock; do what it does. Keep going. - Sam Levenson",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "It is during our darkest moments that we must focus to see the light. - Aristotle",
    "Success is walking from failure to failure with no loss of enthusiasm. - Winston Churchill",
    "The way to get started is to quit talking and begin doing. - Walt Disney",
    "Your limitation—it's only your imagination.",
    "Push yourself, because no one else is going to do it for you.",
    "Sometimes later becomes never. Do it now.",
    "Great things never come from comfort zones.",
    "Dream it. Wish it. Do it.",
    "Success doesn't just find you. You have to go out and get it.",
    "The harder you work for something, the greater you'll feel when you achieve it.",
    "Dream bigger. Do bigger.",
    "Don't stop when you're tired. Stop when you're done.",
    "Wake up with determination. Go to bed with satisfaction.",
    "Do something today that your future self will thank you for.",
    "Little things make big days.",
    "It's going to be hard, but hard does not mean impossible."
]

async def get_daily_tip() -> str:
    """Get a daily tip from database or fallback list."""
    tip = await get_random_daily_tip()
    if not tip:
        # Use fallback tips if database is empty
        import random
        tip = random.choice(FALLBACK_TIPS)
    
    return tip

async def send_daily_tip(application: Application):
    """Send daily tip to support group and optionally to verified users."""
    try:
        tip = await get_daily_tip()
        message = f"💡 Daily Tip: {tip}\n\n/verify to access features or /ask to ask a question."
        
        # Send to support group
        if SUPPORT_GROUP_ID:
            try:
                await application.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=message)
                logger.info("Daily tip sent to support group")
            except Exception as e:
                logger.exception(f"Failed to send daily tip to support group: {e}")
        
        # Send to verified users if enabled
        if DAILY_TIPS_TO_DMS:
            users = await get_verified_users()
            sent_count = 0
            failed_count = 0
            
            for user in users:
                try:
                    # Translate message to user's language
                    user_lang = user.get('language', DEFAULT_LANGUAGE)
                    translated_message = translate(message, user_lang)
                    
                    success = await send_with_backoff(
                        application.bot, 
                        user['telegram_id'], 
                        translated_message
                    )
                    
                    if success:
                        sent_count += 1
                    else:
                        failed_count += 1
                        
                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.2)
                    
                except Exception as e:
                    logger.exception(f"Failed to send daily tip to user {user['telegram_id']}: {e}")
                    failed_count += 1
            
            logger.info(f"Daily tips sent to {sent_count} users, {failed_count} failures")
        
    except Exception as e:
        logger.exception(f"Failed to send daily tip: {e}")

async def add_tip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add a daily tip."""
    # Check admin access
    admin_ids = os.getenv("ADMIN_IDS", "").split(",")
    admin_ids = [int(id.strip()) for id in admin_ids if id.strip()]
    
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text("Admin access required.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add_tip <tip text>")
        return
    
    tip_text = " ".join(context.args)
    success = await add_daily_tip(tip_text)
    
    if success:
        await update.message.reply_text(f"✅ Daily tip added: {tip_text}")
    else:
        await update.message.reply_text("❌ Failed to add daily tip.")

def register_handlers(application: Application):
    """Register daily tips handlers."""
    application.add_handler(CommandHandler("add_tip", add_tip_handler))

def schedule_daily_job(application: Application):
    """Schedule the daily tips job."""
    from avap_bot.utils.scheduling import get_scheduler, schedule_daily_job
    
    scheduler = get_scheduler()
    schedule_daily_job(scheduler, send_daily_tip, application)
    
    if not scheduler.running:
        scheduler.start()
        logger.info("Daily tips scheduler started")
