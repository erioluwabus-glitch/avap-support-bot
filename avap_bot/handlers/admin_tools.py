"""
Admin tools for submissions, achievers, and messaging
"""
import os
import logging
import asyncio
import csv
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ConversationHandler
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import get_student_submissions, list_achievers, get_all_verified_users
from avap_bot.services.supabase_service import get_supabase
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Conversation states
GET_SUBMISSION, BROADCAST_MESSAGE, MESSAGE_ACHIEVERS, BROADCAST_TYPE, BROADCAST_CONTENT = range(5)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))

def log_missing_telegram_ids(users: List[Dict[str, Any]]):
    """Logs users with missing telegram IDs to a CSV file."""
    report_dir = "deprecated_from_audit/reports"
    os.makedirs(report_dir, exist_ok=True)
    filepath = os.path.join(report_dir, "achievers_missing_telegram_id.csv")
    
    file_exists = os.path.isfile(filepath)
    
    try:
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'username', 'assignments', 'wins'])
            
            for user in users:
                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    user.get('username'),
                    user.get('assignments'),
                    user.get('wins')
                ])
        logger.info(f"Logged {len(users)} users with missing telegram_id to {filepath}")
    except Exception as e:
        logger.error(f"Failed to log missing telegram_ids to CSV: {e}")

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
            assignments = achiever.get('assignments', 0)
            wins = achiever.get('wins', 0)
            
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
        failed_users = []
        
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
                    failed_users.append(achiever)
            except Exception as e:
                logger.exception("Failed to send message to achiever: %s", e)
                failed_users.append(achiever)
        
        failed_count = len(failed_users)
        if failed_users:
            log_missing_telegram_ids(failed_users)

        await update.message.reply_text(
            f"✅ **Broadcast Complete!**\n\n"
            f"Messages sent: {sent_count}\n"
            f"Failed (missing Telegram ID): {failed_count}",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.exception("Failed to message achievers: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Message achievers failed: {str(e)}")
        await update.message.reply_text("❌ Failed to message achievers. Please try again.")
    
    return ConversationHandler.END


async def broadcast_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /broadcast command - start interactive broadcast"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END

    # Show broadcast type options
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Text Broadcast", callback_data="broadcast_text")],
        [InlineKeyboardButton("🎤 Audio Broadcast", callback_data="broadcast_audio")],
        [InlineKeyboardButton("🎥 Video Broadcast", callback_data="broadcast_video")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ])

    await update.message.reply_text(
        "📢 **Interactive Broadcast**\n\n"
        "Choose the type of broadcast you want to send:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

    return BROADCAST_TYPE


async def broadcast_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast type selection"""
    query = update.callback_query
    await query.answer()

    broadcast_type = query.data.replace("broadcast_", "")

    if broadcast_type == "cancel":
        await query.edit_message_text("❌ Broadcast cancelled.")
        return ConversationHandler.END

    context.user_data['broadcast_type'] = broadcast_type

    if broadcast_type == "text":
        await query.edit_message_text(
            "📝 **Text Broadcast**\n\n"
            "Please type your broadcast message:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif broadcast_type == "audio":
        await query.edit_message_text(
            "🎤 **Audio Broadcast**\n\n"
            "Please send an audio message or voice note:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif broadcast_type == "video":
        await query.edit_message_text(
            "🎥 **Video Broadcast**\n\n"
            "Please send a video message:",
            parse_mode=ParseMode.MARKDOWN
        )

    return BROADCAST_CONTENT


async def broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast content submission"""
    broadcast_type = context.user_data.get('broadcast_type')

    if not broadcast_type:
        await update.message.reply_text("❌ Missing broadcast type. Please try again.")
        return ConversationHandler.END

    try:
        # Get all verified users
        client = get_supabase()
        result = client.table('verified_users').select('telegram_id').eq('status', 'verified').execute()
        verified_users = result.data

        if not verified_users:
            await update.message.reply_text("❌ No verified users found.")
            return ConversationHandler.END

        # Prepare broadcast content
        sent_count = 0
        failed_count = 0

        for user in verified_users:
            try:
                telegram_id = user.get('telegram_id')
                if not telegram_id:
                    failed_count += 1
                    continue

                if broadcast_type == "text":
                    if not update.message.text:
                        await update.message.reply_text("❌ Please send a text message.")
                        return BROADCAST_CONTENT

                    await context.bot.send_message(
                        telegram_id,
                        f"📢 **Broadcast Message**\n\n{update.message.text}",
                        parse_mode=ParseMode.MARKDOWN
                    )

                elif broadcast_type == "audio":
                    if not update.message.voice:
                        await update.message.reply_text("❌ Please send an audio/voice message.")
                        return BROADCAST_CONTENT

                    await context.bot.send_voice(
                        telegram_id,
                        voice=update.message.voice.file_id,
                        caption="📢 **Audio Broadcast**"
                    )

                elif broadcast_type == "video":
                    if not update.message.video:
                        await update.message.reply_text("❌ Please send a video message.")
                        return BROADCAST_CONTENT

                    await context.bot.send_video(
                        telegram_id,
                        video=update.message.video.file_id,
                        caption="📢 **Video Broadcast**"
                    )

                sent_count += 1

            except Exception as e:
                logger.exception("Failed to send broadcast: %s", e)
                failed_count += 1

        await update.message.reply_text(
            f"✅ **{broadcast_type.title()} Broadcast Complete!**\n\n"
            f"Messages sent: {sent_count}\n"
            f"Failed: {failed_count}",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.exception("Failed to broadcast: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Broadcast failed: {str(e)}")
        await update.message.reply_text("❌ Failed to broadcast. Please try again.")

    return ConversationHandler.END


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
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
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False
)

broadcast_conv = ConversationHandler(
    entry_points=[CommandHandler("broadcast", broadcast_all)],
    states={
        BROADCAST_TYPE: [CallbackQueryHandler(broadcast_type_callback, pattern="^broadcast_")],
        BROADCAST_CONTENT: [
            MessageHandler(filters.TEXT | filters.VOICE | filters.VIDEO, broadcast_content)
        ],
    },
    fallbacks=[get_cancel_fallback_handler()],
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