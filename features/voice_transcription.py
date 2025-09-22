"""
Voice Note Transcription feature for AVAP bot.
Transcribes voice messages from students using OpenAI Whisper API.
"""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters, Application
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
        
        # Save to Google Sheets if configured
        await save_transcription_to_sheets(update, transcription)
        
    except Exception as e:
        logger.exception(f"Failed to process voice message: {e}")
        await processing_msg.edit_text("❌ An error occurred while processing your voice message.")

async def save_transcription_to_sheets(update: Update, transcription: str):
    """Save transcription to Google Sheets if gs_sheet is available."""
    try:
        from bot import gs_sheet  # reuse initialized sheet client if present
    except Exception:
        gs_sheet = None
    if not gs_sheet:
        return
    try:
        user = update.effective_user
        username = user.username or user.full_name or "Unknown"
        sheet_name = "VoiceTranscriptions"
        try:
            sheet = gs_sheet.worksheet(sheet_name)
        except Exception:
            sheet = gs_sheet.add_worksheet(title=sheet_name, rows=1000, cols=6)
        sheet.append_row([username, str(user.id), transcription], value_input_option="RAW")
    except Exception as e:
        logger.exception(f"Failed to save transcription to sheets: {e}")

def register_handlers(application: Application):
    """Register voice transcription handlers."""
    # Only handle voice messages in private chats
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, voice_handler))
