"""
Memory monitoring utilities for AVAP Support Bot
Prevents Render free tier memory issues (512MB limit)
"""
import psutil
import gc
import logging
import tracemalloc
from typing import Dict, Any, List, Tuple
import asyncio

logger = logging.getLogger(__name__)

# Initialize tracemalloc for memory profiling
try:
    tracemalloc.start()
    TRACEMALLOC_AVAILABLE = True
except Exception as e:
    logger.warning(f"tracemalloc not available: {e}")
    TRACEMALLOC_AVAILABLE = False


def get_memory_usage() -> float:
    """Get current memory usage in MB"""
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024)  # Convert to MB
    except Exception as e:
        logger.warning(f"Failed to get memory usage: {e}")
        return 0.0


def get_detailed_memory_info() -> Dict[str, Any]:
    """Get detailed memory information"""
    try:
        process = psutil.Process()
        mem_info = process.memory_info()

        info = {
            "rss_mb": mem_info.rss / (1024 * 1024),  # Resident Set Size
            "vms_mb": mem_info.vms / (1024 * 1024),  # Virtual Memory Size
            "cpu_percent": process.cpu_percent(),
            "num_threads": process.num_threads(),
            "open_files": len(process.open_files()),
            "connections": len(process.connections())
        }

        return info
    except Exception as e:
        logger.warning(f"Failed to get detailed memory info: {e}")
        return {}


def get_memory_top_consumers(limit: int = 10) -> List[Tuple[str, float]]:
    """Get top memory consuming objects (if tracemalloc available)"""
    if not TRACEMALLOC_AVAILABLE:
        return []

    try:
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')
        return [(str(stat), stat.size / (1024 * 1024)) for stat in top_stats[:limit]]
    except Exception as e:
        logger.warning(f"Failed to get memory consumers: {e}")
        return []


async def monitor_memory(context) -> None:
    """
    Monitor memory usage and take corrective action if needed.
    Called periodically by job queue.
    """
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        rss_mb = mem_info.rss / (1024 * 1024)
        vms_mb = mem_info.vms / (1024 * 1024)

        try:
            log_memory_usage("periodic monitoring")
        except (NameError, ImportError):
            logger.info(f"Memory usage: RSS={rss_mb:.1f}MB, VMS={vms_mb:.1f}MB")

        # Check for high memory usage (80% of 512MB = 410MB)
        if rss_mb > 410:
            logger.warning(f"High memory usage detected: {rss_mb:.1f}MB - Taking corrective action")

            # Force garbage collection
            gc.collect()

            # Log memory consumers if available
            if TRACEMALLOC_AVAILABLE:
                top_consumers = get_memory_top_consumers(5)
                for consumer, size_mb in top_consumers:
                    logger.debug(f"Memory consumer: {consumer} - {size_mb:.1f}MB")

            # Force clear AI model cache if available
            try:
                from avap_bot.services.ai_service import clear_model_cache
                clear_model_cache()
                logger.info("Cleared AI model cache")
            except Exception as e:
                logger.warning(f"Failed to clear AI model cache: {e}")

            # Check memory after cleanup
            new_rss_mb = get_memory_usage()
            try:
                log_memory_usage("after memory cleanup")
            except (NameError, ImportError):
                logger.info(f"Memory after cleanup: {new_rss_mb:.1f}MB (freed: {rss_mb - new_rss_mb:.1f}MB)")

        # Check for potential memory leaks (gradual increase)
        # This could be enhanced with historical tracking

    except Exception as e:
        logger.error(f"Memory monitoring failed: {e}")


async def cleanup_resources() -> None:
    """
    Cleanup system resources to prevent memory leaks.
    Called during bot shutdown or periodically.
    """
    try:
        logger.info("Starting resource cleanup...")

        # Force garbage collection
        gc.collect()

        # Clear AI model cache
        try:
            from avap_bot.services.ai_service import clear_model_cache
            clear_model_cache()
            logger.info("Cleared AI model cache during cleanup")
        except Exception as e:
            logger.warning(f"Failed to clear AI model cache: {e}")

        # Log final memory usage
        final_memory = get_memory_usage()
        # Use local import to avoid scope issues
        try:
            log_memory_usage("final cleanup")
        except (NameError, ImportError):
            logger.info(f"Resource cleanup completed. Final memory: {final_memory:.1f}MB")

    except Exception as e:
        logger.error(f"Resource cleanup failed: {e}")


def log_memory_usage(context: str = "") -> None:
    """Log current memory usage with optional context"""
    memory_mb = get_memory_usage()
    context_str = f" ({context})" if context else ""
    logger.info(f"Memory usage{context_str}: {memory_mb:.1f}MB")


# Enhanced memory monitoring for development
def enable_detailed_memory_monitoring() -> None:
    """Enable detailed memory monitoring (for development)"""
    if TRACEMALLOC_AVAILABLE:
        logger.info("Detailed memory monitoring enabled")
    else:
        logger.warning("Detailed memory monitoring not available (tracemalloc failed)")


# Cleanup on import (for development)
import atexit
def _safe_cleanup():
    """Safe cleanup that doesn't rely on async context"""
    try:
        # Only run cleanup if we're not in an async context
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return
        # Run cleanup synchronously
        loop.run_until_complete(cleanup_resources())
    except RuntimeError:
        # No event loop or other issues - just skip cleanup
        pass
    except Exception as e:
        logger.warning(f"Cleanup during exit failed: {e}")

atexit.register(_safe_cleanup)
