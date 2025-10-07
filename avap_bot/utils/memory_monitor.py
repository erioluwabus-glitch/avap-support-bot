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
import os
import sys
import threading
import time

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


def get_comprehensive_memory_diagnostics() -> Dict[str, Any]:
    """Get comprehensive memory diagnostics for troubleshooting"""
    try:
        diagnostics = {
            "timestamp": time.time(),
            "memory_usage": get_detailed_memory_info(),
            "top_memory_consumers": get_memory_top_consumers(20),
            "process_info": {},
            "system_info": {},
            "threading_info": {}
        }

        # Process info
        try:
            proc = psutil.Process()
            diagnostics["process_info"] = {
                "pid": proc.pid,
                "ppid": proc.ppid(),
                "name": proc.name(),
                "cmdline": proc.cmdline(),
                "create_time": proc.create_time(),
                "cpu_times": proc.cpu_times(),
                "num_threads": proc.num_threads(),
                "memory_maps": len(proc.memory_maps()) if hasattr(proc, 'memory_maps') else 0
            }
        except Exception as e:
            logger.debug(f"Failed to get process info: {e}")

        # System info
        try:
            diagnostics["system_info"] = {
                "virtual_memory": dict(psutil.virtual_memory()._asdict()),
                "swap_memory": dict(psutil.swap_memory()._asdict()),
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=1.0)
            }
        except Exception as e:
            logger.debug(f"Failed to get system info: {e}")

        # Threading info
        try:
            import threading
            diagnostics["threading_info"] = {
                "active_threads": threading.active_count(),
                "main_thread": threading.main_thread().name if threading.main_thread() else None,
                "current_thread": threading.current_thread().name
            }
        except Exception as e:
            logger.debug(f"Failed to get threading info: {e}")

        return diagnostics

    except Exception as e:
        logger.error(f"Failed to get comprehensive diagnostics: {e}")
        return {"error": str(e)}


def log_comprehensive_diagnostics(context: str = "diagnostic_check"):
    """Log comprehensive memory diagnostics"""
    try:
        diagnostics = get_comprehensive_memory_diagnostics()

        logger.info(f"=== COMPREHENSIVE MEMORY DIAGNOSTICS ({context}) ===")

        # Memory usage
        mem = diagnostics.get("memory_usage", {})
        logger.info(f"Memory: RSS={mem.get('rss_mb', 0):.1f}MB, VMS={mem.get('vms_mb', 0):.1f}MB, "
                   f"CPU={mem.get('cpu_percent', 0):.1f}%, Threads={mem.get('num_threads', 0)}, "
                   f"FDs={mem.get('open_files', 0)}, Connections={mem.get('connections', 0)}")

        # Top memory consumers
        consumers = diagnostics.get("top_memory_consumers", [])
        if consumers:
            logger.info("Top memory consumers:")
            for i, (obj, size_mb) in enumerate(consumers[:10], 1):
                logger.info(f"  {i}. {obj}: {size_mb:.2f}MB")

        # Process info
        proc_info = diagnostics.get("process_info", {})
        if proc_info:
            logger.info(f"Process: PID={proc_info.get('pid', 'N/A')}, "
                       f"Threads={proc_info.get('num_threads', 'N/A')}, "
                       f"Memory Maps={proc_info.get('memory_maps', 'N/A')}")

        # System info
        sys_info = diagnostics.get("system_info", {})
        if sys_info:
            virt_mem = sys_info.get("virtual_memory", {})
            logger.info(f"System: RAM Total={virt_mem.get('total', 0) / (1024**3):.1f}GB, "
                       f"Available={virt_mem.get('available', 0) / (1024**3):.1f}GB, "
                       f"Used={virt_mem.get('percent', 0):.1f}%")

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Failed to log comprehensive diagnostics: {e}")


