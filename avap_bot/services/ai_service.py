"""
AI service for Hugging Face integration
"""
import os
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import requests
from sentence_transformers import SentenceTransformer
import numpy as np

from avap_bot.services.supabase_service import get_faqs, get_tip_for_day, add_manual_tip

logger = logging.getLogger(__name__)

# Initialize sentence transformer model
model = None

def get_model():
    """Get or initialize the sentence transformer model"""
    global model
    if model is None:
        model = SentenceTransformer('all-MiniLM-L6-v2')
    return model


async def find_faq_match(question: str, threshold: float = 0.8) -> Optional[Dict[str, Any]]:
    """Find best FAQ match using semantic similarity"""
    try:
        # Get all FAQs
        faqs = get_faqs()
        if not faqs:
            return None

        # Get sentence transformer model
        transformer = get_model()

        # Encode question and FAQ questions
        question_embedding = transformer.encode([question])
        faq_questions = [faq['question'] for faq in faqs]
        faq_embeddings = transformer.encode(faq_questions)

        # Calculate similarities
        similarities = np.dot(question_embedding, faq_embeddings.T)[0]

        # Find best match
        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]

        if best_similarity >= threshold:
            return faqs[best_idx]

        return None

    except Exception as e:
        logger.exception("Failed to find FAQ match: %s", e)
        return None


async def find_similar_answered_question(question: str, threshold: float = 0.75) -> Optional[Dict[str, Any]]:
    """Find similar previously answered questions using semantic similarity"""
    try:
        from avap_bot.services.supabase_service import get_answered_questions

        # Get previously answered questions
        answered_questions = get_answered_questions()
        if not answered_questions:
            return None

        # Get sentence transformer model
        transformer = get_model()

        # Encode question and answered questions
        question_embedding = transformer.encode([question])
        answered_texts = [q['question_text'] for q in answered_questions]
        answered_embeddings = transformer.encode(answered_texts)

        # Calculate similarities
        similarities = np.dot(question_embedding, answered_embeddings.T)[0]

        # Find best match
        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]

        if best_similarity >= threshold:
            return answered_questions[best_idx]

        return None

    except Exception as e:
        logger.exception("Failed to find similar answered question: %s", e)
        return None


async def generate_daily_tip() -> str:
    """Generate a daily tip using AI"""
    try:
        # Check if there's already a manual tip for today
        today = datetime.now(timezone.utc).weekday()  # 0=Monday, 6=Sunday
        manual_tip = get_tip_for_day(today)
        
        if manual_tip and manual_tip.get('is_manual'):
            return manual_tip['tip_text']
        
        # Generate AI tip using Hugging Face API
        hf_token = os.getenv("HUGGINGFACE_TOKEN")
        if not hf_token:
            # Fallback to default tips
            return _get_default_tip(today)
        
        # Use Hugging Face API for text generation
        api_url = "https://api-inference.huggingface.co/models/gpt2"
        headers = {"Authorization": f"Bearer {hf_token}"}
        
        prompt = "Here's an inspirational quote for students:"
        data = {
            "inputs": prompt,
            "parameters": {
                "max_length": 100,
                "temperature": 0.8,
                "do_sample": True
            }
        }
        
        response = requests.post(api_url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                generated_text = result[0].get('generated_text', '')
                # Clean up the generated text
                tip = generated_text.replace(prompt, '').strip()
                if tip:
                    return tip
        
        # Fallback to default tips
        return _get_default_tip(today)
        
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
        openai.api_key = os.getenv("OPENAI_API_KEY")
        client = openai.OpenAI(api_key=openai.api_key)

        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        
        # Clean up
        import os
        os.remove(file_path)
        
        return transcript.text
        
    except Exception as e:
        logger.exception("Failed to transcribe audio: %s", e)
        return None


async def answer_question_with_ai(question: str) -> Optional[str]:
    """Answer question using ChatGPT/OpenAI if no FAQ match found"""
    try:
        # First try FAQ matching
        faq_match = await find_faq_match(question)
        if faq_match:
            return faq_match['answer']

        # If no FAQ match, use ChatGPT/OpenAI for intelligent answers
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

        client = openai.OpenAI(api_key=openai_key)

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}\n\nPlease provide a helpful answer:"}
            ],
            max_tokens=300,
            temperature=0.7
        )

        answer = response.choices[0].message.content.strip()
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
