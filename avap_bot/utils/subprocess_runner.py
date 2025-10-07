"""
Subprocess runner for heavy model operations
Ensures memory is freed after heavy AI tasks
"""
import multiprocessing
import traceback
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def model_worker(conn, func: Callable, *args, **kwargs):
    """Worker function that runs in subprocess"""
    try:
        # Import heavy libraries inside worker to avoid global load
        result = func(*args, **kwargs)
        conn.send(("ok", result))
    except Exception as e:
        logger.exception(f"Model worker failed: {e}")
        conn.send(("error", traceback.format_exc()))
    finally:
        conn.close()


def run_in_subprocess(func: Callable, *args, timeout: int = 30, **kwargs) -> Any:
    """
    Run a function in a subprocess to ensure memory cleanup

    Args:
        func: Function to run
        *args: Positional arguments for function
        timeout: Timeout in seconds
        **kwargs: Keyword arguments for function

    Returns:
        Function result or raises exception
    """
    parent_conn, child_conn = multiprocessing.Pipe()

    process = multiprocessing.Process(
        target=model_worker,
        args=(child_conn, func) + args,
        kwargs=kwargs
    )

    process.start()

    try:
        if parent_conn.poll(timeout):
            status, payload = parent_conn.recv()
            if status == "ok":
                return payload
            else:
                raise RuntimeError(f"Model subprocess failed: {payload}")
        else:
            process.terminate()
            raise TimeoutError(f"Model subprocess timed out after {timeout}s")
    finally:
        process.join(timeout=1)


def run_ai_model_in_subprocess(model_func: Callable, *args, **kwargs) -> Any:
    """
    Run AI model operations in subprocess with memory cleanup

    This ensures that heavy AI models (like SentenceTransformer)
    are loaded in a subprocess and memory is freed when it exits.
    """
    return run_in_subprocess(model_func, *args, timeout=60, **kwargs)
