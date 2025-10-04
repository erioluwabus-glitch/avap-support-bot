"""
CancelRegistry - Core cancellation management for AVAP Support Bot

Provides thread-safe, asyncio-friendly task and job cancellation tracking.
Allows cooperative cancellation of long-running operations and immediate
task cancellation for responsive user experience.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Set, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class CancelEntry:
    """Entry tracking cancellation state for a user."""
    tasks: Set[asyncio.Task] = field(default_factory=set)
    jobs: Dict[str, Callable[[], None]] = field(default_factory=dict)
    requested_at: Optional[datetime] = None


class CancelRegistry:
    """
    Thread-safe registry for managing user task and job cancellations.
    
    Provides cooperative cancellation for long-running operations and
    immediate asyncio task cancellation for responsive user experience.
    """
    
    def __init__(self):
        """Initialize the cancel registry."""
        self._entries: Dict[int, CancelEntry] = {}
        self._lock = asyncio.Lock()
        logger.info("CancelRegistry initialized")

    async def _get_entry(self, user_id: int) -> CancelEntry:
        """Get or create cancel entry for user (thread-safe)."""
        async with self._lock:
            if user_id not in self._entries:
                self._entries[user_id] = CancelEntry()
            return self._entries[user_id]

    async def register_task(self, user_id: int, task: asyncio.Task) -> None:
        """
        Register an asyncio task for cancellation tracking.
        
        Args:
            user_id: Telegram user ID
            task: asyncio.Task to track
        """
        entry = await self._get_entry(user_id)
        entry.tasks.add(task)
        logger.debug(f"Registered task for user {user_id}: {task.get_name()}")

    async def unregister_task(self, user_id: int, task: asyncio.Task) -> None:
        """
        Unregister an asyncio task from cancellation tracking.
        
        Args:
            user_id: Telegram user ID
            task: asyncio.Task to remove
        """
        entry = await self._get_entry(user_id)
        entry.tasks.discard(task)
        logger.debug(f"Unregistered task for user {user_id}: {task.get_name()}")

    async def register_job(self, user_id: int, cancel_callable: Callable[[], None]) -> str:
        """
        Register a job with a cancellation callback.
        
        Args:
            user_id: Telegram user ID
            cancel_callable: Function to call when cancelling this job
            
        Returns:
            job_token: Unique identifier for this job registration
        """
        entry = await self._get_entry(user_id)
        token = str(uuid.uuid4())
        entry.jobs[token] = cancel_callable
        logger.debug(f"Registered job for user {user_id}: {token}")
        return token

    async def unregister_job(self, user_id: int, job_token: str) -> None:
        """
        Unregister a job from cancellation tracking.
        
        Args:
            user_id: Telegram user ID
            job_token: Token returned from register_job
        """
        entry = await self._get_entry(user_id)
        if job_token in entry.jobs:
            del entry.jobs[job_token]
            logger.debug(f"Unregistered job for user {user_id}: {job_token}")

    async def request_cancel(self, user_id: int) -> None:
        """
        Request cancellation for a user's operations.
        
        This marks cancellation as requested and attempts to cancel
        registered tasks and jobs immediately.
        
        Args:
            user_id: Telegram user ID to cancel operations for
        """
        entry = await self._get_entry(user_id)
        entry.requested_at = datetime.now(timezone.utc)
        
        logger.info(f"Cancel requested for user {user_id}")
        
        # Cancel all registered tasks
        tasks_to_cancel = list(entry.tasks)
        for task in tasks_to_cancel:
            try:
                if not task.done():
                    task.cancel()
                    logger.debug(f"Cancelled task for user {user_id}: {task.get_name()}")
            except Exception as e:
                logger.warning(f"Failed to cancel task for user {user_id}: {e}")

        # Call all registered job cancellers
        for token, cancel_fn in list(entry.jobs.items()):
            try:
                cancel_fn()
                logger.debug(f"Called job canceller for user {user_id}: {token}")
            except Exception as e:
                logger.warning(f"Failed to call job canceller for user {user_id}: {e}")

    async def cancel_all_for_user(self, user_id: int, wait_timeout: float = 1.0) -> Dict[str, int]:
        """
        Cancel all operations for a user and wait for completion.
        
        Args:
            user_id: Telegram user ID to cancel operations for
            wait_timeout: Maximum time to wait for task cancellation
            
        Returns:
            Dictionary with cancellation statistics
        """
        stats = {"tasks_cancelled": 0, "jobs_called": 0, "tasks_remaining": 0}
        
        entry = await self._get_entry(user_id)
        
        # Cancel all tasks
        tasks_to_cancel = list(entry.tasks)
        for task in tasks_to_cancel:
            try:
                if not task.done():
                    task.cancel()
                    stats["tasks_cancelled"] += 1
            except Exception as e:
                logger.warning(f"Failed to cancel task for user {user_id}: {e}")

        # Wait for tasks to complete with timeout
        if tasks_to_cancel:
            try:
                done, pending = await asyncio.wait(
                    tasks_to_cancel, 
                    timeout=wait_timeout,
                    return_when=asyncio.ALL_COMPLETED
                )
                stats["tasks_remaining"] = len(pending)
                
                # Cancel any remaining tasks
                for task in pending:
                    try:
                        task.cancel()
                    except Exception as e:
                        logger.warning(f"Failed to cancel remaining task for user {user_id}: {e}")
                        
            except Exception as e:
                logger.warning(f"Error waiting for task cancellation for user {user_id}: {e}")

        # Call all job cancellers
        for token, cancel_fn in list(entry.jobs.items()):
            try:
                cancel_fn()
                stats["jobs_called"] += 1
                logger.debug(f"Called job canceller for user {user_id}: {token}")
            except Exception as e:
                logger.warning(f"Failed to call job canceller for user {user_id}: {e}")

        logger.info(f"Cancellation completed for user {user_id}: {stats}")
        return stats

    async def is_cancel_requested(self, user_id: int) -> bool:
        """
        Check if cancellation has been requested for a user.
        
        Args:
            user_id: Telegram user ID to check
            
        Returns:
            True if cancellation was requested, False otherwise
        """
        entry = await self._get_entry(user_id)
        return entry.requested_at is not None

    async def clear_user(self, user_id: int) -> None:
        """
        Clear all cancellation tracking for a user.
        
        Args:
            user_id: Telegram user ID to clear
        """
        async with self._lock:
            if user_id in self._entries:
                entry = self._entries[user_id]
                # Cancel any remaining tasks
                for task in entry.tasks:
                    try:
                        if not task.done():
                            task.cancel()
                    except Exception:
                        pass
                del self._entries[user_id]
                logger.info(f"Cleared cancellation tracking for user {user_id}")

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Get statistics about a user's tracked operations.
        
        Args:
            user_id: Telegram user ID to get stats for
            
        Returns:
            Dictionary with user operation statistics
        """
        entry = await self._get_entry(user_id)
        active_tasks = sum(1 for task in entry.tasks if not task.done())
        
        return {
            "total_tasks": len(entry.tasks),
            "active_tasks": active_tasks,
            "total_jobs": len(entry.jobs),
            "cancel_requested": entry.requested_at is not None,
            "requested_at": entry.requested_at.isoformat() if entry.requested_at else None
        }
