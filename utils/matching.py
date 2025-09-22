"""
Matching utilities for study group pairing.
Handles logic for pairing students and forming study groups.
"""
import logging
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta
import random

logger = logging.getLogger(__name__)

def pair_students(students: List[Dict[str, Any]], match_size: int = 2) -> List[List[Dict[str, Any]]]:
    """
    Pair or group students for study matching.
    
    Args:
        students: List of student dictionaries with telegram_id, username, created_at
        match_size: Size of each group (2 for pairs, 3 for groups)
    
    Returns:
        List of groups, where each group is a list of student dictionaries
    """
    if len(students) < match_size:
        return []
    
    # Shuffle students for random pairing
    shuffled_students = students.copy()
    random.shuffle(shuffled_students)
    
    groups = []
    for i in range(0, len(shuffled_students), match_size):
        group = shuffled_students[i:i + match_size]
        if len(group) == match_size:
            groups.append(group)
    
    return groups

def create_match_message(group: List[Dict[str, Any]]) -> str:
    """
    Create a message for matched students.
    
    Args:
        group: List of student dictionaries in the group
    
    Returns:
        Formatted message for the group
    """
    if len(group) == 2:
        # Pair
        student1, student2 = group
        message = f"🎓 Study Match Found!\n\n"
        message += f"📚 You've been paired with @{student2['username']} for study collaboration!\n\n"
        message += f"👥 Your study partner:\n"
        message += f"• @{student2['username']}\n\n"
        message += f"💡 Start a conversation and plan your study sessions together!"
    else:
        # Group
        message = f"🎓 Study Group Formed!\n\n"
        message += f"📚 You've been matched with {len(group)-1} other students for group study!\n\n"
        message += f"👥 Your study group members:\n"
        for student in group[1:]:  # Skip the first student (current user)
            message += f"• @{student['username']}\n"
        message += f"\n💡 Start a group conversation and plan your study sessions together!"
    
    return message

def should_match_students(students: List[Dict[str, Any]], min_wait_minutes: int = 5) -> bool:
    """
    Check if students should be matched based on wait time.
    
    Args:
        students: List of student dictionaries
        min_wait_minutes: Minimum wait time before matching
    
    Returns:
        True if students should be matched
    """
    if len(students) < 2:
        return False
    
    # Check if any student has been waiting long enough
    cutoff_time = datetime.now() - timedelta(minutes=min_wait_minutes)
    
    for student in students:
        created_at = datetime.fromisoformat(student['created_at'])
        if created_at <= cutoff_time:
            return True
    
    return False

def get_match_stats(students: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get statistics about the match queue.
    
    Args:
        students: List of student dictionaries in queue
    
    Returns:
        Dictionary with match statistics
    """
    if not students:
        return {"total": 0, "waiting_time": 0, "oldest_wait": 0}
    
    now = datetime.now()
    waiting_times = []
    
    for student in students:
        created_at = datetime.fromisoformat(student['created_at'])
        wait_time = (now - created_at).total_seconds() / 60  # minutes
        waiting_times.append(wait_time)
    
    return {
        "total": len(students),
        "waiting_time": sum(waiting_times) / len(waiting_times) if waiting_times else 0,
        "oldest_wait": max(waiting_times) if waiting_times else 0,
        "newest_wait": min(waiting_times) if waiting_times else 0
    }
