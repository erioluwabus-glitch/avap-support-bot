"""
Chat utility functions for Telegram bot.
"""
import logging
from telegram import Update
from telegram.constants import ChatType

logger = logging.getLogger(__name__)


def is_group_chat(update: Update) -> bool:
    """
    Check if the update is coming from a group chat (group or supergroup).

    Args:
        update: The Telegram update object

    Returns:
        bool: True if the chat is a group or supergroup, False otherwise
    """
    try:
        chat_type = update.effective_chat.type
        return chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]
    except (AttributeError, TypeError) as e:
        logger.warning(f"Error checking chat type: {e}")
        return False


def should_disable_inline_keyboards(update: Update) -> bool:
    """
    Check if inline keyboards should be disabled for this update.
    We disable inline keyboards when:
    1. The message is sent in a group chat (group or supergroup)
    2. The message is being sent TO a group chat

    Args:
        update: The Telegram update object

    Returns:
        bool: True if inline keyboards should be disabled, False otherwise
    """
    # Check if the message originated from a group chat
    if is_group_chat(update):
        return True

    # For messages being sent (not replies), check if any destination is a group
    # This is a simplified check - in practice, we'd need to check the specific
    # destination of each message, but this covers the most common case
    return False


def create_keyboard_for_chat(update: Update, keyboard_markup, text_only_fallback: str = None):
    """
    Create appropriate reply markup based on chat type.
    Returns inline keyboard for private chats, text message for groups.

    Args:
        update: The Telegram update object
        keyboard_markup: The InlineKeyboardMarkup to use for private chats
        text_only_fallback: Optional fallback text to send in groups instead

    Returns:
        tuple: (reply_markup, should_send_keyboard) where reply_markup is either
               the keyboard markup or None, and should_send_keyboard indicates
               whether to send the message with keyboard or as text only
    """
    if should_disable_inline_keyboards(update):
        logger.info("Disabling inline keyboard for group chat")
        return None, False, text_only_fallback
    else:
        return keyboard_markup, True, None
