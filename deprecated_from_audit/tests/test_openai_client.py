"""
Unit tests for OpenAI client utilities.
"""
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import os
from avap_bot.utils.openai_client import suggest_answer, transcribe_audio, download_and_transcribe_voice

class TestOpenAIClient(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variable
        os.environ['OPENAI_API_KEY'] = 'test-key'
    
    @patch('utils.openai_client.get_client')
    async def test_suggest_answer_success(self, mock_get_client):
        """Test successful answer suggestion."""
        # Mock OpenAI client response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a suggested answer."
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client
        
        question = "How do I study effectively?"
        result = await suggest_answer(question)
        
        self.assertEqual(result, "This is a suggested answer.")
        mock_client.chat.completions.create.assert_called_once()
    
    @patch('utils.openai_client.get_client')
    async def test_suggest_answer_no_client(self, mock_get_client):
        """Test answer suggestion when no OpenAI client is available."""
        mock_get_client.return_value = None
        
        question = "How do I study effectively?"
        result = await suggest_answer(question)
        
        self.assertIsNone(result)
    
    @patch('utils.openai_client.get_client')
    async def test_suggest_answer_error(self, mock_get_client):
        """Test answer suggestion error handling."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client
        
        question = "How do I study effectively?"
        result = await suggest_answer(question)
        
        self.assertIsNone(result)
    
    @patch('utils.openai_client.get_client')
    async def test_transcribe_audio_success(self, mock_get_client):
        """Test successful audio transcription."""
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = "This is transcribed text."
        mock_get_client.return_value = mock_client
        
        result = await transcribe_audio("test_file.mp3")
        
        self.assertEqual(result, "This is transcribed text.")
    
    @patch('utils.openai_client.get_client')
    async def test_transcribe_audio_error(self, mock_get_client):
        """Test audio transcription error handling."""
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client
        
        result = await transcribe_audio("test_file.mp3")
        
        self.assertIsNone(result)
    
    @patch('utils.openai_client.transcribe_audio')
    @patch('utils.openai_client.tempfile')
    @patch('utils.openai_client.os')
    async def test_download_and_transcribe_voice(self, mock_os, mock_tempfile, mock_transcribe):
        """Test download and transcribe voice message."""
        # Mock bot and file info
        mock_bot = AsyncMock()
        mock_file_info = AsyncMock()
        mock_bot.get_file.return_value = mock_file_info
        
        # Mock tempfile
        mock_temp_file = MagicMock()
        mock_temp_file.name = "temp_file.ogg"
        mock_tempfile.NamedTemporaryFile.return_value.__enter__.return_value = mock_temp_file
        
        # Mock transcription
        mock_transcribe.return_value = "Transcribed text"
        
        result = await download_and_transcribe_voice(mock_bot, "file_id_123")
        
        self.assertEqual(result, "Transcribed text")
        mock_bot.get_file.assert_called_once_with("file_id_123")
        mock_file_info.download_to_drive.assert_called_once_with("temp_file.ogg")
        mock_transcribe.assert_called_once_with("temp_file.ogg")
        mock_os.unlink.assert_called_once_with("temp_file.ogg")

if __name__ == '__main__':
    unittest.main()