async def monitor_memory(context) -> None:
    """
    Monitor memory usage and take corrective action if needed.
    Called periodically by job queue. FAST and non-blocking.
    """
    try:
        rss_mb = get_memory_usage()

        try:
            log_memory_usage("periodic monitoring")
        except (NameError, ImportError):
            logger.info(f"Memory usage: {rss_mb:.1f}MB")

        # Check for CRITICAL memory usage (78% of 512MB = 400MB) - FAST cleanup only
        if rss_mb > 400:
            logger.critical(f"CRITICAL memory usage detected: {rss_mb:.1f}MB - Triggering FAST cleanup!")
            try:
                # Quick cleanup only - don't block other jobs
                for _ in range(3):
                    gc.collect()
                from avap_bot.services.ai_service import clear_model_cache
                clear_model_cache()
                logger.info("FAST critical cleanup completed")
            except Exception as e:
                logger.error(f"Failed to trigger FAST critical cleanup: {e}")

        # Check for high memory usage (25% of 512MB = 128MB) - LIGHT cleanup only
        elif rss_mb > 128:
            logger.warning(f"High memory usage detected: {rss_mb:.1f}MB - Taking LIGHT corrective action")

            # LIGHT cleanup - don't block other jobs
            for _ in range(2):
                gc.collect()

            try:
                from avap_bot.services.ai_service import clear_model_cache
                clear_model_cache()
                logger.info("Cleared AI model cache")
            except Exception as e:
                logger.warning(f"Failed to clear AI model cache: {e}")

        # Check memory after cleanup
        final_rss_mb = get_memory_usage()
        if rss_mb - final_rss_mb > 10:  # Only log if we freed significant memory
            try:
                log_memory_usage("after light cleanup")
            except (NameError, ImportError):
                logger.info(f"Memory after light cleanup: {final_rss_mb:.1f}MB (freed: {rss_mb - final_rss_mb:.1f}MB)")

        # Periodic detailed memory logging for debugging
        if hasattr(monitor_memory, '_log_counter'):
            monitor_memory._log_counter += 1
        else:
            monitor_memory._log_counter = 0

        # Log comprehensive diagnostics every 10 monitoring cycles (every ~30-50 minutes)
        if monitor_memory._log_counter % 10 == 0:
            try:
                log_comprehensive_diagnostics(f"periodic_monitoring_cycle_{monitor_memory._log_counter}")
            except Exception as e:
                logger.warning(f"Failed to log comprehensive diagnostics: {e}")

        # Log detailed memory info every 5 monitoring cycles
        elif monitor_memory._log_counter % 5 == 0:
            try:
                import psutil
                proc = psutil.Process()
                mem = proc.memory_info()
                logger.info(f"DETAILED_MEMORY: RSS={mem.rss / (1024*1024):.1f}MB, VMS={mem.vms / (1024*1024):.1f}MB, "
                          f"Threads={proc.num_threads()}, FDs={proc.num_fds()}")
            except Exception as e:
                logger.warning(f"Failed to get detailed memory info: {e}")

    except Exception as e:
        logger.error(f"Memory monitoring failed: {e}")


async def ultra_aggressive_cleanup() -> None:
    """
    FAST aggressive memory cleanup for critical situations.
    Optimized for speed to prevent job conflicts.
    """
    try:
        logger.warning("Starting FAST aggressive memory cleanup...")
        initial_memory = get_memory_usage()

        # Step 1: Aggressive garbage collection
        for _ in range(10):
            gc.collect()

        # Step 2: Clear AI model cache
        try:
            from avap_bot.services.ai_service import clear_model_cache
            clear_model_cache()
            logger.info("Cleared AI model cache during FAST cleanup")
        except Exception as e:
            logger.warning(f"Failed to clear AI model cache: {e}")

        # Step 3: Aggressive module cleanup (all heavy modules)
        try:
            import sys
            # Clear all potentially heavy modules
            heavy_modules = [
                'sentence_transformers', 'transformers', 'torch', 'torchvision',
                'numpy', 'pandas', 'scipy', 'sklearn', 'matplotlib',
                'PIL', 'cv2', 'openai', 'requests', 'urllib3'
            ]
            cleared_modules = []
            for module_name in heavy_modules:
                if module_name in sys.modules:
                    try:
                        del sys.modules[module_name]
                        cleared_modules.append(module_name)
                    except Exception as e:
                        logger.debug(f"Could not clear module {module_name}: {e}")

            if cleared_modules:
                logger.info(f"Cleared heavy modules: {', '.join(cleared_modules)}")
        except Exception as e:
            logger.warning(f"Failed to clear heavy modules: {e}")

        # Step 4: Force process memory compaction (if available)
        try:
            import os
            # Try to force OS memory cleanup (Linux/Unix only)
            if hasattr(os, 'system'):
                # This may help on some systems
                pass
        except:
            pass

        # Step 5: Final aggressive garbage collection
        for _ in range(10):
            gc.collect()

        # Step 6: Clear internal Python caches
        try:
            # Clear line cache
            import linecache
            linecache.clearcache()

            # Clear importlib caches
            import importlib
            importlib.invalidate_caches()
        except Exception as e:
            logger.debug(f"Failed to clear internal caches: {e}")

        # Log final memory usage and calculate freed memory
        final_memory = get_memory_usage()
        freed_memory = initial_memory - final_memory
        logger.warning(f"FAST cleanup completed. Final memory: {final_memory:.1f}MB (freed: {freed_memory:.1f}MB)")

        # If we didn't free much memory, this indicates a deeper issue
        if freed_memory < 50:  # Less than 50MB freed
            logger.critical(f"WARNING: Cleanup only freed {freed_memory:.1f}MB - memory may be held by external libraries")

    except Exception as e:
        logger.error(f"FAST aggressive cleanup failed: {e}")


