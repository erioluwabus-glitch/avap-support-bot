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

from avap_bot.services.sheets_service import get_student_submissions, list_achievers, get_all_verified_users, get_student_wins, get_all_submissions, get_all_wins, fix_questions_worksheet_headers
from avap_bot.services.supabase_service import get_supabase, clear_all_match_requests
from avap_bot.services.systeme_service import test_systeme_connection
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.chat_utils import should_disable_inline_keyboards
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Conversation states
GET_SUBMISSION = 0

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



async def list_achievers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list_achievers command"""
    logger.info(f"📊 LIST_ACHIEVERS COMMAND RECEIVED from user {update.effective_user.id}")
    
    if not _is_admin(update):
        logger.warning(f"❌ Non-admin user {update.effective_user.id} tried to use list_achievers")
        await update.message.reply_text("❌ This command is only for admins.")
        return

    try:
        logger.info(f"Getting achievers from Google Sheets...")
        # Get achievers from Google Sheets
        achievers = await run_blocking(list_achievers)
        logger.info(f"Retrieved {len(achievers) if achievers else 0} achievers")

        if not achievers:
            # Try to get all students as fallback
            logger.info("No achievers found, trying to get all students...")
            try:
                all_students = await run_blocking(get_all_verified_users)
                if all_students:
                    await update.message.reply_text(
                        f"📊 **No achievers found** (2+ assignments OR 2+ wins)\n\n"
                        f"**Total verified students:** {len(all_students)}\n\n"
                        f"*Try using `/stats` to see detailed statistics.*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("📊 No students found in the system.")
            except Exception as e:
                logger.error(f"Failed to get all students: {e}")
                await update.message.reply_text("📊 No achievers found.\n\n*Note: Achievers are students with 2+ assignments OR 2+ wins.*", parse_mode=ParseMode.MARKDOWN)
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

        # No keyboard needed for achievers list
            keyboard = None

        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard if keyboard else None
        )

    except Exception as e:
        logger.exception("Failed to list achievers: %s", e)
        await notify_admin_telegram(context.bot, f"❌ List achievers failed: {str(e)}")
        await update.message.reply_text("❌ Failed to list achievers. Please try again.")
















async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


async def clear_matches_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all match requests - admin only"""
    # Check if user is admin
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only available to admins.")
        return

    try:
        logger.info(f"Admin {update.effective_user.id} clearing all match requests")
        
        # Clear all match requests
        success = await run_blocking(clear_all_match_requests)
        
        if success:
            await update.message.reply_text(
                "✅ **All match requests have been cleared!**\n\n"
                "All students can now match again with fresh pairings.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Successfully cleared all match requests by admin {update.effective_user.id}")
        else:
            await update.message.reply_text(
                "❌ **Failed to clear match requests.**\n\n"
                "Please check the logs for more details.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.error(f"Failed to clear match requests by admin {update.effective_user.id}")
            
    except Exception as e:
        logger.exception(f"Error in clear_matches_handler: {e}")
        await update.message.reply_text("❌ An error occurred while clearing match requests.")


async def test_systeme_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Test Systeme.io connection - admin only"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only available to admins.")
        return
    
    try:
        logger.info(f"Admin {update.effective_user.id} testing Systeme.io connection")
        result = await run_blocking(test_systeme_connection)
        
        if result["status"] == "success":
            await update.message.reply_text(
                f"✅ **Systeme.io Connection Test**\n\n"
                f"**Status:** {result['message']}\n"
                f"**Contacts Count:** {result.get('contacts_count', 'N/A')}\n\n"
                f"Systeme.io integration is working correctly!",
                parse_mode=ParseMode.MARKDOWN
            )
        elif result["status"] == "error":
            await update.message.reply_text(
                f"❌ **Systeme.io Connection Test Failed**\n\n"
                f"**Error:** {result['message']}\n"
                f"**Suggestion:** {result['suggestion']}\n\n"
                f"Please check your SYSTEME_API_KEY in Render environment variables.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"⚠️ **Systeme.io Connection Test Warning**\n\n"
                f"**Status:** {result['message']}\n"
                f"**Suggestion:** {result['suggestion']}",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.exception(f"Error in test_systeme_handler: {e}")
        await update.message.reply_text("❌ An error occurred while testing Systeme.io connection.")


async def fix_headers_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fix duplicate headers in Questions worksheet - admin only"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only available to admins.")
        return
    
    try:
        logger.info(f"Admin {update.effective_user.id} fixing Questions worksheet headers")
        success = await run_blocking(fix_questions_worksheet_headers)
        
        if success:
            await update.message.reply_text(
                "✅ **Questions Worksheet Headers Fixed!**\n\n"
                "The Questions worksheet has been recreated with proper headers.\n"
                "All existing data has been preserved.\n\n"
                "Question status updates should now work correctly.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Successfully fixed Questions worksheet headers by admin {update.effective_user.id}")
        else:
            await update.message.reply_text(
                "❌ **Failed to fix Questions worksheet headers.**\n\n"
                "Please check the logs for more details.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.error(f"Failed to fix Questions worksheet headers by admin {update.effective_user.id}")
            
    except Exception as e:
        logger.exception(f"Error in fix_headers_handler: {e}")
        await update.message.reply_text("❌ An error occurred while fixing worksheet headers.")






def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


# Get submission is a simple command, not a conversation



def register_handlers(application):
    """Register all admin tools handlers with the application"""
    logger.info("🔧 Registering admin tools handlers...")
    
    # Add command handlers
    application.add_handler(CommandHandler("clear_matches", clear_matches_handler))
    application.add_handler(CommandHandler("test_systeme", test_systeme_handler))
    application.add_handler(CommandHandler("fix_headers", fix_headers_handler))
    logger.info("✅ Registered clear_matches, test_systeme, and fix_headers command handlers")

    # Add command handlers
    application.add_handler(CommandHandler("list_achievers", list_achievers_cmd))