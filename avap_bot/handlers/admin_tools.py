"""
Admin tools for submissions, achievers, and messaging
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import get_student_submissions, list_achievers, get_all_verified_users
from avap_bot.services.supabase_service import get_supabase
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# Conversation states
GET_SUBMISSION, BROADCAST_MESSAGE, MESSAGE_ACHIEVERS = range(3)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))


async def get_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /get_submission command"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    # Parse command arguments
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📝 **Get Student Submission**\n\n"
            "Usage: `/get_submission <username> <module>`\n"
            "Example: `/get_submission john_doe 1`",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    username = args[0]
    module = args[1]
    
    try:
        # Get submission from Google Sheets
        submissions = await run_blocking(get_student_submissions, username, module)
        
        if not submissions:
            await update.message.reply_text(
                f"❌ No submissions found for @{username} in module {module}",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        # Format and send submission details
        message = f"📝 **Submission Details**\n\n"
        message += f"Student: @{username}\n"
        message += f"Module: {module}\n\n"
        
        for i, submission in enumerate(submissions, 1):
            message += f"**Submission {i}:**\n"
            message += f"Type: {submission.get('type', 'Unknown')}\n"
            message += f"Status: {submission.get('status', 'Unknown')}\n"
            message += f"Submitted: {submission.get('submitted_at', 'Unknown')}\n"
            if submission.get('grade'):
                message += f"Grade: {submission['grade']}/10\n"
            if submission.get('comment'):
                message += f"Comment: {submission['comment']}\n"
            message += "\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.exception("Failed to get submission: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Get submission failed: {str(e)}")
        await update.message.reply_text("❌ Failed to get submission. Please try again.")
    
    return ConversationHandler.END


async def list_achievers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list_achievers command"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return
    
    try:
        # Get achievers from Google Sheets
        achievers = await run_blocking(list_achievers)
        
        if not achievers:
            await update.message.reply_text("📊 No achievers found.")
            return
        
        # Format achievers list
        message = "🏆 **Top Achievers**\n\n"
        for i, achiever in enumerate(achievers, 1):
            username = achiever.get('username', 'Unknown')
            assignments = achiever.get('assignments_count', 0)
            wins = achiever.get('wins_count', 0)
            
            message += f"**{i}. @{username}**\n"
            message += f"   Assignments: {assignments}\n"
            message += f"   Wins: {wins}\n\n"
        
        # Add broadcast button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Broadcast to Achievers", callback_data="broadcast_achievers")]
        ])
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception("Failed to list achievers: %s", e)
        await notify_admin_telegram(context.bot, f"❌ List achievers failed: {str(e)}")
        await update.message.reply_text("❌ Failed to list achievers. Please try again.")


async def broadcast_achievers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast to achievers callback"""
    query = update.callback_query
    await query.answer()
    
    if not _is_admin(update):
        await query.edit_message_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    await query.edit_message_text(
        "📢 **Broadcast to Achievers**\n\n"
        "Please provide the message you want to send to all achievers:",
        parse_mode=ParseMode.MARKDOWN
    )
    return MESSAGE_ACHIEVERS


async def message_achievers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle message to achievers"""
    try:
        message_text = update.message.text.strip()
        
        if len(message_text) < 5:
            await update.message.reply_text("❌ Message must be at least 5 characters long.")
            return MESSAGE_ACHIEVERS
        
        # Get achievers
        achievers = await run_blocking(list_achievers)
        
        if not achievers:
            await update.message.reply_text("❌ No achievers found to message.")
            return ConversationHandler.END
        
        # Send message to each achiever
        sent_count = 0
        failed_count = 0
        
        for achiever in achievers:
            try:
                telegram_id = achiever.get('telegram_id')
                if telegram_id:
                    await context.bot.send_message(
                        telegram_id,
                        f"📢 **Message from Admin**\n\n{message_text}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.exception("Failed to send message to achiever: %s", e)
                failed_count += 1
        
        await update.message.reply_text(
            f"✅ **Broadcast Complete!**\n\n"
            f"Messages sent: {sent_count}\n"
            f"Failed: {failed_count}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Failed to message achievers: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Message achievers failed: {str(e)}")
        await update.message.reply_text("❌ Failed to message achievers. Please try again.")
    
    return ConversationHandler.END


async def broadcast_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /broadcast command"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    # Parse command arguments
    args = context.args
    if not args:
        await update.message.reply_text(
            "📢 **Broadcast Message**\n\n"
            "Usage: `/broadcast <message>`\n"
            "Example: `/broadcast Important announcement for all students!`",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    message_text = " ".join(args)
    
    try:
        # Get all verified users
        client = get_supabase()
        result = client.table('verified_users').select('telegram_id').eq('status', 'verified').execute()
        verified_users = result.data
        
        if not verified_users:
            await update.message.reply_text("❌ No verified users found.")
            return ConversationHandler.END
        
        # Send message to each verified user
        sent_count = 0
        failed_count = 0
        
        for user in verified_users:
            try:
                telegram_id = user.get('telegram_id')
                if telegram_id:
                    await context.bot.send_message(
                        telegram_id,
                        f"📢 **Broadcast Message**\n\n{message_text}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.exception("Failed to send broadcast message: %s", e)
                failed_count += 1
        
        await update.message.reply_text(
            f"✅ **Broadcast Complete!**\n\n"
            f"Messages sent: {sent_count}\n"
            f"Failed: {failed_count}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Failed to broadcast message: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Broadcast failed: {str(e)}")
        await update.message.reply_text("❌ Failed to broadcast message. Please try again.")
    
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Conversation handlers
get_submission_conv = ConversationHandler(
    entry_points=[CommandHandler("get_submission", get_submission)],
    states={},
    fallbacks=[],
    per_message=False
)

message_achievers_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(broadcast_achievers, pattern="^broadcast_achievers$")],
    states={
        MESSAGE_ACHIEVERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_achievers)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    per_message=False
)

broadcast_conv = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_all)],
    states={},
    fallbacks=[],
    per_message=False
)


def register_handlers(application):
    """Register all admin tools handlers with the application"""
    # Add conversation handlers
    application.add_handler(get_submission_conv)
    application.add_handler(message_achievers_conv)
    application.add_handler(broadcast_conv)
    
    # Add command handlers
    application.add_handler(CommandHandler("list_achievers", list_achievers_cmd))