async def cleanup_resources() -> None:
    """
    Cleanup system resources to prevent memory leaks.
    Called during bot shutdown or periodically.
    """
    try:
        logger.info("Starting resource cleanup...")
        initial_memory = get_memory_usage()

        # Force garbage collection
        for _ in range(5):
            gc.collect()

        # Clear AI model cache
        try:
            from avap_bot.services.ai_service import clear_model_cache
            clear_model_cache()
            logger.info("Cleared AI model cache during cleanup")
        except Exception as e:
            logger.warning(f"Failed to clear AI model cache: {e}")

        # Clear heavy modules
        try:
            import sys
            heavy_modules = ['sentence_transformers', 'transformers', 'torch', 'numpy', 'openai']
            cleared_modules = []
            for module_name in heavy_modules:
                if module_name in sys.modules:
                    try:
                        del sys.modules[module_name]
                        cleared_modules.append(module_name)
                    except Exception:
                        pass

            if cleared_modules:
                logger.info(f"Cleared modules during cleanup: {', '.join(cleared_modules)}")
        except Exception as e:
            logger.warning(f"Failed to clear modules during cleanup: {e}")

        # Clear internal caches
        try:
            import linecache
            linecache.clearcache()
            import importlib
            importlib.invalidate_caches()
        except Exception as e:
            logger.debug(f"Failed to clear internal caches: {e}")

        # Final garbage collection
        for _ in range(5):
            gc.collect()

        # Log final memory usage and freed memory
        final_memory = get_memory_usage()
        freed_memory = initial_memory - final_memory

        try:
            log_memory_usage("final cleanup")
        except (NameError, ImportError):
            logger.info(f"Resource cleanup completed. Final memory: {final_memory:.1f}MB (freed: {freed_memory:.1f}MB)")

    except Exception as e:
        logger.error(f"Resource cleanup failed: {e}")


def start_memory_watchdog() -> threading.Thread:
    """Start the memory watchdog in a separate thread"""
    watchdog_thread = threading.Thread(
        target=memory_watchdog_loop,
        kwargs={'check_interval': 30},
        daemon=True,
        name="MemoryWatchdog"
    )
    watchdog_thread.start()
    logger.info("Memory watchdog thread started")
    return watchdog_thread


def graceful_restart(reason: str = "memory_threshold_exceeded"):
    """Gracefully restart the process to reclaim all memory"""
    logger.critical(f"Graceful restart triggered: {reason}")

    try:
        # Log current memory state before restart
        try:
            detailed_info = get_detailed_memory_info()
            logger.critical(f"Pre-restart memory: RSS={detailed_info.get('rss_mb', 0):.1f}MB, "
                          f"VMS={detailed_info.get('vms_mb', 0):.1f}MB, "
                          f"Threads={detailed_info.get('num_threads', 0)}")
        except Exception as e:
            logger.warning(f"Failed to get pre-restart memory info: {e}")

        # Give other threads a moment to finish
        import time
        time.sleep(2)

        # Restart the process (Render will respawn it)
        logger.critical("Restarting process to reclaim memory...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        logger.error(f"Graceful restart failed: {e}")
        # Fallback: force exit and let Render restart
        sys.exit(1)


def memory_watchdog_loop(check_interval: int = 30) -> None:
    """Memory watchdog that restarts process when RSS exceeds safe threshold"""
    try:
        proc = psutil.Process()
        # Set RSS limit to 550MB (safer threshold before Render kills us at 512MB)
        rss_limit_bytes = int(os.environ.get("RSS_LIMIT_MB", "550")) * 1024 * 1024

        logger.info(f"Memory watchdog started - RSS limit: {rss_limit_bytes / (1024*1024):.0f}MB")

        while True:
            try:
                rss = proc.memory_info().rss
                if rss > rss_limit_bytes:
                    logger.critical(f"RSS {rss / (1024*1024):.1f}MB > {rss_limit_bytes / (1024*1024):.0f}MB limit. Triggering graceful restart.")
                    graceful_restart("memory_watchdog_threshold_exceeded")
                time.sleep(check_interval)
            except Exception as e:
                logger.error(f"Memory watchdog check failed: {e}")
                time.sleep(check_interval)
    except Exception as e:
        logger.error(f"Memory watchdog loop failed: {e}")


def log_memory_usage(context: str = "") -> None:
    """Log current memory usage with optional context and detailed info"""
    memory_mb = get_memory_usage()
    context_str = f" ({context})" if context else ""

    try:
        detailed_info = get_detailed_memory_info()
        if detailed_info:
            cpu_percent = detailed_info.get('cpu_percent', 0)
            num_threads = detailed_info.get('num_threads', 0)
            logger.info(f"Memory usage{context_str}: {memory_mb:.1f}MB, CPU: {cpu_percent:.1f}%, Threads: {num_threads}")
        else:
            logger.info(f"Memory usage{context_str}: {memory_mb:.1f}MB")
    except Exception as e:
        logger.warning(f"Failed to get detailed memory info: {e}")
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
