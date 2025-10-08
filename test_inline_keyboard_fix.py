#!/usr/bin/env python3
"""
Test script to verify that inline keyboards are properly disabled in group chats.
This script simulates the chat type checking logic to ensure the fix works correctly.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, Message, Chat, User
from telegram.constants import ChatType
from avap_bot.utils.chat_utils import should_disable_inline_keyboards

def create_mock_update(chat_type, is_callback=False):
    """Create a mock update object for testing"""
    class MockChat:
        def __init__(self, chat_type):
            self.type = chat_type

    class MockMessage:
        def __init__(self, chat_type):
            self.chat = MockChat(chat_type)

    class MockCallbackQuery:
        def __init__(self, chat_type):
            self.message = MockMessage(chat_type)

    class MockEffectiveChat:
        def __init__(self, chat_type):
            self.type = chat_type

    class MockUpdate:
        def __init__(self, chat_type, is_callback=False):
            self.effective_chat = MockEffectiveChat(chat_type)
            if is_callback:
                self.callback_query = MockCallbackQuery(chat_type)
            else:
                self.callback_query = None

    return MockUpdate(chat_type, is_callback)

def test_chat_type_detection():
    """Test the chat type detection logic"""
    print("🧪 Testing inline keyboard chat type detection...")

    # Test private chat (should not disable keyboards)
    private_update = create_mock_update(ChatType.PRIVATE)
    result = should_disable_inline_keyboards(private_update)
    print(f"Private chat: should_disable={result} (expected: False)")
    assert result == False, "Private chat should not disable keyboards"

    # Test group chat (should disable keyboards)
    group_update = create_mock_update(ChatType.GROUP)
    result = should_disable_inline_keyboards(group_update)
    print(f"Group chat: should_disable={result} (expected: True)")
    assert result == True, "Group chat should disable keyboards"

    # Test supergroup chat (should disable keyboards)
    supergroup_update = create_mock_update(ChatType.SUPERGROUP)
    result = should_disable_inline_keyboards(supergroup_update)
    print(f"Supergroup chat: should_disable={result} (expected: True)")
    assert result == True, "Supergroup chat should disable keyboards"

    # Test callback query from group chat (should disable keyboards)
    group_callback_update = create_mock_update(ChatType.GROUP, is_callback=True)
    result = should_disable_inline_keyboards(group_callback_update)
    print(f"Group callback query: should_disable={result} (expected: True)")
    assert result == True, "Callback query from group chat should disable keyboards"

    # Test callback query from private chat (should not disable keyboards)
    private_callback_update = create_mock_update(ChatType.PRIVATE, is_callback=True)
    result = should_disable_inline_keyboards(private_callback_update)
    print(f"Private callback query: should_disable={result} (expected: False)")
    assert result == False, "Callback query from private chat should not disable keyboards"

    print("✅ All chat type detection tests passed!")

if __name__ == "__main__":
    try:
        test_chat_type_detection()
        print("\n🎉 Inline keyboard fix verification completed successfully!")
        print("Inline keyboards should now be properly disabled in group chats.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
