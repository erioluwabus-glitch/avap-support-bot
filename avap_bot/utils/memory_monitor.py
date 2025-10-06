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

        # Check for CRITICAL memory usage (78% of 512MB = 400MB) - NUCLEAR OPTION
        if rss_mb > 400:
            logger.critical(f"CRITICAL memory usage detected: {rss_mb:.1f}MB - Triggering NUCLEAR cleanup!")
            try:
                from avap_bot.utils.memory_monitor import ultra_aggressive_cleanup
                await ultra_aggressive_cleanup()
            except Exception as e:
                logger.error(f"Failed to trigger ULTRA aggressive cleanup: {e}")
        
        # Check for high memory usage (25% of 512MB = 128MB for ULTRA aggressive cleanup)
        elif rss_mb > 128:
            logger.warning(f"High memory usage detected: {rss_mb:.1f}MB - Taking ULTRA aggressive corrective action")

            # Force ULTRA aggressive garbage collection
            for _ in range(10):
                gc.collect()
            
            # Force clear AI model cache if available
            try:
                from avap_bot.services.ai_service import clear_model_cache
                clear_model_cache()
                logger.info("Cleared AI model cache")
            except Exception as e:
                logger.warning(f"Failed to clear AI model cache: {e}")
            
            # Force ULTRA aggressive garbage collection again after cache clear
            for _ in range(10):
                gc.collect()
            
            # Additional memory cleanup - clear all possible caches
            try:
                import sys
                # Clear Python's internal caches
                sys.modules.clear()
                # Force another round of garbage collection
                for _ in range(5):
                    gc.collect()
            except Exception as e:
                logger.warning(f"Failed additional memory cleanup: {e}")

            # Log memory consumers if available
            if TRACEMALLOC_AVAILABLE:
                top_consumers = get_memory_top_consumers(5)
                for consumer, size_mb in top_consumers:
                    logger.debug(f"Memory consumer: {consumer} - {size_mb:.1f}MB")

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


async def ultra_aggressive_cleanup() -> None:
    """
    ULTRA aggressive memory cleanup for critical situations.
    This is the nuclear option for memory management.
    """
    try:
        logger.warning("Starting ULTRA aggressive memory cleanup...")
        
        # Step 1: Force multiple rounds of garbage collection
        for _ in range(20):
            gc.collect()
        
        # Step 2: Clear AI model cache
        try:
            from avap_bot.services.ai_service import clear_model_cache
            clear_model_cache()
            logger.info("Cleared AI model cache during ULTRA cleanup")
        except Exception as e:
            logger.warning(f"Failed to clear AI model cache: {e}")
        
        # Step 3: Clear Python's internal caches
        try:
            import sys
            # Clear module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                              if name.startswith('avap_bot') or name.startswith('telegram')]
            for module_name in modules_to_clear:
                if module_name in sys.modules:
                    del sys.modules[module_name]
        except Exception as e:
            logger.warning(f"Failed to clear module cache: {e}")
        
        # Step 4: Force more garbage collection
        for _ in range(15):
            gc.collect()
        
        # Step 5: Clear any remaining caches
        try:
            # Clear any remaining AI caches
            from avap_bot.services.ai_service import clear_model_cache
            clear_model_cache()
        except:
            pass
        
        # Final garbage collection
        for _ in range(10):
            gc.collect()
        
        # Log final memory usage
        final_memory = get_memory_usage()
        logger.warning(f"ULTRA cleanup completed. Final memory: {final_memory:.1f}MB")
        
    except Exception as e:
        logger.error(f"ULTRA aggressive cleanup failed: {e}")


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
