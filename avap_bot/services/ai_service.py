"""
AI service for Hugging Face integration with memory optimization
"""
import os
import logging
import asyncio
import gc
import psutil
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
        # Force immediate cleanup after each use
        for _ in range(5):
            gc.collect()
        # Clear model cache after each use for maximum memory efficiency
        clear_model_cache()

def clear_model_cache():
    """Force clear the model cache"""
    global _model, _model_last_used
    if _model:
        del _model
        _model = None
    _model_last_used = None

    # Force aggressive garbage collection
    for _ in range(5):
        gc.collect()
    log_memory_usage("after model cache clear")


async def find_faq_match(question: str, threshold: float = 0.8) -> Optional[Dict[str, Any]]:
    """Find best FAQ match using semantic similarity with subprocess memory isolation"""
    try:
        # Get all FAQs
        faqs = get_faqs()
        if not faqs:
            return None

        # Limit FAQ list size to prevent memory issues (top 20 FAQs for memory efficiency)
        max_faqs = 20
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
        logger.exception("Failed to find FAQ match: %s", e)
        return None


async def find_similar_answered_question(question: str, threshold: float = 0.8) -> Optional[Dict[str, Any]]:
    """Find similar previously answered questions using semantic similarity with subprocess memory isolation"""
    try:
        from avap_bot.services.supabase_service import get_answered_questions

        # Get previously answered questions
        answered_questions = get_answered_questions()
        if not answered_questions:
            return None

        # Limit answered questions to prevent memory issues (top 100)
        max_questions = 100
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
        logger.exception("Failed to find similar answered question: %s", e)
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
        logger.exception("Failed to generate daily tip: %s", e)
        return _get_default_tip(datetime.now(timezone.utc).weekday())


def _get_default_tip(day_of_week: int) -> str:
    """Get default tip for day of week"""
    default_tips = [
        "Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill",
        "The only way to do great work is to love what you do. - Steve Jobs", 
        "Believe you can and you're halfway there. - Theodore Roosevelt",
        "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
        "It is during our darkest moments that we must focus to see the light. - Aristotle",
        "The way to get started is to quit talking and begin doing. - Walt Disney",
        "Don't be pushed around by the fears in your mind. Be led by the dreams in your heart. - Roy T. Bennett"
    ]
    
    return default_tips[day_of_week]


async def transcribe_audio(file_id: str, bot) -> Optional[str]:
    """Transcribe audio using OpenAI Whisper API"""
    try:
        # Download file from Telegram
        file = await bot.get_file(file_id)
        file_path = f"/tmp/audio_{file_id}.ogg"
        
        # Download file
        await file.download_to_drive(file_path)
        
        # Use OpenAI for transcription
        import openai
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            logger.error("OpenAI API key not configured")
            return None

        try:
            client = openai.OpenAI(api_key=openai_key)
        except (TypeError, AttributeError) as e:
            if "proxies" in str(e) or "unexpected keyword" in str(e):
                # Handle version compatibility issue
                logger.warning(f"OpenAI client init error: {e}. Trying without proxies parameter.")
                try:
                    # Try the older initialization method
                    openai.api_key = openai_key
                    client = openai
                except Exception as fallback_error:
                    logger.error(f"OpenAI fallback also failed: {fallback_error}")
                    return None
            else:
                logger.error(f"OpenAI initialization failed: {e}")
                return None

        try:
            with open(file_path, "rb") as audio_file:
                if hasattr(client, 'audio'):
                    # New OpenAI client style
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                    )
                else:
                    # Old OpenAI API style
                    transcript = client.Audio.transcribe("whisper-1", audio_file)
        except AttributeError as e:
            logger.error(f"OpenAI audio transcription methods not available: {e}")
            import os
            os.remove(file_path)
            return None
        except Exception as e:
            logger.error(f"OpenAI audio transcription failed: {e}")
            import os
            os.remove(file_path)
            return None
        
        return transcript.text
        
    except Exception as e:
        logger.exception("Failed to transcribe audio: %s", e)
        return None


