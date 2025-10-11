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

async def get_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /get_submission command"""
    logger.info(f"📝 GET_SUBMISSION COMMAND RECEIVED from user {update.effective_user.id}")
    logger.info(f"Command text: {update.message.text if update.message else 'No message'}")
    logger.info(f"Admin check: {_is_admin(update)}")
    
    if not _is_admin(update):
        logger.warning(f"❌ Non-admin user {update.effective_user.id} tried to use get_submission")
        await update.message.reply_text("❌ This command is only for admins.")
        return
    
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
        return
    
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
            return
        
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


async def list_students_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all students - admin only"""
    if not _is_admin(update):
        await update.message.reply_text("❌ This command is only available to admins.")
        return
    
    try:
        logger.info(f"Admin {update.effective_user.id} listing all students")
        students = await run_blocking(get_all_verified_users)
        
        if not students:
            await update.message.reply_text(
                "📋 **No students found in the database.**\n\n"
                "This could mean:\n"
                "• No students have been verified yet\n"
                "• All students have been removed\n"
                "• Database connection issue",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Format the student list
        message = f"📋 **All Students ({len(students)} total):**\n\n"
        
        for i, student in enumerate(students[:20], 1):  # Limit to first 20 to avoid message length issues
            name = student.get('name', 'Unknown')
            email = student.get('email', 'No email')
            phone = student.get('phone', 'No phone')
            telegram_id = student.get('telegram_id', 'No Telegram ID')
            status = student.get('status', 'Unknown')
            
            message += f"**{i}. {name}**\n"
            message += f"   • Email: `{email}`\n"
            message += f"   • Phone: `{phone}`\n"
            message += f"   • Telegram ID: `{telegram_id}`\n"
            message += f"   • Status: {status}\n\n"
        
        if len(students) > 20:
            message += f"... and {len(students) - 20} more students\n\n"
        
        message += "💡 **To remove a student, use:**\n"
        message += "`/remove_student <email_or_phone_or_name>`"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"Successfully listed {len(students)} students for admin {update.effective_user.id}")
        
    except Exception as e:
        logger.exception(f"Error in list_students_handler: {e}")
        await update.message.reply_text("❌ An error occurred while listing students.")


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
            submissions = await run_blocking(get_all_submissions)  # Get all submissions
            total_submissions = len(submissions) if submissions else 0
        except Exception as e:
            logger.warning(f"Failed to get submissions count: {e}")
            total_submissions = 0
        
        # Get total wins count
        try:
            wins = await run_blocking(get_all_wins)  # Get all wins
            total_wins = len(wins) if wins else 0
        except Exception as e:
            logger.warning(f"Failed to get wins count: {e}")
            total_wins = 0
        
        
        # Get top students (achievers) for more detailed stats
        try:
            achievers = await run_blocking(list_achievers)
            top_students = achievers[:5] if achievers else []  # Top 5 students
        except Exception as e:
            logger.warning(f"Failed to get achievers: {e}")
            top_students = []
        
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
        )
        
        # Add top students if available
        if top_students:
            stats_message += "🏆 **Top Students:**\n"
            for i, student in enumerate(top_students, 1):
                username = student.get('username', 'Unknown')
                submissions = student.get('submissions', 0)
                wins = student.get('wins', 0)
                stats_message += f"{i}. @{username} - {submissions} submissions, {wins} wins\n"
            stats_message += "\n"
        
        stats_message += "🤖 **Bot Status:** ✅ Active"
        
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



def register_handlers(application):
    """Register all admin tools handlers with the application"""
    logger.info("🔧 Registering admin tools handlers...")
    
    # Add command handlers
    application.add_handler(CommandHandler("get_submission", get_submission))
    application.add_handler(CommandHandler("getsubmission", get_submission))  # Alternative command name
    application.add_handler(CommandHandler("getsubmissions", get_submission))  # Plural alias
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("clear_matches", clear_matches_handler))
    application.add_handler(CommandHandler("test_systeme", test_systeme_handler))
    application.add_handler(CommandHandler("fix_headers", fix_headers_handler))
    application.add_handler(CommandHandler("list_students", list_students_handler))
    logger.info("✅ Registered stats, get_submission, clear_matches, test_systeme, fix_headers, and list_students command handlers")

    # Add command handlers
    application.add_handler(CommandHandler("list_achievers", list_achievers_cmd))