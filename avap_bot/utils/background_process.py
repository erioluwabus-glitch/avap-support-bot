"""
Background process utility for running heavy operations in separate processes
to prevent memory spikes in the main application process.
"""
import multiprocessing
import logging
import time
import os
import sys
from typing import Callable, Any, Tuple

logger = logging.getLogger(__name__)

def run_func_in_subprocess(func: Callable, args: Tuple = (), timeout: int = 120) -> bool:
    """
    Run *func* in a separate process and return True if completed within timeout.
    The child process frees all memory on exit, preventing memory spikes in main process.
    
    Args:
        func: Function to run in subprocess
        args: Arguments to pass to function
        timeout: Maximum time to wait for completion (seconds)
    
    Returns:
        True if function completed successfully, False if timeout or error
    """
    logger.info(f"Starting background process for {func.__name__} with timeout {timeout}s")
    
    p = multiprocessing.Process(target=_child_wrapper, args=(func, args), daemon=False)
    p.start()
    p.join(timeout)
    
    if p.is_alive():
        logger.warning(f"Child process still alive after {timeout}s timeout; terminating")
        p.terminate()
        p.join(1)
        if p.is_alive():
            logger.error("Child process still alive after terminate; killing")
            p.kill()
            p.join()
        return False
    
    success = p.exitcode == 0
    if success:
        logger.info(f"Background process {func.__name__} completed successfully")
    else:
        logger.error(f"Background process {func.__name__} failed with exit code {p.exitcode}")
    
    return success

def _child_wrapper(func: Callable, args: Tuple) -> None:
    """Wrapper function that runs in the child process"""
    try:
        # Set up logging for child process
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        logger.info(f"Child process starting {func.__name__}")
        func(*args)
        logger.info(f"Child process completed {func.__name__}")
        
    except Exception as e:
        logger.error(f"Child process error in {func.__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def run_heavy_operation_safely(operation_name: str, func: Callable, args: Tuple = (), timeout: int = 120) -> bool:
    """
    Safely run a heavy operation in a subprocess with proper error handling and logging.
    
    Args:
        operation_name: Human-readable name for the operation
        func: Function to run
        args: Arguments to pass to function
        timeout: Maximum time to wait
    
    Returns:
        True if operation completed successfully
    """
    logger.info(f"Starting heavy operation '{operation_name}' in subprocess")
    
    try:
        success = run_func_in_subprocess(func, args, timeout)
        if success:
            logger.info(f"Heavy operation '{operation_name}' completed successfully")
        else:
            logger.error(f"Heavy operation '{operation_name}' failed or timed out")
        return success
        
    except Exception as e:
        logger.error(f"Error running heavy operation '{operation_name}': {e}")
        return False
