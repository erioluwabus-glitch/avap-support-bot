"""
Daily tips handlers and scheduling
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from services.sheets_service import append_tip, get_manual_tips
from utils.run_blocking import run_blocking
from services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# Conversation states
ADD_TIP = range(1)

SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


async def add_tip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start add tip conversation"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "💡 **Add Daily Tip**\n\n"
        "Please provide the tip content:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_TIP


async def add_tip_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle tip content input"""
    try:
        tip_content = update.message.text.strip()
        
        if len(tip_content) < 10:
            await update.message.reply_text("❌ Tip must be at least 10 characters long.")
            return ADD_TIP
        
        # Save tip to Google Sheets
        tip_data = {
            'content': tip_content,
            'added_by': update.effective_user.username or "admin",
            'added_at': datetime.now(timezone.utc),
            'type': 'manual'
        }
        
        success = await run_blocking(append_tip, tip_data)
        
        if success:
            await update.message.reply_text(
                f"✅ **Tip Added Successfully!**\n\n"
                f"Content: {tip_content[:100]}{'...' if len(tip_content) > 100 else ''}\n"
                f"Type: Manual\n"
                f"This tip will be included in the daily rotation.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Failed to add tip. Please try again.")
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to add tip: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Add tip failed: {str(e)}")
        await update.message.reply_text("❌ Failed to add tip. Please try again.")
        return ConversationHandler.END


async def schedule_daily_tips(bot, scheduler):
    """Schedule daily tips job"""
    try:
        # Schedule for 8:00 AM WAT (UTC+1)
        scheduler.add_job(
            send_daily_tip,
            'cron',
            hour=8,
            minute=0,
            timezone='Africa/Lagos',
            args=[bot],
            id='daily_tips',
            replace_existing=True
        )
        logger.info("Daily tips job scheduled for 8:00 AM WAT")
        
    except Exception as e:
        logger.exception("Failed to schedule daily tips: %s", e)


async def send_daily_tip(bot):
    """Send daily tip to support group"""
    try:
        if not SUPPORT_GROUP_ID:
            logger.warning("SUPPORT_GROUP_ID not set, cannot send daily tip")
            return
        
        # Get tip content
        tip_content = await _get_daily_tip_content()
        
        if not tip_content:
            logger.warning("No tip content available")
            return
        
        # Send tip to support group
        await bot.send_message(
            SUPPORT_GROUP_ID,
            f"💡 **Daily Tip**\n\n{tip_content}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info("Daily tip sent successfully")
        
    except Exception as e:
        logger.exception("Failed to send daily tip: %s", e)
        await notify_admin_telegram(bot, f"❌ Daily tip failed: {str(e)}")


async def _get_daily_tip_content() -> Optional[str]:
    """Get daily tip content (manual or AI-generated)"""
    try:
        # Try to get manual tips first
        manual_tips = await run_blocking(get_manual_tips)
        
        if manual_tips:
            # Use manual tip (simple rotation)
            tip = manual_tips[0]  # In real implementation, use proper rotation
            return tip.get('content', '')
        
        # Fallback to AI-generated tip
        if OPENAI_API_KEY:
            return await _generate_ai_tip()
        
        # Default tip if no manual or AI available
        return "💡 Remember: Consistency is key to success! Keep working on your goals every day."
        
    except Exception as e:
        logger.exception("Failed to get daily tip content: %s", e)
        return None


async def _generate_ai_tip() -> Optional[str]:
    """Generate AI tip using OpenAI"""
    try:
        import openai
        
        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a motivational coach. Generate a short, inspiring daily tip for students learning programming and personal development. Keep it under 200 characters."},
                {"role": "user", "content": "Generate a daily tip for today."}
            ],
            max_tokens=100,
            temperature=0.7
        )
        
        tip = response.choices[0].message.content.strip()
        return tip if tip else None
        
    except Exception as e:
        logger.exception("Failed to generate AI tip: %s", e)
        return None


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handler
add_tip_conv = ConversationHandler(
    entry_points=[CommandHandler("add_tip", add_tip_start)],
    states={
        ADD_TIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tip_content)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    per_message=False
)
