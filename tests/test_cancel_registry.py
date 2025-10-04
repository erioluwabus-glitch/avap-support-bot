"""
Unit tests for CancelRegistry and cancel helpers.

Tests the core cancellation functionality to ensure reliable
operation cancellation across the bot.
"""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime, timezone

from avap_bot.utils.cancel_registry import CancelRegistry, CancelEntry
from avap_bot.utils.cancel_helpers import (
    cooperative_checkpoint,
    safe_network_call,
    register_user_task,
    CancellableOperation,
    create_cancellable_loop,
    with_cancellation_check
)


class TestCancelEntry:
    """Test CancelEntry dataclass."""
    
    def test_cancel_entry_initialization(self):
        """Test CancelEntry initializes with empty collections."""
        entry = CancelEntry()
        assert entry.tasks == set()
        assert entry.jobs == {}
        assert entry.requested_at is None


class TestCancelRegistry:
    """Test CancelRegistry functionality."""
    
    @pytest.fixture
    async def registry(self):
        """Create a fresh CancelRegistry for each test."""
        return CancelRegistry()
    
    @pytest.fixture
    async def mock_task(self):
        """Create a mock asyncio task."""
        task = Mock(spec=asyncio.Task)
        task.done.return_value = False
        task.cancel.return_value = True
        task.get_name.return_value = "test_task"
        return task
    
    async def test_register_unregister_task(self, registry, mock_task):
        """Test task registration and unregistration."""
        user_id = 12345
        
        # Register task
        await registry.register_task(user_id, mock_task)
        stats = await registry.get_user_stats(user_id)
        assert stats['total_tasks'] == 1
        assert stats['active_tasks'] == 1
        
        # Unregister task
        await registry.unregister_task(user_id, mock_task)
        stats = await registry.get_user_stats(user_id)
        assert stats['total_tasks'] == 0
        assert stats['active_tasks'] == 0
    
    async def test_register_unregister_job(self, registry):
        """Test job registration and unregistration."""
        user_id = 12345
        cancel_fn = Mock()
        
        # Register job
        token = await registry.register_job(user_id, cancel_fn)
        assert isinstance(token, str)
        assert len(token) > 0
        
        stats = await registry.get_user_stats(user_id)
        assert stats['total_jobs'] == 1
        
        # Unregister job
        await registry.unregister_job(user_id, token)
        stats = await registry.get_user_stats(user_id)
        assert stats['total_jobs'] == 0
    
    async def test_request_cancel(self, registry, mock_task):
        """Test cancellation request."""
        user_id = 12345
        cancel_fn = Mock()
        
        # Register task and job
        await registry.register_task(user_id, mock_task)
        token = await registry.register_job(user_id, cancel_fn)
        
        # Request cancellation
        await registry.request_cancel(user_id)
        
        # Check that cancellation was requested
        assert await registry.is_cancel_requested(user_id) is True
        
        # Check that task was cancelled and job was called
        mock_task.cancel.assert_called_once()
        cancel_fn.assert_called_once()
    
    async def test_cancel_all_for_user(self, registry, mock_task):
        """Test cancelling all operations for a user."""
        user_id = 12345
        cancel_fn = Mock()
        
        # Register task and job
        await registry.register_task(user_id, mock_task)
        token = await registry.register_job(user_id, cancel_fn)
        
        # Cancel all operations
        stats = await registry.cancel_all_for_user(user_id)
        
        # Check statistics
        assert stats['tasks_cancelled'] == 1
        assert stats['jobs_called'] == 1
        assert stats['tasks_remaining'] == 0
        
        # Check that operations were cancelled
        mock_task.cancel.assert_called()
        cancel_fn.assert_called()
    
    async def test_clear_user(self, registry, mock_task):
        """Test clearing user data."""
        user_id = 12345
        cancel_fn = Mock()
        
        # Register task and job
        await registry.register_task(user_id, mock_task)
        token = await registry.register_job(user_id, cancel_fn)
        
        # Clear user
        await registry.clear_user(user_id)
        
        # Check that user data is cleared
        stats = await registry.get_user_stats(user_id)
        assert stats['total_tasks'] == 0
        assert stats['total_jobs'] == 0
        assert stats['cancel_requested'] is False
    
    async def test_multiple_users(self, registry):
        """Test that different users have separate cancellation state."""
        user1_id = 12345
        user2_id = 67890
        
        task1 = Mock(spec=asyncio.Task)
        task1.done.return_value = False
        task1.cancel.return_value = True
        task1.get_name.return_value = "task1"
        
        task2 = Mock(spec=asyncio.Task)
        task2.done.return_value = False
        task2.cancel.return_value = True
        task2.get_name.return_value = "task2"
        
        # Register tasks for different users
        await registry.register_task(user1_id, task1)
        await registry.register_task(user2_id, task2)
        
        # Cancel only user1
        await registry.request_cancel(user1_id)
        
        # Check that only user1 is cancelled
        assert await registry.is_cancel_requested(user1_id) is True
        assert await registry.is_cancel_requested(user2_id) is False
        
        # Check that only task1 was cancelled
        task1.cancel.assert_called()
        task2.cancel.assert_not_called()


