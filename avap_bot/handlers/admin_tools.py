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

from avap_bot.services.sheets_service import get_student_submissions, list_achievers, get_all_verified_users, get_student_wins
from avap_bot.services.supabase_service import get_supabase, add_broadcast_record, update_broadcast_stats, get_broadcast_history, delete_broadcast_messages
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
    logger.info(f"Get submission command received from user {update.effective_user.id}")
    
    if not _is_admin(update):
        logger.warning(f"Non-admin user {update.effective_user.id} tried to use get_submission")
        await update.message.reply_text("❌ This command is only for admins.")
        return ConversationHandler.END
    
    # Parse command arguments
    args = context.args
    logger.info(f"Get submission args: {args}")
    
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
    
    logger.info(f"Getting submissions for username: {username}, module: {module}")
    
    try:
        # Get submission from Google Sheets
        submissions = await run_blocking(get_student_submissions, username, module)
        logger.info(f"Retrieved {len(submissions)} submissions for {username} in module {module}")
        
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
            logger.info(f"Processing submission {i}: {submission}")
            message += f"**Submission {i}:**\n"
            message += f"Type: {submission.get('type', 'Unknown')}\n"
            message += f"Status: {submission.get('status', 'Unknown')}\n"
            message += f"Submitted: {submission.get('submitted_at', 'Unknown')}\n"
            if submission.get('grade'):
                message += f"Grade: {submission['grade']}/10\n"
            if submission.get('comment'):
                message += f"Comment: {submission['comment']}\n"
            message += "\n"
        
        logger.info(f"Sending submission details message: {message[:200]}...")
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


async def broadcast_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast_history command"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only for admins.")
        return

    try:
        # Get recent broadcast history
        broadcasts = await run_blocking(get_broadcast_history, 20)

        if not broadcasts:
            await update.message.reply_text("📜 No broadcast history found.")
            return

        # Send each broadcast as a separate message with delete option
        for i, broadcast in enumerate(broadcasts, 1):
            broadcast_id = broadcast.get('id')
            broadcast_type = broadcast.get('broadcast_type', 'Unknown').title()
            sent_at = broadcast.get('sent_at', 'Unknown')
            sent_count = broadcast.get('sent_to_count', 0)
            failed_count = broadcast.get('failed_count', 0)
            admin_username = broadcast.get('admin_username', 'Unknown')

            # Format sent_at to readable format
            try:
                dt = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                sent_at_formatted = dt.strftime("%Y-%m-%d %H:%M UTC")
            except:
                sent_at_formatted = sent_at

            message = f"**{i}. {broadcast_type} Broadcast**\n"
            message += f"📅 Sent: {sent_at_formatted}\n"
            message += f"👤 By: @{admin_username}\n"
            message += f"📊 Recipients: {sent_count} sent, {failed_count} failed\n"

            # Show content preview for text broadcasts
            if broadcast.get('content_type') == 'text' and broadcast.get('content'):
                content_preview = broadcast['content'][:50] + "..." if len(broadcast['content']) > 50 else broadcast['content']
                message += f"💬 Content: \"{content_preview}\"\n"

            # Add delete button for this broadcast
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Delete This Broadcast", callback_data=f"delete_broadcast_{broadcast_id}")],
                [InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="admin_menu")]
            ])

            await update.message.reply_text(
                message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )

    except Exception as e:
        logger.exception("Failed to get broadcast history: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Broadcast history failed: {str(e)}")
        await update.message.reply_text("❌ Failed to get broadcast history. Please try again.")


