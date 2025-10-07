#!/usr/bin/env python3
"""
Subprocess runner for heavy model operations - PERMANENT MEMORY FIX
Ensures memory is freed after heavy AI tasks by running in subprocess
"""
import multiprocessing
import traceback
import logging
import sys
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def model_worker(conn, func_name: str, *args, **kwargs):
    """
    Worker function that runs in subprocess with proper cleanup
    """
    try:
        # Set process name for monitoring
        try:
            import setproctitle
            setproctitle.setproctitle(f"avap-model-{func_name}")
        except ImportError:
            pass  # setproctitle not available

        # Force garbage collection before starting
        import gc
        gc.collect()

        # Import heavy libraries inside worker to avoid loading in parent
        if func_name == "find_faq_match":
            from sentence_transformers import SentenceTransformer
            import numpy as np

            question = args[0]
            faqs = args[1]
            threshold = kwargs.get('threshold', 0.8)

            # Load model
            transformer = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

            # Encode question
            question_embedding = transformer.encode([question])

            # Batch encode FAQs
            faq_questions = [faq['question'] for faq in faqs]
            batch_size = 5
            faq_embeddings = []
            for i in range(0, len(faq_questions), batch_size):
                batch = faq_questions[i:i + batch_size]
                batch_embeddings = transformer.encode(batch)
                faq_embeddings.extend(batch_embeddings)

            faq_embeddings = np.array(faq_embeddings)

            # Calculate similarities
            similarities = np.dot(question_embedding, faq_embeddings.T)[0]

            # Find best match
            best_idx = np.argmax(similarities)
            best_similarity = similarities[best_idx]

            if best_similarity >= threshold:
                result = faqs[best_idx]
            else:
                result = None

        elif func_name == "find_similar_question":
            from sentence_transformers import SentenceTransformer
            import numpy as np

            question = args[0]
            answered_questions = args[1]
            threshold = kwargs.get('threshold', 0.8)

            # Load model
            transformer = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

            # Encode question
            question_embedding = transformer.encode([question])

            # Batch encode answered questions
            answered_texts = [q['question_text'] for q in answered_questions]
            batch_size = 15
            answered_embeddings = []
            for i in range(0, len(answered_texts), batch_size):
                batch = answered_texts[i:i + batch_size]
                batch_embeddings = transformer.encode(batch)
                answered_embeddings.extend(batch_embeddings)

            answered_embeddings = np.array(answered_embeddings)

            # Calculate similarities
            similarities = np.dot(question_embedding, answered_embeddings.T)[0]

            # Find best match
            best_idx = np.argmax(similarities)
            best_similarity = similarities[best_idx]

            if best_similarity >= threshold:
                result = answered_questions[best_idx]
            else:
                result = None

        elif func_name == "generate_ai_tip":
            # Use OpenAI for tip generation in subprocess
            import openai

            openai_key = kwargs.get('openai_key')
            if not openai_key:
                result = "💡 Remember: Consistency is key to success! Keep working on your goals every day."
            else:
                try:
                    client = openai.OpenAI(api_key=openai_key)
                    response = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "You are a motivational coach. Generate a short, inspiring daily tip for students learning programming and personal development. Keep it under 200 characters."},
                            {"role": "user", "content": "Generate a daily tip for today."}
                        ],
                        max_tokens=100,
                        temperature=0.7
                    )
                    result = response.choices[0].message.content.strip()
                except Exception as e:
                    logger.warning(f"OpenAI tip generation failed: {e}")
                    result = "💡 Remember: Consistency is key to success! Keep working on your goals every day."

        else:
            raise ValueError(f"Unknown function: {func_name}")

        conn.send(("ok", result))

    except Exception as e:
        logger.exception(f"Model worker failed: {e}")
        conn.send(("error", traceback.format_exc()))
    finally:
        # Force aggressive cleanup - ensures memory is freed back to OS
        import gc
        import sys

        # Clear all local variables explicitly
        try:
            if 'transformer' in locals():
                del transformer
            if 'question_embedding' in locals():
                del question_embedding
            if 'faq_embeddings' in locals():
                del faq_embeddings
            if 'answered_embeddings' in locals():
                del answered_embeddings
            if 'batch_embeddings' in locals():
                del batch_embeddings
            if 'similarities' in locals():
                del similarities
            if 'result' in locals():
                del result
        except:
            pass

        # Aggressive garbage collection
        for _ in range(10):  # More GC cycles for subprocess
            gc.collect()

        # Clear module cache for heavy libraries
        modules_to_clear = ['sentence_transformers', 'transformers', 'torch', 'numpy']
        for module_name in modules_to_clear:
            if module_name in sys.modules:
                try:
                    del sys.modules[module_name]
                except:
                    pass

        # Final GC after module cleanup
        gc.collect()

        conn.close()


def run_model_in_subprocess(func_name: str, *args, timeout: int = 60, **kwargs) -> Any:
    """
    Run AI model operations in subprocess with GUARANTEED memory cleanup

    This ensures that heavy AI models are loaded in a subprocess and
    ALL memory is freed when the subprocess exits (OS-level cleanup).

    Args:
        func_name: Name of the function to run
        *args: Positional arguments for function
        timeout: Timeout in seconds
        **kwargs: Keyword arguments for function

    Returns:
        Function result

    Raises:
        RuntimeError: If subprocess fails
        TimeoutError: If subprocess times out
    """
    # Create pipe for communication
    parent_conn, child_conn = multiprocessing.Pipe()

    # Create process with explicit cleanup
    process = multiprocessing.Process(
        target=model_worker,
        args=(child_conn, func_name) + args,
        kwargs=kwargs
    )

    try:
        process.start()

        # Wait for result with timeout
        if parent_conn.poll(timeout):
            status, payload = parent_conn.recv()
            if status == "ok":
                return payload
            else:
                raise RuntimeError(f"Model subprocess failed: {payload}")
        else:
            logger.warning(f"Model subprocess timed out after {timeout}s, terminating...")
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                logger.warning("Process still alive after terminate, using kill...")
                process.kill()
                process.join(timeout=1)
            raise TimeoutError(f"Model subprocess timed out after {timeout}s")

    except Exception as e:
        logger.error(f"Error in model subprocess: {e}")
        raise
    finally:
        # Ensure process is completely cleaned up
        try:
            if process.is_alive():
                logger.warning("Force terminating subprocess in cleanup...")
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
        except Exception as cleanup_error:
            logger.error(f"Error during subprocess cleanup: {cleanup_error}")
            try:
                if process.is_alive():
                    process.kill()
            except:
                pass


def run_in_subprocess(func: Callable, *args, timeout: int = 30, **kwargs) -> Any:
    """
    Legacy wrapper - use run_model_in_subprocess for AI operations
    """
    logger.warning("run_in_subprocess is deprecated. Use run_model_in_subprocess for AI operations.")
    return run_model_in_subprocess(func.__name__, *args, timeout=timeout, **kwargs)
