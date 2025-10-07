"""
User concurrency limits to prevent memory spikes with thousands of users
"""
import asyncio
import logging
from typing import Dict, Set
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class UserLimits:
    """
    Manages user concurrency limits to prevent memory issues with thousands of users.
    """
    
    def __init__(self, max_concurrent_users: int = 500, max_ai_requests_per_minute: int = 100):
        """Initialize user limits."""
        self.max_concurrent_users = max_concurrent_users
        self.max_ai_requests_per_minute = max_ai_requests_per_minute
        
        # Track active users
        self.active_users: Set[int] = set()
        self.user_last_activity: Dict[int, datetime] = {}
        
        # Track AI requests
        self.ai_requests: Dict[int, datetime] = {}  # user_id -> last_ai_request_time
        
        # Cleanup task
        self._cleanup_task = None
        self._start_cleanup_task()
        
        logger.info(f"UserLimits initialized: max_concurrent={max_concurrent_users}, max_ai_per_minute={max_ai_requests_per_minute}")

    def _start_cleanup_task(self):
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """Background cleanup loop to remove inactive users."""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                await self._cleanup_inactive_users()
            except Exception as e:
                logger.error(f"User limits cleanup failed: {e}")

    async def _cleanup_inactive_users(self):
        """Remove users who haven't been active for 10 minutes."""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            inactive_users = [
                user_id for user_id, last_activity in self.user_last_activity.items()
                if last_activity < cutoff_time
            ]
            
            for user_id in inactive_users:
                self.active_users.discard(user_id)
                self.user_last_activity.pop(user_id, None)
                self.ai_requests.pop(user_id, None)
            
            if inactive_users:
                logger.info(f"Cleaned up {len(inactive_users)} inactive users")
                
        except Exception as e:
            logger.error(f"Failed to cleanup inactive users: {e}")

    async def can_handle_user(self, user_id: int) -> bool:
        """Check if we can handle a new user request."""
        try:
            # Clean up old AI request records
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=1)
            old_requests = [
                uid for uid, req_time in self.ai_requests.items()
                if req_time < cutoff_time
            ]
            for uid in old_requests:
                self.ai_requests.pop(uid, None)
            
            # Check concurrent user limit
            if len(self.active_users) >= self.max_concurrent_users:
                logger.warning(f"Max concurrent users reached: {len(self.active_users)}")
                return False
            
            # Update user activity
            self.active_users.add(user_id)
            self.user_last_activity[user_id] = datetime.now(timezone.utc)
            return True
            
        except Exception as e:
            logger.error(f"Failed to check user limits: {e}")
            return True  # Allow on error to prevent blocking

    async def can_handle_ai_request(self, user_id: int) -> bool:
        """Check if user can make an AI request (rate limiting)."""
        try:
            now = datetime.now(timezone.utc)
            user_last_request = self.ai_requests.get(user_id)
            
            # Check if user made a request in the last minute
            if user_last_request and (now - user_last_request).seconds < 60:
                logger.warning(f"User {user_id} rate limited for AI requests")
                return False
            
            # Check global AI request rate
            recent_requests = sum(
                1 for req_time in self.ai_requests.values()
                if (now - req_time).seconds < 60
            )
            
            if recent_requests >= self.max_ai_requests_per_minute:
                logger.warning(f"Global AI request rate limit reached: {recent_requests}")
                return False
            
            # Update user's last AI request time
            self.ai_requests[user_id] = now
            return True
            
        except Exception as e:
            logger.error(f"Failed to check AI request limits: {e}")
            return True  # Allow on error to prevent blocking

    def get_stats(self) -> Dict[str, int]:
        """Get current usage statistics."""
        return {
            "active_users": len(self.active_users),
            "max_concurrent_users": self.max_concurrent_users,
            "ai_requests_last_minute": len([
                req_time for req_time in self.ai_requests.values()
                if (datetime.now(timezone.utc) - req_time).seconds < 60
            ]),
            "max_ai_requests_per_minute": self.max_ai_requests_per_minute
        }

# Global instance
user_limits = UserLimits()
