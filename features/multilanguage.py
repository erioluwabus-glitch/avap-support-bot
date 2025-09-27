"""
Multi-language Support feature for AVAP bot.
Allows users to set language preferences and translates outgoing messages.
"""
import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from avap_bot.utils.db_access import set_user_language, get_user_language
from avap_bot.utils.translator import get_supported_languages, translate

logger = logging.getLogger(__name__)

# Environment variables
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

async def setlang_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setlang command to set user language preference."""
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use this command in a private chat with the bot.")
        return
    
    if not context.args:
        # Show available languages
        languages = get_supported_languages()
        message = "🌍 Available Languages:\n\n"
        
        # Show first 20 languages in a nice format
        lang_items = list(languages.items())[:20]
        for code, name in lang_items:
            message += f"• {code}: {name}\n"
        
        if len(languages) > 20:
            message += f"\n... and {len(languages) - 20} more languages available."
        
        message += f"\n\nUsage: /setlang <language_code>\nExample: /setlang es"
        await update.message.reply_text(message)
        return
    
    lang_code = context.args[0].lower()
    languages = get_supported_languages()
    
    if lang_code not in languages:
        await update.message.reply_text(f"❌ Language code '{lang_code}' not supported.\n\nUse /setlang to see available languages.")
        return
    
    # Set user language
    success = await set_user_language(update.effective_user.id, lang_code)
    
    if success:
        language_name = languages[lang_code]
        message = f"✅ Language set to {language_name} ({lang_code})"
        
        # Translate the message to the new language
        translated_message = translate(message, lang_code)
        await update.message.reply_text(translated_message)
    else:
        await update.message.reply_text("❌ Failed to set language preference. Please try again.")

async def getlang_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /getlang command to show current language preference."""
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use this command in a private chat with the bot.")
        return
    
    current_lang = await get_user_language(update.effective_user.id)
    languages = get_supported_languages()
    language_name = languages.get(current_lang, current_lang)
    
    message = f"🌍 Your current language: {language_name} ({current_lang})"
    
    # Translate the message to user's language
    translated_message = translate(message, current_lang)
    await update.message.reply_text(translated_message)

def translate_message(message: str, user_id: int, target_lang: str = None) -> str:
    """
    Translate a message for a specific user.
    
    Args:
        message: Message to translate
        user_id: User's Telegram ID
        target_lang: Target language (if None, uses user's preference)
    
    Returns:
        Translated message
    """
    if target_lang is None:
        # This would need to be async in a real implementation
        # For now, we'll use the default language
        target_lang = DEFAULT_LANGUAGE
    
    return translate(message, target_lang)

def register_handlers(application: Application):
    """Register multi-language handlers."""
    application.add_handler(CommandHandler("setlang", setlang_handler))
    application.add_handler(CommandHandler("getlang", getlang_handler))
