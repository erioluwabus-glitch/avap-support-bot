"""
Cancel helpers - Decorators and context managers for cooperative cancellation

Provides utilities for integrating long-running operations with the
CancelRegistry system for responsive cancellation.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from functools import wraps
from typing import Callable, Any, Optional, Coroutine

from .cancel_registry import CancelRegistry

logger = logging.getLogger(__name__)


async def cooperative_checkpoint(user_id: int, cancel_registry: CancelRegistry) -> None:
    """
    Checkpoint for cooperative cancellation in long-running operations.
    
    Call this at regular intervals in loops or before expensive operations
    to allow cancellation to be detected quickly.
    
    Args:
        user_id: Telegram user ID to check cancellation for
        cancel_registry: CancelRegistry instance
        
    Raises:
        asyncio.CancelledError: If cancellation was requested
    """
    if await cancel_registry.is_cancel_requested(user_id):
        logger.debug(f"Cancellation detected at checkpoint for user {user_id}")
        raise asyncio.CancelledError("Operation cancelled by user")


async def safe_network_call(
    coro: Coroutine[Any, Any, Any], 
    user_id: int, 
    cancel_registry: CancelRegistry
) -> Any:
    """
    Safely execute a network call with cancellation checking.
    
    Executes the coroutine and checks for cancellation after completion.
    If cancellation was requested, raises CancelledError.
    
    Args:
        coro: Coroutine to execute
        user_id: Telegram user ID to check cancellation for
        cancel_registry: CancelRegistry instance
        
    Returns:
        Result of the coroutine
        
    Raises:
        asyncio.CancelledError: If cancellation was requested
    """
    try:
        result = await coro
        # Check for cancellation after the call
        if await cancel_registry.is_cancel_requested(user_id):
            logger.debug(f"Cancellation detected after network call for user {user_id}")
            raise asyncio.CancelledError("Operation cancelled by user")
        return result
    except asyncio.CancelledError:
        logger.debug(f"Network call cancelled for user {user_id}")
        raise


@asynccontextmanager
async def register_user_task(
    cancel_registry: CancelRegistry, 
    user_id: int, 
    task: Optional[asyncio.Task] = None
):
    """
    Context manager for registering a task with cancellation tracking.
    
    Automatically registers the task on entry and unregisters on exit.
    
    Args:
        cancel_registry: CancelRegistry instance
        user_id: Telegram user ID
        task: Task to register (if None, uses current task)
        
    Example:
        async with register_user_task(cancel_registry, user_id):
            # Long-running operation here
            await some_long_operation()
    """
    if task is None:
        task = asyncio.current_task()
    
    if task is None:
        raise RuntimeError("No current task to register")
    
    try:
        await cancel_registry.register_task(user_id, task)
        logger.debug(f"Registered task in context manager for user {user_id}")
        yield task
    finally:
        await cancel_registry.unregister_task(user_id, task)
        logger.debug(f"Unregistered task from context manager for user {user_id}")


def register_user_task_decorator(cancel_registry: CancelRegistry):
    """
    Decorator factory for registering functions as cancellable tasks.
    
    Args:
        cancel_registry: CancelRegistry instance
        
    Returns:
        Decorator function
        
    Example:
        @register_user_task_decorator(cancel_registry)
        async def long_operation(update, context):
            # Function body
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract user_id from common patterns
            user_id = None
            if args and hasattr(args[0], 'effective_user'):
                user_id = args[0].effective_user.id
            elif 'update' in kwargs and hasattr(kwargs['update'], 'effective_user'):
                user_id = kwargs['update'].effective_user.id
            elif 'context' in kwargs and hasattr(kwargs['context'], 'user_data'):
                user_id = kwargs['context'].user_data.get('user_id')
            
            if user_id is None:
                logger.warning("Could not extract user_id for task registration")
                return await func(*args, **kwargs)
            
            task = asyncio.current_task()
            if task is None:
                logger.warning("No current task to register")
                return await func(*args, **kwargs)
            
            async with register_user_task(cancel_registry, user_id, task):
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


class CancellableOperation:
    """
    Context manager for managing cancellable operations with cleanup.
    
    Provides a structured way to handle operations that need cleanup
    on cancellation.
    """
    
    def __init__(self, cancel_registry: CancelRegistry, user_id: int, operation_name: str = "operation"):
        self.cancel_registry = cancel_registry
        self.user_id = user_id
        self.operation_name = operation_name
        self.task: Optional[asyncio.Task] = None
        self.cleanup_callbacks: list[Callable[[], None]] = []
    
    async def __aenter__(self):
        self.task = asyncio.current_task()
        if self.task is None:
            raise RuntimeError("No current task to register")
        
        await self.cancel_registry.register_task(self.user_id, self.task)
        logger.debug(f"Started cancellable operation '{self.operation_name}' for user {self.user_id}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.task:
            await self.cancel_registry.unregister_task(self.user_id, self.task)
        
        # Run cleanup callbacks
        for cleanup in self.cleanup_callbacks:
            try:
                cleanup()
            except Exception as e:
                logger.warning(f"Cleanup callback failed for operation '{self.operation_name}': {e}")
        
        if exc_type == asyncio.CancelledError:
            logger.info(f"Operation '{self.operation_name}' was cancelled for user {self.user_id}")
            return True  # Suppress the CancelledError
        
        return False
    
    def add_cleanup(self, callback: Callable[[], None]) -> None:
        """Add a cleanup callback to be called on exit."""
        self.cleanup_callbacks.append(callback)
    
    async def checkpoint(self) -> None:
        """Check for cancellation at this point."""
        await cooperative_checkpoint(self.user_id, self.cancel_registry)


def create_cancellable_loop(
    cancel_registry: CancelRegistry,
    user_id: int,
    operation_name: str = "loop"
) -> CancellableOperation:
    """
    Create a cancellable operation context manager for loops.
    
    Args:
        cancel_registry: CancelRegistry instance
        user_id: Telegram user ID
        operation_name: Name for logging purposes
        
    Returns:
        CancellableOperation context manager
        
    Example:
        async with create_cancellable_loop(cancel_registry, user_id, "broadcast") as op:
            for item in items:
                await op.checkpoint()  # Check for cancellation
                await process_item(item)
    """
    return CancellableOperation(cancel_registry, user_id, operation_name)


async def with_cancellation_check(
    coro: Coroutine[Any, Any, Any],
    user_id: int,
    cancel_registry: CancelRegistry,
    check_interval: float = 0.1
) -> Any:
    """
    Execute a coroutine with periodic cancellation checking.
    
    This is useful for operations that don't naturally have checkpoints
    but need to be cancellable.
    
    Args:
        coro: Coroutine to execute
        user_id: Telegram user ID
        cancel_registry: CancelRegistry instance
        check_interval: How often to check for cancellation (seconds)
        
    Returns:
        Result of the coroutine
        
    Raises:
        asyncio.CancelledError: If cancellation was requested
    """
    async def check_and_wait():
        while True:
            if await cancel_registry.is_cancel_requested(user_id):
                raise asyncio.CancelledError("Operation cancelled by user")
            await asyncio.sleep(check_interval)
    
    # Run the coroutine and cancellation checker concurrently
    try:
        result = await asyncio.gather(
            coro,
            check_and_wait(),
            return_exceptions=True
        )
        
        # If the main coroutine completed, return its result
        if not isinstance(result[0], Exception):
            return result[0]
        else:
            raise result[0]
            
    except asyncio.CancelledError:
        logger.debug(f"Operation cancelled for user {user_id}")
        raise
