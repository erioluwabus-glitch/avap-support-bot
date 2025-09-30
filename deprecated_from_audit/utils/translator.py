"""
Translation utilities using deep-translator.
Provides caching and error handling for multi-language support.
"""
import logging
from typing import Optional
from deep_translator import GoogleTranslator
import functools

logger = logging.getLogger(__name__)

# Cache for translations to avoid repeated API calls
_translation_cache = {}

@functools.lru_cache(maxsize=1000)
def translate(text: str, target_lang: str = 'en', source_lang: str = 'auto') -> str:
    """
    Translate text using Google Translator with caching.
    
    Args:
        text: Text to translate
        target_lang: Target language code (e.g., 'es', 'fr', 'de')
        source_lang: Source language code (default: 'auto' for auto-detection)
    
    Returns:
        Translated text or original text if translation fails
    """
    if not text or target_lang == 'en':
        return text
    
    # Check cache first
    cache_key = f"{source_lang}:{target_lang}:{text}"
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]
    
    try:
        translator = GoogleTranslator(source=source_lang, target=target_lang)
        translated = translator.translate(text)
        
        # Cache the result
        _translation_cache[cache_key] = translated
        return translated
        
    except Exception as e:
        logger.exception(f"Translation failed for '{text}' to {target_lang}: {e}")
        return text  # Return original text if translation fails

def clear_cache():
    """Clear the translation cache."""
    global _translation_cache
    _translation_cache.clear()
    translate.cache_clear()

def get_supported_languages() -> dict:
    """Get dictionary of supported language codes and names."""
    return {
        'en': 'English',
        'es': 'Spanish',
        'fr': 'French',
        'de': 'German',
        'it': 'Italian',
        'pt': 'Portuguese',
        'ru': 'Russian',
        'ja': 'Japanese',
        'ko': 'Korean',
        'zh': 'Chinese',
        'ar': 'Arabic',
        'hi': 'Hindi',
        'th': 'Thai',
        'vi': 'Vietnamese',
        'tr': 'Turkish',
        'pl': 'Polish',
        'nl': 'Dutch',
        'sv': 'Swedish',
        'da': 'Danish',
        'no': 'Norwegian',
        'fi': 'Finnish',
        'cs': 'Czech',
        'hu': 'Hungarian',
        'ro': 'Romanian',
        'bg': 'Bulgarian',
        'hr': 'Croatian',
        'sk': 'Slovak',
        'sl': 'Slovenian',
        'et': 'Estonian',
        'lv': 'Latvian',
        'lt': 'Lithuanian',
        'uk': 'Ukrainian',
        'be': 'Belarusian',
        'mk': 'Macedonian',
        'sq': 'Albanian',
        'sr': 'Serbian',
        'bs': 'Bosnian',
        'mt': 'Maltese',
        'is': 'Icelandic',
        'ga': 'Irish',
        'cy': 'Welsh',
        'eu': 'Basque',
        'ca': 'Catalan',
        'gl': 'Galician'
    }
