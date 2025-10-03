"""
Student matching handlers for peer connections, using a robust Supabase backend.
"""
import os
import logging

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode

from avap_bot.services.supabase_service import (
    check_verified_user,
    add_match_request,
    pop_match_request,
    find_verified_by_telegram
)
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.run_blocking import run_blocking

logger = logging.getLogger(__name__)

async def match_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /match command for student pairing."""
    user = update.effective_user
    logger.info(f"User @{user.username} ({user.id}) initiated /match.")

    # 1. Check if user is verified
    verified_user = check_verified_user(user.id)
    if not verified_user:
        await update.message.reply_text(
            "❌ You must be a verified student to use the matching feature.\n"
            "Please complete verification by sending /start.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        # 2. Add the current user to the matching queue
        add_match_request(user.id, user.username or "unknown")
        logger.info(f"User {user.id} added to match queue.")

        # 3. Try to find another student in the queue
        matched_user_record = pop_match_request(exclude_id=user.id)

        if matched_user_record:
            matched_user_id = matched_user_record['telegram_id']
            logger.info(f"Found a match for user {user.id} with user {matched_user_id}.")

            # 4. If a match is found, notify both users
            current_user_details = verified_user
            matched_user_details = find_verified_by_telegram(matched_user_id)

            current_username = user.username or current_user_details.get('name')
            
            matched_user_chat = await context.bot.get_chat(matched_user_id)
            matched_username = matched_user_chat.username or (matched_user_details and matched_user_details.get('name'))

            # Notify current user
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"🎉 **Match Found!**\n\n"
                    f"You've been matched with: @{matched_username}\n\n"
                    f"You can now start chatting and collaborating!"
                ),
                parse_mode=ParseMode.MARKDOWN
            )

            # Notify the other user
            await context.bot.send_message(
                chat_id=matched_user_id,
                text=(
                    f"🎉 **Match Found!**\n\n"
                    f"You've been matched with: @{current_username}\n\n"
                    f"You can now start chatting and collaborating!"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Successfully notified both users of the match: {user.id} and {matched_user_id}")

        else:
            # 5. If no match is found, inform the user they are in the queue
            logger.info(f"No immediate match found for user {user.id}. They are now in the queue.")
            await update.message.reply_text(
                "🔍 **You've been added to the matching queue!**\n\n"
                "I'll notify you as soon as another student is available to be matched.",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.exception("Error during /match process for user %s: %s", user.id, e)
        await notify_admin_telegram(context.bot, f"Error in /match command for user {user.id}: {e}")
        await update.message.reply_text("❌ An error occurred while trying to find a match. The admin has been notified.")


def register_handlers(application):
    """Register all matching handlers with the application"""
    application.add_handler(CommandHandler("match", match_student))