async def process_question_with_ai(question: str) -> Dict[str, Any]:
    """
    Process question with all AI services in one go to minimize memory usage.
    Returns a dict with the best answer found and its source.
    """
    try:
        # First try FAQ matching (most memory efficient)
        faq_match = await find_faq_match(question)
        if faq_match:
            return {
                'answer': faq_match['answer'],
                'source': 'faq',
                'question': faq_match['question']
            }

        # Then try similar answered questions
        similar_answer = await find_similar_answered_question(question)
        if similar_answer:
            return {
                'answer': similar_answer['answer'],
                'source': 'similar',
                'question': similar_answer['question_text']
            }

        # Finally try AI generation
        ai_answer = await answer_question_with_ai(question)
        if ai_answer:
            return {
                'answer': ai_answer,
                'source': 'ai',
                'question': question
            }

        return None

    except Exception as e:
        logger.exception("Failed to process question with AI: %s", e)
        return None


async def answer_question_with_ai(question: str) -> Optional[str]:
    """Answer question using ChatGPT/OpenAI for intelligent answers"""
    try:
        # Use ChatGPT/OpenAI for intelligent answers
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            # Fallback to Hugging Face if OpenAI is not available
            return await _answer_with_huggingface(question)

        import openai
        openai.api_key = openai_key

        # Use ChatGPT for contextual question answering
        context = (
            "You are a helpful support bot assistant for AVAP course students. "
            "AVAP is a comprehensive course with 12 modules covering various topics. "
            "Students can submit assignments, share wins, ask questions, check their progress, "
            "and earn badges for participation. Common student activities include: "
            "submitting text/audio/video assignments, sharing achievements, asking for help, "
            "and getting matched with study partners."
        )

        system_prompt = (
            "You are an expert AVAP course assistant. Provide helpful, accurate answers "
            "about course procedures, assignments, progress tracking, and community features. "
            "Be encouraging and supportive in your responses."
        )

        try:
            client = openai.OpenAI(api_key=openai_key)
        except (TypeError, AttributeError) as e:
            if "proxies" in str(e) or "unexpected keyword" in str(e):
                # Handle version compatibility issue
                logger.warning(f"OpenAI client init error: {e}. Trying without proxies parameter.")
                try:
                    # Try the older initialization method
                    openai.api_key = openai_key
                    client = openai
                except Exception as fallback_error:
                    logger.error(f"OpenAI fallback also failed: {fallback_error}")
                    return None
            else:
                logger.error(f"OpenAI initialization failed: {e}")
                return None

        try:
            if hasattr(client, 'chat'):
                # New OpenAI client style
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}\n\nPlease provide a helpful answer:"}
                    ],
                    max_tokens=300,
                    temperature=0.7
                )
            else:
                # Old OpenAI API style
                response = client.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}\n\nPlease provide a helpful answer:"}
                    ],
                    max_tokens=300,
                    temperature=0.7
                )
        except AttributeError as e:
            logger.error(f"OpenAI API methods not available: {e}")
            return None
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return None

        answer = response.choices[0].message.content.strip() if hasattr(response.choices[0].message, 'content') else response.choices[0].message['content'].strip()
        if answer:
            return answer

        return None

    except Exception as e:
        logger.exception("Failed to answer question with AI: %s", e)
        # Try Hugging Face as fallback
        try:
            return await _answer_with_huggingface(question)
        except:
            return None


async def _answer_with_huggingface(question: str) -> Optional[str]:
    """Fallback to Hugging Face if OpenAI is not available"""
    try:
        hf_token = os.getenv("HUGGINGFACE_TOKEN")
        if not hf_token:
            return None

        # Use Hugging Face API for question answering
        api_url = "https://api-inference.huggingface.co/models/distilbert-base-cased-distilled-squad"
        headers = {"Authorization": f"Bearer {hf_token}"}

        data = {
            "inputs": {
                "question": question,
                "context": "This is a support bot for AVAP course students. Students can submit assignments, share wins, ask questions, and check their progress. The course has 12 modules and students can earn badges for participation."
            }
        }

        response = requests.post(api_url, headers=headers, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, dict) and 'answer' in result:
                answer = result['answer']
                if answer and answer != '[CLS]':
                    return answer

        return None

    except Exception as e:
        logger.exception("Failed to answer question with Hugging Face: %s", e)
        return None
