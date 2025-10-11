"""
Tips system handlers for daily motivational tips
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.supabase_service import (
    add_tip, get_all_tips, get_random_tip, update_tip_sent_count,
    get_all_verified_telegram_ids
)
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Get cancel fallback handler
_cancel_fallback_handler = get_cancel_fallback_handler()

# Conversation states
ADD_TIP_TEXT = range(1)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


async def add_tip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start add tip conversation"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "💡 **Add Daily Tip**\n\n"
        "Please provide the tip text:",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADD_TIP_TEXT


async def add_tip_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle tip text input"""
    tip_text = update.message.text.strip()
    
    if not tip_text or len(tip_text) < 10:
        await update.message.reply_text(
            "❌ Please provide a meaningful tip (at least 10 characters)."
        )
        return ADD_TIP_TEXT
    
    try:
        # Add tip to database
        tip_data = add_tip(
            text=tip_text,
            created_by=update.effective_user.id
        )
        
        if tip_data:
            await update.message.reply_text(
                f"✅ **Tip Added Successfully!**\n\n"
                f"**Tip:** {tip_text}\n"
                f"**ID:** {tip_data.get('id', 'N/A')}\n"
                f"**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Failed to add tip.")
            
    except Exception as e:
        logger.exception("Add tip command failed: %s", e)
        await update.message.reply_text("❌ Error occurred while adding tip.")
    
    return ConversationHandler.END


async def send_tip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random tip to all verified students"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return

    try:
        # Get random tip
        tip = get_random_tip()
        
        if not tip:
            await update.message.reply_text("📭 No tips available. Add some tips first using /add_tip")
            return
        
        # Get all verified users
        verified_users = get_all_verified_telegram_ids()
        
        if not verified_users:
            await update.message.reply_text("👥 No verified users found.")
            return
        
        # Send tip to all verified users
        success_count = 0
        failure_count = 0
        
        await update.message.reply_text(f"📤 Sending tip to {len(verified_users)} users...")
        
        tip_message = f"💡 **Daily Tip**\n\n{tip.get('text', '')}"
        
        for user_id in verified_users:
            try:
                await context.bot.send_message(user_id, tip_message, parse_mode=ParseMode.MARKDOWN)
                success_count += 1
                
                # Rate limiting
                await asyncio.sleep(0.03)
                
            except Exception as e:
                logger.warning(f"Failed to send tip to user {user_id}: {e}")
                failure_count += 1
        
        # Update tip sent count
        try:
            update_tip_sent_count(tip.get('id'))
        except Exception as e:
            logger.warning(f"Failed to update tip sent count: {e}")
        
        # Send completion message
        await update.message.reply_text(
            f"✅ **Tip Sent Successfully!**\n\n"
            f"📤 Sent: {success_count}\n"
            f"❌ Failed: {failure_count}\n"
            f"📊 Total: {len(verified_users)}\n\n"
            f"**Tip:** {tip.get('text', '')[:100]}{'...' if len(tip.get('text', '')) > 100 else ''}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Send tip command failed: %s", e)
        await update.message.reply_text("❌ Error occurred while sending tip.")


async def test_tip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test tip by sending to admin only"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return

    try:
        # Get random tip
        tip = get_random_tip()
        
        if not tip:
            await update.message.reply_text("📭 No tips available. Add some tips first using /add_tip")
            return
        
        # Send tip to admin
        tip_message = f"💡 **Daily Tip (Test)**\n\n{tip.get('text', '')}"
        
        await update.message.reply_text(
            tip_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        await update.message.reply_text(
            f"✅ **Test Tip Sent!**\n\n"
            f"**Tip ID:** {tip.get('id', 'N/A')}\n"
            f"**Sent Count:** {tip.get('sent_count', 0)}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Test tip command failed: %s", e)
        await update.message.reply_text("❌ Error occurred while testing tip.")


async def list_tips_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all tips (admin only)"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return

    try:
        # Get all tips
        tips = get_all_tips()
        
        if not tips:
            await update.message.reply_text("📭 No tips found. Add some tips using /add_tip")
            return

        # Format the message
        message = f"💡 **All Tips** ({len(tips)} total)\n\n"
        
        for i, tip in enumerate(tips[:10], 1):  # Limit to 10 for readability
            created_at = tip.get('created_at', 'Unknown')
            if created_at != 'Unknown':
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    created_at = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            text_preview = tip.get('text', '')[:100]
            if len(tip.get('text', '')) > 100:
                text_preview += "..."
            
            message += f"**{i}.** ID: {tip.get('id', 'N/A')}\n"
            message += f"📅 Created: {created_at}\n"
            message += f"📤 Sent: {tip.get('sent_count', 0)} times\n"
            message += f"💬 Text: {text_preview}\n\n"

        if len(tips) > 10:
            message += f"... and {len(tips) - 10} more tips."

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception("List tips command failed: %s", e)
        await update.message.reply_text("❌ Error occurred while fetching tips.")


async def send_daily_tip():
    """Send daily tip to all verified users (scheduled function)"""
    try:
        from avap_bot.services.supabase_service import get_supabase
        from avap_bot.bot import bot_app
        
        # Get random tip
        tip = get_random_tip()
        
        if not tip:
            logger.warning("No tips available for daily sending")
            return
        
        # Get all verified users
        verified_users = get_all_verified_telegram_ids()
        
        if not verified_users:
            logger.warning("No verified users found for daily tip")
            return
        
        # Send tip to all verified users
        success_count = 0
        failure_count = 0
        
        tip_message = f"💡 **Daily Tip**\n\n{tip.get('text', '')}"
        
        for user_id in verified_users:
            try:
                await bot_app.bot.send_message(user_id, tip_message, parse_mode=ParseMode.MARKDOWN)
                success_count += 1
                
                # Rate limiting
                await asyncio.sleep(0.03)
                
            except Exception as e:
                logger.warning(f"Failed to send daily tip to user {user_id}: {e}")
                failure_count += 1
        
        # Update tip sent count
        try:
            update_tip_sent_count(tip.get('id'))
        except Exception as e:
            logger.warning(f"Failed to update tip sent count: {e}")
        
        logger.info(f"Daily tip sent: {success_count} success, {failure_count} failures")
        
    except Exception as e:
        logger.exception("Daily tip sending failed: %s", e)


# Conversation handlers
fallbacks = [get_cancel_fallback_handler()] if get_cancel_fallback_handler() else []
add_tip_conv = ConversationHandler(
    entry_points=[CommandHandler("add_tip", add_tip_start)],
    states={
        ADD_TIP_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_tip_text)],
    },
    fallbacks=fallbacks,
    per_message=False,
    conversation_timeout=600
)


def register_handlers(application):
    """Register all tips handlers with the application"""
    # Add conversation handlers
    application.add_handler(add_tip_conv)

    # Add simple command handlers
    application.add_handler(CommandHandler("send_tip", send_tip_handler))
    application.add_handler(CommandHandler("test_tip", test_tip_handler))
    application.add_handler(CommandHandler("list_tips", list_tips_handler))
