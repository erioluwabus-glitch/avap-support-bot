"""
Unit tests for matching utilities.
"""
import unittest
from datetime import datetime, timedelta
from utils.matching import pair_students, create_match_message, should_match_students, get_match_stats

class TestMatching(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        self.sample_students = [
            {"telegram_id": 1, "username": "user1", "created_at": "2023-01-01T10:00:00"},
            {"telegram_id": 2, "username": "user2", "created_at": "2023-01-01T10:05:00"},
            {"telegram_id": 3, "username": "user3", "created_at": "2023-01-01T10:10:00"},
            {"telegram_id": 4, "username": "user4", "created_at": "2023-01-01T10:15:00"},
        ]
    
    def test_pair_students_default_size(self):
        """Test pairing students with default size (2)."""
        groups = pair_students(self.sample_students)
        
        self.assertEqual(len(groups), 2)  # 4 students = 2 pairs
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(len(groups[1]), 2)
    
    def test_pair_students_custom_size(self):
        """Test grouping students with custom size (3)."""
        groups = pair_students(self.sample_students, match_size=3)
        
        self.assertEqual(len(groups), 1)  # 4 students = 1 group of 3, 1 leftover
        self.assertEqual(len(groups[0]), 3)
    
    def test_pair_students_insufficient(self):
        """Test pairing with insufficient students."""
        groups = pair_students(self.sample_students[:1], match_size=2)
        self.assertEqual(len(groups), 0)
    
    def test_pair_students_empty(self):
        """Test pairing with empty list."""
        groups = pair_students([])
        self.assertEqual(len(groups), 0)
    
    def test_create_match_message_pair(self):
        """Test creating match message for a pair."""
        group = self.sample_students[:2]
        message = create_match_message(group)
        
        self.assertIn("Study Match Found!", message)
        self.assertIn("user2", message)
        self.assertIn("study partner", message)
    
    def test_create_match_message_group(self):
        """Test creating match message for a group."""
        group = self.sample_students[:3]
        message = create_match_message(group)
        
        self.assertIn("Study Group Formed!", message)
        self.assertIn("2 other students", message)
        self.assertIn("user2", message)
        self.assertIn("user3", message)
    
    def test_should_match_students_true(self):
        """Test should_match_students returns True when students have waited long enough."""
        # Create students with old timestamps
        old_time = datetime.now() - timedelta(minutes=10)
        students = [
            {"telegram_id": 1, "username": "user1", "created_at": old_time.isoformat()},
            {"telegram_id": 2, "username": "user2", "created_at": old_time.isoformat()},
        ]
        
        result = should_match_students(students, min_wait_minutes=5)
        self.assertTrue(result)
    
    def test_should_match_students_false(self):
        """Test should_match_students returns False when students haven't waited long enough."""
        # Create students with recent timestamps
        recent_time = datetime.now() - timedelta(minutes=2)
        students = [
            {"telegram_id": 1, "username": "user1", "created_at": recent_time.isoformat()},
            {"telegram_id": 2, "username": "user2", "created_at": recent_time.isoformat()},
        ]
        
        result = should_match_students(students, min_wait_minutes=5)
        self.assertFalse(result)
    
    def test_should_match_students_insufficient(self):
        """Test should_match_students returns False with insufficient students."""
        students = [{"telegram_id": 1, "username": "user1", "created_at": "2023-01-01T10:00:00"}]
        result = should_match_students(students)
        self.assertFalse(result)
    
    def test_get_match_stats(self):
        """Test getting match statistics."""
        stats = get_match_stats(self.sample_students)
        
        self.assertEqual(stats["total"], 4)
        self.assertGreater(stats["waiting_time"], 0)
        self.assertGreater(stats["oldest_wait"], 0)
        self.assertGreaterEqual(stats["oldest_wait"], stats["newest_wait"])
    
    def test_get_match_stats_empty(self):
        """Test getting match statistics for empty list."""
        stats = get_match_stats([])
        
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["waiting_time"], 0)
        self.assertEqual(stats["oldest_wait"], 0)

if __name__ == '__main__':
    unittest.main()
