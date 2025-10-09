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
        if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            logger.debug(f"Detected group chat: {chat_type}")
            return True
        else:
            logger.debug(f"Chat type is not group: {chat_type}")
            return False
    except (AttributeError, TypeError) as e:
        logger.warning(f"Error checking chat type: {e}")
        return False


def should_disable_inline_keyboards(update: Update, target_chat_id: int = None, allow_admin_operations: bool = False) -> bool:
    """
    Check if inline keyboards should be disabled for this update.
    We disable inline keyboards when:
    1. The message/callback is from a group chat (group or supergroup) - UNLESS it's an admin operation
    2. The message/callback is being sent TO a group chat

    Args:
        update: The Telegram update object (message or callback_query)
        target_chat_id: Optional target chat ID to check if sending TO a group
        allow_admin_operations: If True, allow inline keyboards for admin operations even in group chats

    Returns:
        bool: True if inline keyboards should be disabled, False otherwise
    """
    # CRITICAL FIX: Always disable inline keyboards in group chats
    # This prevents old 4-button keyboards from showing in assignment, verification, and question groups
    # Admin operations should also not show inline keyboards in groups

    # Check if the message/callback originated from a group chat
    if is_group_chat(update):
        # Allow admin operations to show inline keyboards in group chats
        if allow_admin_operations:
            logger.info("Message originated from group chat but admin operations allowed - keeping inline keyboards")
            return False
        else:
            logger.info("Message originated from group chat - disabling inline keyboards")
            return True

    # For callback queries, also check the message's chat type
    if update.callback_query:
        try:
            # Check the chat where the original message with the inline keyboard was sent
            message_chat_type = update.callback_query.message.chat.type
            if message_chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
                # Allow admin operations to show inline keyboards in group chats
                if allow_admin_operations:
                    logger.info(f"Callback query from group chat: {message_chat_type} but admin operations allowed - keeping inline keyboards")
                    return False
                else:
                    logger.info(f"Callback query from group chat: {message_chat_type} - disabling inline keyboards")
                    return True
        except (AttributeError, TypeError) as e:
            logger.warning(f"Error checking callback query chat type: {e}")
            return False

    # Check if we're sending TO a group chat by checking known group IDs
    if target_chat_id:
        # CRITICAL FIX: Always disable inline keyboards when sending TO group chats
        # This prevents old 4-button keyboards from showing in assignment, verification, and question groups
            
        # Check against known group IDs from environment variables
        try:
            import os
            assignment_group_id = int(os.getenv("ASSIGNMENT_GROUP_ID", "0"))
            support_group_id = int(os.getenv("SUPPORT_GROUP_ID", "0"))
            questions_group_id = int(os.getenv("QUESTIONS_GROUP_ID", "0"))

            known_group_ids = [assignment_group_id, support_group_id, questions_group_id]

            if target_chat_id in known_group_ids and target_chat_id != 0:
                logger.info(f"Sending TO known group chat (ID: {target_chat_id}) - disabling inline keyboards")
                return True

            # Also check if it's a negative ID (group chat IDs are negative in Telegram)
            if target_chat_id < 0:
                logger.info(f"Sending TO group chat (negative ID: {target_chat_id}) - disabling inline keyboards")
                return True

        except (ValueError, TypeError) as e:
            logger.warning(f"Error checking target chat ID {target_chat_id}: {e}")
            # If we can't determine, err on the side of caution for negative IDs
            if target_chat_id < 0:
                logger.info(f"Target chat ID is negative ({target_chat_id}), likely a group - disabling keyboards")
                return True

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
