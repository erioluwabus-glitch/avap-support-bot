"""
OpenAI client utilities for AI-powered features.
Handles API calls for FAQ suggestions and voice transcription.
"""
import os
import logging
import tempfile
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = None

def init_openai_client():
    """Initialize OpenAI client with API key."""
    global client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set - AI features will be disabled")
        return None
    
    client = OpenAI(api_key=api_key)
    return client

def get_client():
    """Get OpenAI client instance."""
    global client
    if client is None:
        client = init_openai_client()
    return client

async def suggest_answer(question: str) -> Optional[str]:
    """
    Generate a suggested answer for a question using OpenAI.
    
    Args:
        question: The question to answer
    
    Returns:
        Suggested answer or None if generation fails
    """
    openai_client = get_client()
    if not openai_client:
        return None
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant for the AVAP (Academic and Professional Achievement Program) support bot. Provide concise, helpful answers to student questions about academic and professional development. Keep responses under 200 words and be encouraging and supportive."
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nPlease provide a helpful answer:"
                }
            ],
            max_tokens=300,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.exception(f"Failed to generate answer for question: {e}")
        return None

async def transcribe_audio(file_path: str) -> Optional[str]:
    """
    Transcribe audio using faster-whisper (offline) if available; fallback to OpenAI Whisper.
    """
    # Try faster-whisper first
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model_size = os.getenv("FASTER_WHISPER_MODEL", "medium")
        compute_type = os.getenv("FASTER_WHISPER_COMPUTE", "int8")
        model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
        segments, _ = model.transcribe(file_path, beam_size=5)
        text = " ".join([s.text for s in segments]).strip()
        if text:
            return text
    except Exception:
        # Fall back to OpenAI if local model not available
        pass

    openai_client = get_client()
    if not openai_client:
        return None
    try:
        with open(file_path, "rb") as audio_file:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        text = transcript.strip() if isinstance(transcript, str) else str(transcript)
        return text if text else None
    except Exception as e:
        if "insufficient_quota" in str(e) or "429" in str(e):
            logger.error(f"OpenAI quota/rate limit error during transcription: {e}")
            return None
        logger.exception(f"Failed to transcribe audio file {file_path}: {e}")
        return None

async def download_and_transcribe_voice(bot, file_id: str) -> Optional[str]:
    """
    Download voice message and transcribe it.
    
    Args:
        bot: Telegram bot instance
        file_id: Telegram file ID of the voice message
    
    Returns:
        Transcribed text or None if transcription fails
    """
    try:
        # Get file info
        file_info = await bot.get_file(file_id)
        
        # Download file to temporary location
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
            await file_info.download_to_drive(temp_file.name)
            
            # Transcribe the audio
            transcription = await transcribe_audio(temp_file.name)
            
            # Clean up temporary file
            os.unlink(temp_file.name)
            
            return transcription
            
    except Exception as e:
        logger.exception(f"Failed to download and transcribe voice {file_id}: {e}")
        return None
