"""
General-purpose handlers for the bot, including start, status, and join requests.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..config import logger, ADMIN_ID
from ..database import get_verified_user_by_telegram_id, get_student_stats
from ..models import MAIN_MENU_MARKUP, ASK_QUESTION

# --- Utility ---

async def is_admin(user_id: int) -> bool:
    """Checks if a user is the bot admin."""
    return ADMIN_ID and int(user_id) == int(ADMIN_ID)

# --- Handlers ---

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command.
    - If the user is in a private chat and verified, it shows the main menu.
    - If the user is not verified, it prompts them to verify.
    - In groups, it does nothing.
    """
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    if not user:
        return

    try:
        verified_user = await get_verified_user_by_telegram_id(user.id)
        if verified_user:
            # User is verified, show the main menu
            await update.effective_message.reply_text(
                "You are already verified! Here are the available commands.",
                reply_markup=MAIN_MENU_MARKUP
            )
        else:
            # User is not verified, show the verify button
            verify_btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify Now", callback_data="verify_now")]])
            await update.effective_message.reply_text(
                "Welcome to the AVAP Support Bot! To access features, you need to be a verified student.\n\n"
                "Please click the button below to start the verification process.",
                reply_markup=verify_btn
            )
    except Exception:
        logger.exception("Error in start_handler")
        await update.effective_message.reply_text("An error occurred. Please try again later.")


async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the 'Check Status' command.
    Displays the user's completed modules, scores, and total number of wins.
    """
    # This command should only work in private chats
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please check your status in a private message with me.")
        return

    user = update.effective_user
    try:
        verified_user = await get_verified_user_by_telegram_id(user.id)
        if not verified_user:
            await update.effective_message.reply_text(
                "You must be verified to check your status.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify Now", callback_data="verify_now")]])
            )
            return

        submissions, wins_count = await get_student_stats(user.id)

        if not submissions:
            status_message = "You have not submitted any assignments yet."
        else:
            completed_lines = []
            for sub in submissions:
                score_info = f"Score: {sub['score']}" if sub['score'] else "Not Graded"
                comment_info = f", Comment: {sub['comment']}" if sub['comment'] else ""
                completed_lines.append(f"• Module {sub['module']}: {sub['status']} ({score_info}{comment_info})")
            status_message = "Your Submissions:\n" + "\n".join(completed_lines)

        status_message += f"\n\nTotal Small Wins Shared: {wins_count}"

        await update.effective_message.reply_text(status_message, reply_markup=MAIN_MENU_MARKUP)

    except Exception:
        logger.exception(f"Error checking status for user {user.id}")
        await update.effective_message.reply_text("An error occurred while fetching your status.")


async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles new requests to join a chat.
    Approves the request if the user is verified, otherwise declines it.
    """
    if not update.chat_join_request:
        return

    user_id = update.chat_join_request.from_user.id
    chat_id = update.chat_join_request.chat.id

    try:
        is_verified = await get_verified_user_by_telegram_id(user_id)
        if is_verified:
            logger.info(f"Approving join request for verified user {user_id} to chat {chat_id}.")
            await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(chat_id=user_id, text="Your request to join the group has been approved!")
        else:
            logger.info(f"Declining join request for non-verified user {user_id} to chat {chat_id}.")
            await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text="Your request to join the group was declined because you are not a verified student. "
                     "Please complete the verification process by messaging me and trying again."
            )
    except Exception:
        logger.exception(f"Failed to handle chat join request for user {user_id}")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the active conversation."""
    await update.message.reply_text(
        "Action cancelled.", reply_markup=MAIN_MENU_MARKUP
    )
    return ConversationHandler.END