async def delete_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle delete broadcast callback"""
    query = update.callback_query
    await query.answer()

    if not _is_admin(update):
        await query.edit_message_text("❌ This command is only for admins.")
        return ConversationHandler.END

    # Extract broadcast ID from callback data (format: "delete_broadcast_{id}")
    broadcast_id = query.data.replace("delete_broadcast_", "")

    try:
        # Delete the broadcast messages
        success = await run_blocking(delete_broadcast_messages, broadcast_id, query.bot)

        if success:
            await query.edit_message_text("✅ **Broadcast messages deleted successfully!**")
        else:
            await query.edit_message_text("❌ Failed to delete broadcast messages.")

    except Exception as e:
        logger.exception("Failed to delete broadcast: %s", e)
        await notify_admin_telegram(query.bot, f"❌ Delete broadcast failed: {str(e)}")
        await query.edit_message_text("❌ Failed to delete broadcast. Please try again.")

    return ConversationHandler.END


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
                    # Send only the raw message without prefix
                    await context.bot.send_message(
                        telegram_id,
                        message_text  # Send raw message without "Message from Admin" prefix
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
    logger.info(f"🔊 BROADCAST COMMAND RECEIVED from user {update.effective_user.id}")
    logger.info(f"Admin check: {_is_admin(update)}")
    logger.info(f"ADMIN_USER_ID from env: {ADMIN_USER_ID}")
    
    if not _is_admin(update):
        logger.warning(f"❌ Non-admin user {update.effective_user.id} tried to use broadcast command")
        await update.message.reply_text(
            f"❌ This command is only for admins.\n"
            f"Your ID: {update.effective_user.id}\n"
            f"Admin ID: {ADMIN_USER_ID}\n"
            f"Admin check: {_is_admin(update)}"
        )
        return ConversationHandler.END

    logger.info(f"✅ Admin check passed for user {update.effective_user.id}, showing broadcast options")

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

    logger.info(f"Broadcast options sent to user {update.effective_user.id}, returning BROADCAST_TYPE")
    return BROADCAST_TYPE


async def broadcast_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast type selection"""
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Broadcast type callback received: {query.data} from user {update.effective_user.id}")

    broadcast_type = query.data.replace("broadcast_", "")
    logger.info(f"Parsed broadcast type: {broadcast_type}")

    if broadcast_type == "cancel":
        logger.info("Broadcast cancelled by user")
        await query.edit_message_text("❌ Broadcast cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data['broadcast_type'] = broadcast_type
    logger.info(f"Broadcast type stored in context: {broadcast_type}")

    if broadcast_type == "text":
        logger.info("Showing text broadcast prompt")
        await query.edit_message_text(
            "📝 **Text Broadcast**\n\n"
            "Please type your broadcast message:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif broadcast_type == "audio":
        logger.info("Showing audio broadcast prompt")
        await query.edit_message_text(
            "🎤 **Audio Broadcast**\n\n"
            "Please send an audio message or voice note:",
            parse_mode=ParseMode.MARKDOWN
        )
    elif broadcast_type == "video":
        logger.info("Showing video broadcast prompt")
        await query.edit_message_text(
            "🎥 **Video Broadcast**\n\n"
            "Please send a video message:",
            parse_mode=ParseMode.MARKDOWN
        )

    logger.info(f"Returning BROADCAST_CONTENT state for {broadcast_type} broadcast")
    return BROADCAST_CONTENT


async def broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast content submission"""
    logger.info(f"Broadcast content handler called from user {update.effective_user.id}")
    
    broadcast_type = context.user_data.get('broadcast_type')
    logger.info(f"Broadcast type from context: {broadcast_type}")

    if not broadcast_type:
        logger.warning("No broadcast type found in context")
        await update.message.reply_text("❌ Missing broadcast type. Please try again.")
        return ConversationHandler.END

    try:
        # Get all verified users
        logger.info("Retrieving verified users from database")
        client = get_supabase()
        result = client.table('verified_users').select('telegram_id').eq('status', 'verified').execute()
        verified_users = result.data
        
        logger.info(f"Database query result: {result}")
        logger.info(f"Verified users count: {len(verified_users) if verified_users else 0}")

        if not verified_users:
            logger.warning("No verified users found in database")
            await update.message.reply_text(
                f"❌ No verified users found.\n"
                f"Database query result: {result}\n"
                f"Verified users count: {len(verified_users) if verified_users else 0}"
            )
            return ConversationHandler.END

        # Create broadcast record in history
        admin_id = update.effective_user.id
        admin_username = update.effective_user.username or "Unknown"

        broadcast_record = None
        if broadcast_type == "text":
            content = update.message.text
            content_type = "text"
            file_name = None
        elif broadcast_type == "audio":
            content = update.message.voice.file_id if update.message.voice else None
            content_type = "voice"
            file_name = getattr(update.message.voice, 'file_name', None) if update.message.voice else None
        elif broadcast_type == "video":
            content = update.message.video.file_id if update.message.video else None
            content_type = "video"
            file_name = getattr(update.message.video, 'file_name', None) if update.message.video else None

        broadcast_record = await run_blocking(
            add_broadcast_record,
            broadcast_type,
            content,
            content_type,
            admin_id,
            admin_username,
            file_name
        )

        if not broadcast_record:
            await update.message.reply_text("❌ Failed to create broadcast record.")
            return ConversationHandler.END

        # Prepare broadcast content and track sent messages
        sent_count = 0
        failed_count = 0
        message_ids = []

        for user in verified_users:
            try:
                telegram_id = user.get('telegram_id')
                if not telegram_id:
                    failed_count += 1
                    continue

                sent_message = None

                if broadcast_type == "text":
                    if not update.message.text:
                        await update.message.reply_text("❌ Please send a text message.")
                        return BROADCAST_CONTENT

                    # Remove the "📢 **Broadcast Message**" prefix - send only the raw text
                    sent_message = await context.bot.send_message(
                        telegram_id,
                        update.message.text  # Send raw message without prefix
                    )

                elif broadcast_type == "audio":
                    if not update.message.voice:
                        await update.message.reply_text("❌ Please send an audio/voice message.")
                        return BROADCAST_CONTENT

                    sent_message = await context.bot.send_voice(
                        telegram_id,
                        voice=update.message.voice.file_id
                        # No caption - just the audio
                    )

                elif broadcast_type == "video":
                    if not update.message.video:
                        await update.message.reply_text("❌ Please send a video message.")
                        return BROADCAST_CONTENT

                    sent_message = await context.bot.send_video(
                        telegram_id,
                        video=update.message.video.file_id
                        # No caption - just the video
                    )

                sent_count += 1

                # Track message ID for potential deletion later
                if sent_message:
                    message_ids.append({
                        "user_id": telegram_id,
                        "message_id": sent_message.message_id
                    })

            except Exception as e:
                logger.exception("Failed to send broadcast: %s", e)
                failed_count += 1

        # Update broadcast record with statistics
        await run_blocking(
            update_broadcast_stats,
            broadcast_record.get('id'),
            sent_count,
            failed_count,
            message_ids
        )

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


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command - show bot statistics"""
    logger.info(f"📊 STATS COMMAND RECEIVED from user {update.effective_user.id}")
    logger.info(f"Admin check: {_is_admin(update)}")
    logger.info(f"ADMIN_USER_ID from env: {ADMIN_USER_ID}")
    
    if not _is_admin(update):
        logger.warning(f"❌ Non-admin user {update.effective_user.id} tried to use stats command")
        await update.message.reply_text(
            f"❌ This command is only for admins.\n"
            f"Your ID: {update.effective_user.id}\n"
            f"Admin ID: {ADMIN_USER_ID}\n"
            f"Admin check: {_is_admin(update)}"
        )
        return

    logger.info(f"✅ Admin check passed for user {update.effective_user.id}, retrieving stats")

    try:
        # Get statistics from database
        client = get_supabase()
        
        # Get verified users count
        verified_result = client.table("verified_users").select("id", count="exact").eq("status", "verified").execute()
        verified_count = verified_result.count or 0
        
        # Get pending verifications count
        pending_result = client.table("pending_verifications").select("id", count="exact").execute()
        pending_count = pending_result.count or 0
        
        # Get removed users count
        removed_result = client.table("verified_users").select("id", count="exact").eq("status", "removed").execute()
        removed_count = removed_result.count or 0
        
        # Get total submissions count (from Google Sheets)
        try:
            submissions = await run_blocking(get_student_submissions, "all")  # Get all submissions
            total_submissions = len(submissions) if submissions else 0
        except Exception as e:
            logger.warning(f"Failed to get submissions count: {e}")
            total_submissions = 0
        
        # Get total wins count
        try:
            wins = await run_blocking(get_student_wins, "all")  # Get all wins
            total_wins = len(wins) if wins else 0
        except Exception as e:
            logger.warning(f"Failed to get wins count: {e}")
            total_wins = 0
        
        # Get broadcast history count
        try:
            broadcast_history = await run_blocking(get_broadcast_history, 1000)  # Get last 1000 broadcasts
            total_broadcasts = len(broadcast_history) if broadcast_history else 0
        except Exception as e:
            logger.warning(f"Failed to get broadcast history: {e}")
            total_broadcasts = 0
        
        # Format the stats message
        stats_message = (
            "📊 **AVAP Support Bot Statistics**\n\n"
            f"👥 **Users:**\n"
            f"• Verified Students: {verified_count}\n"
            f"• Pending Verifications: {pending_count}\n"
            f"• Removed Users: {removed_count}\n\n"
            f"📝 **Activity:**\n"
            f"• Total Submissions: {total_submissions}\n"
            f"• Total Wins Shared: {total_wins}\n"
            f"• Total Broadcasts Sent: {total_broadcasts}\n\n"
            f"🤖 **Bot Status:** ✅ Active"
        )
        
        await update.message.reply_text(
            stats_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"Stats sent successfully to admin {update.effective_user.id}")
        
    except Exception as e:
        logger.exception(f"Failed to get stats: {e}")
        await update.message.reply_text(
            "❌ Failed to retrieve statistics. Please try again later."
        )


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Get submission is a simple command, not a conversation

message_achievers_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(broadcast_achievers, pattern="^broadcast_achievers$")],
    states={
        MESSAGE_ACHIEVERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_achievers)],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=True,
    conversation_timeout=600
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
    per_message=False,
    conversation_timeout=600
)


def register_handlers(application):
    """Register all admin tools handlers with the application"""
    logger.info("🔧 Registering admin tools handlers...")
    
    # Add command handlers
    application.add_handler(CommandHandler("get_submission", get_submission))
    application.add_handler(CommandHandler("stats", stats_handler))
    logger.info("✅ Registered stats and get_submission command handlers")
    
    # Add conversation handlers
    application.add_handler(message_achievers_conv)
    application.add_handler(broadcast_conv)
    logger.info("✅ Registered broadcast and message_achievers conversation handlers")

    # Add global callback handlers to fix per_message=False warnings
    application.add_handler(CallbackQueryHandler(broadcast_achievers, pattern="^broadcast_achievers$"))
    # Note: broadcast_type_callback is already handled by broadcast_conv, so we don't need to register it separately

    # Add command handlers
    application.add_handler(CommandHandler("list_achievers", list_achievers_cmd))
    application.add_handler(CommandHandler("broadcast_history", broadcast_history_cmd))
    application.add_handler(CallbackQueryHandler(delete_broadcast_callback, pattern="^delete_broadcast_"))