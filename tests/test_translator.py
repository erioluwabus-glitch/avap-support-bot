"""
Unit tests for translator utilities.
"""
import unittest
from unittest.mock import patch
from utils.translator import translate, get_supported_languages, clear_cache

class TestTranslator(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        clear_cache()
    
    def test_translate_english_to_spanish(self):
        """Test translation from English to Spanish."""
        result = translate("Hello world", "es")
        # Since we're using a real translator, we'll just check it returns a string
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)
    
    def test_translate_same_language(self):
        """Test that translating to the same language returns original text."""
        text = "Hello world"
        result = translate(text, "en")
        self.assertEqual(result, text)
    
    def test_translate_empty_text(self):
        """Test translation of empty text."""
        result = translate("", "es")
        self.assertEqual(result, "")
    
    def test_translate_none_text(self):
        """Test translation of None text."""
        result = translate(None, "es")
        self.assertEqual(result, None)
    
    def test_get_supported_languages(self):
        """Test getting supported languages."""
        languages = get_supported_languages()
        self.assertIsInstance(languages, dict)
        self.assertIn("en", languages)
        self.assertIn("es", languages)
        self.assertIn("fr", languages)
        self.assertEqual(languages["en"], "English")
    
    def test_translate_with_caching(self):
        """Test that translation results are cached."""
        text = "Test caching"
        result1 = translate(text, "es")
        result2 = translate(text, "es")
        self.assertEqual(result1, result2)
    
    @patch('utils.translator.GoogleTranslator')
    def test_translate_error_handling(self, mock_translator):
        """Test error handling in translation."""
        # Mock translator to raise an exception
        mock_translator.return_value.translate.side_effect = Exception("API Error")
        
        text = "Hello world"
        result = translate(text, "es")
        
        # Should return original text on error
        self.assertEqual(result, text)

if __name__ == '__main__':
    unittest.main()
