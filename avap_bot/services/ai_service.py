"""
Simplified AI service - KEEPS ONLY: FAQ matching, similar question detection, and AI-generated daily tips
REMOVES: Heavy AI operations that cause memory issues
"""
import os
import logging
import asyncio
import gc
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from contextlib import contextmanager

import requests

# Import sentence transformer
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    logger.warning("sentence-transformers not available. AI features will be limited.")
    SentenceTransformer = None

from avap_bot.services.supabase_service import get_faqs, get_tip_for_day, add_manual_tip
from avap_bot.utils.memory_monitor import log_memory_usage
from avap_bot.utils.user_limits import user_limits

logger = logging.getLogger(__name__)

# Model cache with aggressive cleanup
_model = None
_model_last_used = None
MODEL_CACHE_DURATION = 5  # 5 seconds for extremely aggressive memory management

@contextmanager
def managed_model():
    """Context manager for model loading with automatic cleanup"""
    global _model, _model_last_used

    # Clean up old model if cache expired
    if (_model_last_used and
        (datetime.now(timezone.utc) - _model_last_used).seconds > MODEL_CACHE_DURATION):
        logger.info("Cleaning up expired model cache")
        if _model:
            del _model
            _model = None
        gc.collect()

    # Load model if not cached
    if _model is None:
        # Import here to ensure it's available
        from avap_bot.utils.memory_monitor import log_memory_usage
        log_memory_usage("before model loading")
        logger.info("Loading sentence transformer model...")
        
        if SentenceTransformer is None:
            logger.error("SentenceTransformer not available - AI features disabled")
            raise ImportError("sentence-transformers library not installed")
            
        _model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        _model_last_used = datetime.now(timezone.utc)
        log_memory_usage("after model loading")

    try:
        yield _model
    finally:
        # Update last used time
        _model_last_used = datetime.now(timezone.utc)


def clear_model_cache():
    """Clear the model cache to free memory"""
    global _model, _model_last_used
    
    if _model:
        del _model
        _model = None
    _model_last_used = None

    # Force aggressive garbage collection
    for _ in range(5):
        gc.collect()

    log_memory_usage("after model cache clear")


async def find_faq_match(question: str, threshold: float = 0.8, user_id: int = None) -> Optional[Dict[str, Any]]:
    """Find best FAQ match using semantic similarity with subprocess memory isolation"""
    try:
        # Check user limits if user_id provided
        if user_id and not await user_limits.can_handle_ai_request(user_id):
            logger.warning(f"User {user_id} rate limited for AI requests")
            return None

        # Get all FAQs
        faqs = get_faqs()
        
        if not faqs:
            logger.warning("No FAQs available for matching")
            return None

        # Limit FAQs to prevent memory issues
        max_faqs = 50  # Reduced from 100
        if len(faqs) > max_faqs:
            logger.info(f"Limiting FAQ search to {max_faqs} most recent FAQs")
            faqs = faqs[:max_faqs]

        # Use subprocess for heavy model operations to ensure memory cleanup
        from avap_bot.utils.subprocess_runner import run_model_in_subprocess

        log_memory_usage("start FAQ matching subprocess")

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_model_in_subprocess,
            "find_faq_match",
            question,
            faqs,
            threshold
        )

        log_memory_usage("end FAQ matching subprocess")

        return result

    except Exception as e:
        logger.exception(f"FAQ matching failed: {e}")
        return None


async def find_similar_answered_question(question: str, threshold: float = 0.8) -> Optional[Dict[str, Any]]:
    """Find similar previously answered questions using semantic similarity with subprocess memory isolation"""
    try:
        from avap_bot.services.supabase_service import get_answered_questions

        # Get answered questions
        answered_questions = get_answered_questions()
        
        if not answered_questions:
            logger.warning("No answered questions available for matching")
            return None

        # Limit questions to prevent memory issues
        max_questions = 30  # Reduced from 50
        if len(answered_questions) > max_questions:
            logger.info(f"Limiting similar question search to {max_questions} most recent questions")
            answered_questions = answered_questions[:max_questions]

        # Use subprocess for heavy model operations to ensure memory cleanup
        from avap_bot.utils.subprocess_runner import run_model_in_subprocess

        log_memory_usage("start similar question matching subprocess")

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_model_in_subprocess,
            "find_similar_question",
            question,
            answered_questions,
            threshold
        )

        log_memory_usage("end similar question matching subprocess")

        return result

    except Exception as e:
        logger.exception(f"Similar question matching failed: {e}")
        return None


async def generate_daily_tip() -> str:
    """Generate a daily tip using AI with subprocess memory isolation"""
    try:
        # Check if there's already a manual tip for today
        today = datetime.now(timezone.utc).weekday()  # 0=Monday, 6=Sunday
        manual_tip = get_tip_for_day(today)
        
        if manual_tip and manual_tip.get('is_manual'):
            return manual_tip['tip_text']

        # Use subprocess for AI tip generation to ensure memory cleanup
        from avap_bot.utils.subprocess_runner import run_model_in_subprocess

        log_memory_usage("start AI tip generation subprocess")

        openai_key = os.getenv("OPENAI_API_KEY")
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            run_model_in_subprocess,
            "generate_ai_tip",
            openai_key=openai_key
        )

        log_memory_usage("end AI tip generation subprocess")

        return result if result else _get_default_tip(today)
        
    except Exception as e:
        logger.exception(f"AI tip generation failed: {e}")
        return _get_default_tip(datetime.now(timezone.utc).weekday())


def _get_default_tip(day_of_week: int) -> str:
    """Get a default tip for the day of week"""
    default_tips = [
        "💡 Remember: Consistency is key to success! Keep working on your goals every day.",
        "🎯 Set small, achievable goals for today. Progress is made one step at a time.",
        "📚 Learning is a journey, not a destination. Enjoy the process and celebrate your progress.",
        "🔥 Don't wait for motivation - create it! Start with small actions and build momentum.",
        "🌟 Every expert was once a beginner. Your current struggles are building your future expertise.",
        "⏰ Time management tip: Use the Pomodoro technique - 25 minutes focused work, 5 minutes break.",
        "🚀 Break complex tasks into smaller, manageable steps. Each step forward is progress."
    ]
    
    return default_tips[day_of_week]