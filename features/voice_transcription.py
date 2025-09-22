"""
Voice Note Transcription feature for AVAP bot.
Transcribes voice messages from students using OpenAI Whisper API.
"""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters
from utils.openai_client import download_and_transcribe_voice
from utils.db_access import init_database

logger = logging.getLogger(__name__)

# Environment variables
ASSIGNMENTS_GROUP_ID = int(os.getenv("ASSIGNMENTS_GROUP_ID", "0")) if os.getenv("ASSIGNMENTS_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0")) if os.getenv("QUESTIONS_GROUP_ID") else None

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages from verified users."""
    # Only work in private chats
    if update.effective_chat.type != "private":
        return
    
    # Check if user is verified (you might want to add this check)
    # For now, we'll process all voice messages in private chats
    
    voice = update.message.voice
    if not voice:
        return
    
    # Show processing message
    processing_msg = await update.message.reply_text("🎤 Processing voice message...")
    
    try:
        # Download and transcribe voice
        transcription = await download_and_transcribe_voice(context.bot, voice.file_id)
        
        if not transcription:
            await processing_msg.edit_text("❌ Failed to transcribe voice message. Please try again.")
            return
        
        # Send transcription back to user
        await processing_msg.edit_text(f"📝 Transcription:\n\n{transcription}")
        
        # Save to appropriate Google Sheet based on context
        # This would need to be implemented based on your existing Google Sheets integration
        await save_transcription_to_sheets(update, transcription)
        
    except Exception as e:
        logger.exception(f"Failed to process voice message: {e}")
        await processing_msg.edit_text("❌ An error occurred while processing your voice message.")

async def save_transcription_to_sheets(update: Update, transcription: str):
    """Save transcription to appropriate Google Sheet."""
    try:
        # This is a placeholder - you would integrate with your existing Google Sheets code
        # The transcription could be saved to Questions or Wins sheet based on context
        
        user = update.effective_user
        username = user.username or user.full_name or "Unknown"
        
        # For now, just log the transcription
        logger.info(f"Voice transcription from {username}: {transcription}")
        
        # You could add logic here to determine which sheet to save to
        # and integrate with your existing Google Sheets code
        
    except Exception as e:
        logger.exception(f"Failed to save transcription to sheets: {e}")

def register_handlers(application: Application):
    """Register voice transcription handlers."""
    # Only handle voice messages in private chats
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, voice_handler))
