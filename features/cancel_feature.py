"""
Cancel feature - Universal /cancel command implementation

Provides the /cancel command handler and admin subcommand logic
for cancelling user operations across the bot.
"""
import asyncio
import os
import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler
from telegram.constants import ParseMode

from avap_bot.utils.cancel_registry import CancelRegistry
from avap_bot.services.notifier import notify_admin_telegram

logger = logging.getLogger(__name__)

# Get admin user IDs from environment
ADMIN_USER_IDS = set()
admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
if admin_ids_str:
    try:
        ADMIN_USER_IDS = {int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()}
    except ValueError:
        logger.warning("Invalid ADMIN_USER_IDS format, using single ADMIN_USER_ID")
        admin_id = int(os.getenv("ADMIN_USER_ID", "0"))
        if admin_id:
            ADMIN_USER_IDS.add(admin_id)
else:
    admin_id = int(os.getenv("ADMIN_USER_ID", "0"))
    if admin_id:
        ADMIN_USER_IDS.add(admin_id)

logger.info(f"Admin user IDs: {ADMIN_USER_IDS}")


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_USER_IDS


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /cancel command.
    
    Supports:
    - /cancel - Cancel current user's operations
    - /cancel <user_id> - Admin can cancel another user's operations
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Parse command arguments
    args = context.args
    target_user_id = user_id  # Default to current user
    
    if args:
        # Check if user is admin for cancelling other users
        if not is_admin(user_id):
            await update.message.reply_text(
                "❌ Only admins can cancel other users' operations.\n"
                "Use /cancel to cancel your own operations.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        try:
            target_user_id = int(args[0])
            logger.info(f"Admin {user_id} requesting cancellation for user {target_user_id}")
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid user ID format. Use: `/cancel <user_id>`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
    
    # Get cancel registry from bot data
    cancel_registry: Optional[CancelRegistry] = context.bot_data.get('cancel_registry')
    if not cancel_registry:
        logger.error("CancelRegistry not found in bot_data")
        await update.message.reply_text(
            "❌ Cancel system not available. Please try again later."
        )
        return
    
    try:
        # Check if user has any operations to cancel
        stats = await cancel_registry.get_user_stats(target_user_id)
        
        if stats['active_tasks'] == 0 and stats['total_jobs'] == 0:
            if target_user_id == user_id:
                await update.message.reply_text(
                    "ℹ️ No active operations to cancel.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ User {target_user_id} has no active operations to cancel.",
                    parse_mode=ParseMode.MARKDOWN
                )
            return
        
        # Request cancellation
        await cancel_registry.request_cancel(target_user_id)
        
        # Cancel all operations and get statistics
        cancel_stats = await cancel_registry.cancel_all_for_user(target_user_id)
        
        # Send confirmation message
        if target_user_id == user_id:
            # User cancelling their own operations
            message = (
                "✅ **Cancel Requested**\n\n"
                f"Attempting to stop all ongoing operations...\n"
                f"• Tasks cancelled: {cancel_stats['tasks_cancelled']}\n"
                f"• Jobs stopped: {cancel_stats['jobs_called']}\n"
                f"• Tasks still running: {cancel_stats['tasks_remaining']}\n\n"
                "You will be notified when cancellation completes."
            )
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
            # Set cancel flag in user data for conversation handlers
            context.user_data['cancel_requested'] = True
            
        else:
            # Admin cancelling another user's operations
            message = (
                f"✅ **Cancellation Requested**\n\n"
                f"User: `{target_user_id}`\n"
                f"• Tasks cancelled: {cancel_stats['tasks_cancelled']}\n"
                f"• Jobs stopped: {cancel_stats['jobs_called']}\n"
                f"• Tasks still running: {cancel_stats['tasks_remaining']}\n\n"
                "Admins will be notified of results."
            )
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
            # Try to notify the target user
            try:
                await context.bot.send_message(
                    target_user_id,
                    "🛑 **Operations Cancelled**\n\n"
                    "An admin has cancelled your ongoing operations.\n"
                    "Use /start to see the main menu.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"Could not notify user {target_user_id} of cancellation: {e}")
        
        # Log the cancellation
        logger.info(
            f"Cancellation completed for user {target_user_id} by {user_id}: "
            f"{cancel_stats}"
        )
        
        # Notify admins if there were issues
        if cancel_stats['tasks_remaining'] > 0:
            admin_message = (
                f"⚠️ **Cancellation Warning**\n\n"
                f"User: `{target_user_id}`\n"
                f"Requested by: `{user_id}`\n"
                f"Tasks still running: {cancel_stats['tasks_remaining']}\n"
                f"Tasks cancelled: {cancel_stats['tasks_cancelled']}\n"
                f"Jobs stopped: {cancel_stats['jobs_called']}"
            )
            await notify_admin_telegram(context.bot, admin_message)
        
    except Exception as e:
        logger.exception(f"Error in cancel_handler for user {target_user_id}: {e}")
        
        error_message = (
            "❌ **Cancellation Failed**\n\n"
            "An error occurred while cancelling operations. "
            "Please try again or contact support."
        )
        
        if target_user_id == user_id:
            await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(
                f"❌ Failed to cancel operations for user {target_user_id}.\n"
                "Please check the logs for details.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Notify admins of the error
        admin_error_message = (
            f"🚨 **Cancellation Error**\n\n"
            f"User: `{target_user_id}`\n"
            f"Requested by: `{user_id}`\n"
            f"Error: {str(e)[:500]}"
        )
        await notify_admin_telegram(context.bot, admin_error_message)


async def conversation_cancel_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Fallback cancel handler for conversation flows.
    
    This should be used as a fallback in ConversationHandler instances
    to handle /cancel commands within conversations.
    
    Returns:
        ConversationHandler.END to exit the conversation
    """
    user_id = update.effective_user.id
    
    # Get cancel registry from bot data
    cancel_registry: Optional[CancelRegistry] = context.bot_data.get('cancel_registry')
    if cancel_registry:
        try:
            # Request cancellation for the user
            await cancel_registry.request_cancel(user_id)
            logger.info(f"Conversation cancellation requested for user {user_id}")
        except Exception as e:
            logger.warning(f"Error requesting cancellation in conversation for user {user_id}: {e}")
    
    # Set cancel flag in user data
    context.user_data['cancel_requested'] = True
    
    # Send cancellation message
    await update.message.reply_text(
        "🛑 **Operation Cancelled**\n\n"
        "Use /start to see the main menu.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    return ConversationHandler.END


def register_cancel_handlers(application) -> None:
    """
    Register cancel command handlers with the application.
    
    Args:
        application: Telegram Application instance
    """
    # Register global cancel handler
    application.add_handler(CommandHandler("cancel", cancel_handler))
    logger.info("Registered cancel command handlers")


def get_cancel_fallback_handler() -> CommandHandler:
    """
    Get a cancel fallback handler for use in ConversationHandler instances.
    
    Returns:
        CommandHandler for /cancel in conversations
    """
    return CommandHandler("cancel", conversation_cancel_fallback)


# Test command for manual testing
async def longop_test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Test command for long-running operations.
    
    This command simulates a long-running operation that can be cancelled.
    Use this to test the cancel functionality.
    """
    user_id = update.effective_user.id
    
    # Get cancel registry
    cancel_registry: Optional[CancelRegistry] = context.bot_data.get('cancel_registry')
    if not cancel_registry:
        await update.message.reply_text("❌ Cancel system not available.")
        return
    
    await update.message.reply_text(
        "🔄 Starting long operation test...\n"
        "This will run for 10 seconds. Use /cancel to stop it.",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        from avap_bot.utils.cancel_helpers import CancellableOperation
        
        async with CancellableOperation(cancel_registry, user_id, "longop_test") as op:
            for i in range(10):
                await op.checkpoint()  # Check for cancellation
                await update.message.reply_text(f"⏱️ Step {i+1}/10...")
                await asyncio.sleep(1)
            
            await update.message.reply_text("✅ Long operation completed successfully!")
            
    except asyncio.CancelledError:
        await update.message.reply_text("🛑 Long operation was cancelled!")
    except Exception as e:
        logger.exception(f"Error in longop test for user {user_id}: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


def register_test_handlers(application) -> None:
    """
    Register test handlers (for development/testing only).
    
    Args:
        application: Telegram Application instance
    """
    # Only register in development
    if os.getenv("ENVIRONMENT", "production") == "development":
        application.add_handler(CommandHandler("longop", longop_test_handler))
        logger.info("Registered test handlers")