class TestCancelHelpers:
    """Test cancel helper functions."""
    
    @pytest.fixture
    async def registry(self):
        """Create a fresh CancelRegistry for each test."""
        return CancelRegistry()
    
    async def test_cooperative_checkpoint_no_cancel(self, registry):
        """Test cooperative checkpoint when no cancellation is requested."""
        user_id = 12345
        
        # Should not raise exception
        await cooperative_checkpoint(user_id, registry)
    
    async def test_cooperative_checkpoint_with_cancel(self, registry):
        """Test cooperative checkpoint when cancellation is requested."""
        user_id = 12345
        
        # Request cancellation
        await registry.request_cancel(user_id)
        
        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await cooperative_checkpoint(user_id, registry)
    
    async def test_safe_network_call_success(self, registry):
        """Test safe network call when operation succeeds."""
        user_id = 12345
        
        async def mock_coro():
            return "success"
        
        result = await safe_network_call(mock_coro(), user_id, registry)
        assert result == "success"
    
    async def test_safe_network_call_cancelled(self, registry):
        """Test safe network call when cancellation is requested."""
        user_id = 12345
        
        async def mock_coro():
            # Simulate cancellation after the call
            await registry.request_cancel(user_id)
            return "success"
        
        with pytest.raises(asyncio.CancelledError):
            await safe_network_call(mock_coro(), user_id, registry)
    
    async def test_register_user_task_context_manager(self, registry):
        """Test register_user_task context manager."""
        user_id = 12345
        
        async def test_operation():
            return "completed"
        
        # Test with context manager
        async with register_user_task(registry, user_id) as task:
            result = await test_operation()
            assert result == "completed"
        
        # Check that task was unregistered
        stats = await registry.get_user_stats(user_id)
        assert stats['total_tasks'] == 0
    
    async def test_cancellable_operation_context_manager(self, registry):
        """Test CancellableOperation context manager."""
        user_id = 12345
        cleanup_called = False
        
        def cleanup():
            nonlocal cleanup_called
            cleanup_called = True
        
        async with CancellableOperation(registry, user_id, "test_op") as op:
            op.add_cleanup(cleanup)
            # Operation completes normally
            pass
        
        # Check that cleanup was called
        assert cleanup_called is True
    
    async def test_cancellable_operation_cancelled(self, registry):
        """Test CancellableOperation when cancelled."""
        user_id = 12345
        cleanup_called = False
        
        def cleanup():
            nonlocal cleanup_called
            cleanup_called = True
        
        async with CancellableOperation(registry, user_id, "test_op") as op:
            op.add_cleanup(cleanup)
            # Request cancellation
            await registry.request_cancel(user_id)
            # This should raise CancelledError
            with pytest.raises(asyncio.CancelledError):
                await op.checkpoint()
        
        # Check that cleanup was called even when cancelled
        assert cleanup_called is True
    
    async def test_create_cancellable_loop(self, registry):
        """Test create_cancellable_loop context manager."""
        user_id = 12345
        items_processed = []
        
        async with create_cancellable_loop(registry, user_id, "test_loop") as op:
            for i in range(5):
                await op.checkpoint()  # Check for cancellation
                items_processed.append(i)
        
        assert items_processed == [0, 1, 2, 3, 4]
    
    async def test_with_cancellation_check(self, registry):
        """Test with_cancellation_check function."""
        user_id = 12345
        
        async def long_operation():
            await asyncio.sleep(0.1)
            return "completed"
        
        # Test normal completion
        result = await with_cancellation_check(long_operation(), user_id, registry)
        assert result == "completed"
    
    async def test_with_cancellation_check_cancelled(self, registry):
        """Test with_cancellation_check when cancelled."""
        user_id = 12345
        
        async def long_operation():
            await asyncio.sleep(0.2)
            return "completed"
        
        # Start the operation and cancel it
        async def cancel_after_delay():
            await asyncio.sleep(0.1)
            await registry.request_cancel(user_id)
        
        # Run both concurrently
        with pytest.raises(asyncio.CancelledError):
            await asyncio.gather(
                with_cancellation_check(long_operation(), user_id, registry),
                cancel_after_delay()
            )


class TestIntegration:
    """Integration tests for the cancel system."""
    
    async def test_full_cancellation_flow(self):
        """Test a complete cancellation flow."""
        registry = CancelRegistry()
        user_id = 12345
        
        # Create a long-running task
        async def long_task():
            try:
                for i in range(10):
                    await cooperative_checkpoint(user_id, registry)
                    await asyncio.sleep(0.1)
                return "completed"
            except asyncio.CancelledError:
                return "cancelled"
        
        # Start the task
        task = asyncio.create_task(long_task())
        await registry.register_task(user_id, task)
        
        # Cancel after a short delay
        await asyncio.sleep(0.3)
        await registry.request_cancel(user_id)
        
        # Wait for task to complete
        result = await task
        assert result == "cancelled"
        
        # Check that cancellation was requested
        assert await registry.is_cancel_requested(user_id) is True
    
    async def test_multiple_tasks_cancellation(self):
        """Test cancelling multiple tasks for a user."""
        registry = CancelRegistry()
        user_id = 12345
        
        # Create multiple tasks
        tasks = []
        for i in range(3):
            async def task_func(task_id=i):
                try:
                    for j in range(5):
                        await cooperative_checkpoint(user_id, registry)
                        await asyncio.sleep(0.1)
                    return f"task_{task_id}_completed"
                except asyncio.CancelledError:
                    return f"task_{task_id}_cancelled"
            
            task = asyncio.create_task(task_func())
            await registry.register_task(user_id, task)
            tasks.append(task)
        
        # Cancel after a short delay
        await asyncio.sleep(0.2)
        stats = await registry.cancel_all_for_user(user_id)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check that all tasks were cancelled
        assert stats['tasks_cancelled'] == 3
        assert all("cancelled" in str(result) for result in results)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
