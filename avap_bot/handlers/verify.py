"""
Student verification handlers
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode, ChatType

from avap_bot.services.supabase_service import (
    find_pending_by_email_or_phone, find_verified_by_email_or_phone,
    promote_pending_to_verified, check_verified_user
)
from avap_bot.services.sheets_service import update_verification_status
from avap_bot.services.systeme_service import create_contact_and_tag
from avap_bot.utils.validators import validate_email, validate_phone
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# Conversation states
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = range(3)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
VERIFICATION_GROUP_ID = int(os.getenv("VERIFICATION_GROUP_ID", "0"))
LANDING_PAGE_URL = os.getenv("LANDING_PAGE_URL", "https://avap.com")


async def verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the verification process"""
    user_id = update.effective_user.id
    
    # Check if already verified
    verified_user = check_verified_user(user_id)
    if verified_user:
        await update.message.reply_text(
            f"✅ **You're already verified!**\n\n"
            f"Welcome back, {verified_user['name']}!\n"
            f"Use the menu below to access all features.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🔐 **Student Verification**\n\n"
        "Please provide your full name as registered:",
        parse_mode=ParseMode.MARKDOWN
    )
    return VERIFY_NAME


async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle name input for verification"""
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Please provide a valid name (at least 2 characters).")
        return VERIFY_NAME
    
    context.user_data['verify_name'] = name
    await update.message.reply_text(
        f"📱 **Phone Number**\n\n"
        f"Name: {name}\n"
        "Please provide your phone number:",
        parse_mode=ParseMode.MARKDOWN
    )
    return VERIFY_PHONE


async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone input for verification"""
    phone = update.message.text.strip()
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ Invalid phone number format. Please provide a valid phone number:"
        )
        return VERIFY_PHONE
    
    context.user_data['verify_phone'] = phone
    await update.message.reply_text(
        f"📧 **Email Address**\n\n"
        f"Name: {context.user_data['verify_name']}\n"
        f"Phone: {phone}\n"
        "Please provide your email address:",
        parse_mode=ParseMode.MARKDOWN
    )
    return VERIFY_EMAIL


async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle email input and complete verification"""
    email = update.message.text.strip().lower()
    
    if not validate_email(email):
        await update.message.reply_text(
            "❌ Invalid email format. Please provide a valid email address:"
        )
        return VERIFY_EMAIL
    
    name = context.user_data['verify_name']
    phone = context.user_data['verify_phone']
    user_id = update.effective_user.id
    username = update.effective_user.username or "unknown"
    
    try:
        # Check if already verified
        verified_existing = find_verified_by_email_or_phone(email, phone)
        if verified_existing:
            await update.message.reply_text(
                f"✅ **Already Verified!**\n\n"
                f"Your account is already verified.\n"
                f"Use the menu below to access all features.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        # Check pending verifications
        pending_existing = find_pending_by_email_or_phone(email, phone)
        if not pending_existing:
            await update.message.reply_text(
                f"❌ **Verification Not Found**\n\n"
                f"Your details were not found in our system.\n"
                f"Please contact an admin for verification.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        # Find the matching pending verification
        pending_match = None
        for pending in pending_existing:
            if (pending.get('email', '').lower() == email and 
                pending.get('phone', '') == phone and 
                pending.get('name', '').lower() == name.lower()):
                pending_match = pending
                break
        
        if not pending_match:
            await update.message.reply_text(
                f"❌ **Details Don't Match**\n\n"
                f"Your details don't match our records.\n"
                f"Please contact an admin for verification.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        # Promote to verified
        verified_data = promote_pending_to_verified(pending_match['id'], user_id)
        if not verified_data:
            raise Exception("Failed to promote pending to verified")
        
        # Update Google Sheets
        await run_blocking(update_verification_status, email, 'Verified')
        
        # Update Systeme.io
        await create_contact_and_tag(verified_data)
        
        # Show success message with menu
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Submit Assignment", callback_data="submit")],
            [InlineKeyboardButton("🏆 Share Win", callback_data="share_win")],
            [InlineKeyboardButton("📊 Check Status", callback_data="status")],
            [InlineKeyboardButton("❓ Ask Question", callback_data="ask")]
        ])
        
        await update.message.reply_text(
            f"🎉 **Welcome to AVAP!**\n\n"
            f"Congratulations! You're now verified and have access to all features.\n\n"
            f"**Your Course:** {LANDING_PAGE_URL}\n\n"
            f"Choose an option below to get started:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
        # Notify admin
        if VERIFICATION_GROUP_ID:
            await context.bot.send_message(
                VERIFICATION_GROUP_ID,
                f"✅ **Student Self-Verified**\n\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Phone: {phone}\n"
                f"Telegram: @{username}",
                parse_mode=ParseMode.MARKDOWN
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to verify student: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Student verification failed: {str(e)}")
        await update.message.reply_text(
            f"❌ Verification failed. Please try again or contact admin."
        )
        return ConversationHandler.END


async def admin_verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin manual verification command"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🔐 **Admin Verification**\n\n"
            "Usage: /verify <email or phone>\n"
            "Example: /verify student@example.com",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    identifier = context.args[0]
    
    try:
        # Find pending verification
        pending_existing = find_pending_by_email_or_phone(identifier, identifier)
        if not pending_existing:
            await update.message.reply_text(
                f"❌ No pending verification found for: {identifier}"
            )
            return
        
        pending = pending_existing[0]
        
        # Promote to verified
        verified_data = promote_pending_to_verified(pending['id'])
        if not verified_data:
            raise Exception("Failed to promote pending to verified")
        
        # Update Google Sheets
        await run_blocking(update_verification_status, verified_data['email'], 'Verified')
        
        # Update Systeme.io
        await create_contact_and_tag(verified_data)
        
        await update.message.reply_text(
            f"✅ **Student Verified!**\n\n"
            f"Name: {verified_data['name']}\n"
            f"Email: {verified_data['email']}\n"
            f"Phone: {verified_data['phone']}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Admin verify command failed: %s", e)
        await update.message.reply_text(f"❌ Verification failed: {str(e)}")


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handler
verify_conv = ConversationHandler(
    entry_points=[CommandHandler("verify", verify_start)],
    states={
        VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
        VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
        VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    per_message=False
)


def register_handlers(application):
    """Register verification handlers"""
    # Add conversation handler
    application.add_handler(verify_conv)
    
    # Add admin verify command
    application.add_handler(CommandHandler("verify", admin_verify_command, filters=filters.ChatType.PRIVATE))
