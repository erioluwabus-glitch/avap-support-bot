"""
Helper for running blocking operations in thread pool
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Thread pool executor for blocking operations
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="blocking")


async def run_blocking(func: Callable, *args, **kwargs) -> Any:
    """Run blocking function in thread pool executor"""
    try:
        loop = asyncio.get_event_loop()
        # Create a wrapper function that handles both args and kwargs properly
        def wrapper():
            return func(*args, **kwargs)
        result = await loop.run_in_executor(_executor, wrapper)
        return result
    except Exception as e:
        logger.exception("Blocking operation failed: %s", e)
        raise


def run_async_in_thread(coro: Awaitable) -> Any:
    """Run async coroutine in a separate thread (for sync contexts)"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except Exception as e:
        logger.exception("Async operation in thread failed: %s", e)
        raise


def shutdown_executor():
    """Shutdown thread pool executor"""
    global _executor
    if _executor:
        _executor.shutdown(wait=True)
        logger.info("Thread pool executor shutdown complete")
