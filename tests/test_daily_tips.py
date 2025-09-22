"""
Unit tests for daily tips feature.
"""
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio
from features.daily_tips import get_daily_tip, send_daily_tip

class TestDailyTips(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_app = MagicMock()
        self.mock_bot = AsyncMock()
        self.mock_app.bot = self.mock_bot
    
    @patch('features.daily_tips.get_random_daily_tip')
    async def test_get_daily_tip_from_db(self, mock_get_tip):
        """Test getting daily tip from database."""
        mock_get_tip.return_value = "Test tip from database"
        
        result = await get_daily_tip()
        
        self.assertEqual(result, "Test tip from database")
    
    @patch('features.daily_tips.get_random_daily_tip')
    async def test_get_daily_tip_fallback(self, mock_get_tip):
        """Test getting daily tip from fallback when database is empty."""
        mock_get_tip.return_value = None
        
        result = await get_daily_tip()
        
        self.assertIn(result, [
            "Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill",
            "The only way to do great work is to love what you do. - Steve Jobs",
            # ... other fallback tips
        ])
    
    @patch('features.daily_tips.get_daily_tip')
    @patch('features.daily_tips.SUPPORT_GROUP_ID', 12345)
    @patch('features.daily_tips.DAILY_TIPS_TO_DMS', False)
    async def test_send_daily_tip_to_group_only(self, mock_get_tip):
        """Test sending daily tip to support group only."""
        mock_get_tip.return_value = "Test tip"
        
        await send_daily_tip(self.mock_app)
        
        self.mock_bot.send_message.assert_called_once_with(
            chat_id=12345,
            text="💡 Daily Tip: Test tip\n\n/verify to access features or /ask to ask a question."
        )
    
    @patch('features.daily_tips.get_daily_tip')
    @patch('features.daily_tips.SUPPORT_GROUP_ID', 12345)
    @patch('features.daily_tips.DAILY_TIPS_TO_DMS', True)
    @patch('features.daily_tips.get_verified_users')
    @patch('features.daily_tips.send_with_backoff')
    async def test_send_daily_tip_to_group_and_dms(self, mock_send_backoff, mock_get_users, mock_get_tip):
        """Test sending daily tip to both group and DMs."""
        mock_get_tip.return_value = "Test tip"
        mock_get_users.return_value = [
            {"telegram_id": 1, "language": "en"},
            {"telegram_id": 2, "language": "es"},
        ]
        mock_send_backoff.return_value = True
        
        await send_daily_tip(self.mock_app)
        
        # Should send to group
        self.mock_bot.send_message.assert_called_with(
            chat_id=12345,
            text="💡 Daily Tip: Test tip\n\n/verify to access features or /ask to ask a question."
        )
        
        # Should send to users
        self.assertEqual(mock_send_backoff.call_count, 2)
    
    @patch('features.daily_tips.get_daily_tip')
    @patch('features.daily_tips.SUPPORT_GROUP_ID', None)
    @patch('features.daily_tips.DAILY_TIPS_TO_DMS', False)
    async def test_send_daily_tip_no_group(self, mock_get_tip):
        """Test sending daily tip when no support group is configured."""
        mock_get_tip.return_value = "Test tip"
        
        await send_daily_tip(self.mock_app)
        
        # Should not send any messages
        self.mock_bot.send_message.assert_not_called()

if __name__ == '__main__':
    unittest.main()
