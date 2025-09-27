"""
Broadcast Messages feature for AVAP bot.
Allows admins to send messages to all verified users.
"""
import logging
import os
import asyncio
from typing import List
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from avap_bot.utils.db_access import get_verified_users, send_with_backoff
from avap_bot.utils.translator import translate

logger = logging.getLogger(__name__)

# Environment variables
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to broadcast message to all verified users."""
    # Check admin access
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin access required.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    message_text = " ".join(context.args)
    
    # Get all verified users
    users = await get_verified_users()
    if not users:
        await update.message.reply_text("No verified users found.")
        return
    
    # Send confirmation to admin
    await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    # Send message to each user
    sent_count = 0
    failed_count = 0
    failed_users = []
    
    for user in users:
        try:
            # Translate message to user's language
            user_lang = user.get('language', DEFAULT_LANGUAGE)
            translated_message = translate(message_text, user_lang)
            
            success = await send_with_backoff(
                context.bot,
                user['telegram_id'],
                translated_message
            )
            
            if success:
                sent_count += 1
            else:
                failed_count += 1
                failed_users.append(f"@{user.get('name', 'Unknown')} ({user['telegram_id']})")
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.2)
            
        except Exception as e:
            logger.exception(f"Failed to send broadcast to user {user['telegram_id']}: {e}")
            failed_count += 1
            failed_users.append(f"@{user.get('name', 'Unknown')} ({user['telegram_id']})")
    
    # Send summary to admin
    summary = f"📊 Broadcast Complete\n\n"
    summary += f"✅ Sent: {sent_count}\n"
    summary += f"❌ Failed: {failed_count}\n"
    summary += f"📝 Message: {message_text[:100]}{'...' if len(message_text) > 100 else ''}"
    
    if failed_users and len(failed_users) <= 10:
        summary += f"\n\n❌ Failed users:\n" + "\n".join(failed_users[:10])
    elif failed_users:
        summary += f"\n\n❌ {len(failed_users)} users failed (too many to list)"
    
    await update.message.reply_text(summary)

def register_handlers(application: Application):
    """Register broadcast handlers."""
    application.add_handler(CommandHandler("broadcast", broadcast_handler))
