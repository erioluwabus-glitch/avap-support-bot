#!/usr/bin/env python3
"""
Test script for Google Sheets integration (Option B - single spreadsheet)
Tests CSV fallback when Sheets is not available
"""
import os
import sys
import logging
from datetime import datetime, timezone

# Add the parent directory to the path so we can import avap_bot
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avap_bot.services.sheets_service import (
    append_pending_verification,
    append_submission,
    append_win,
    append_question,
    list_achievers
)
from avap_bot.utils.run_blocking import run_blocking
import asyncio

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_sheets_integration():
    """Test all sheets operations"""
    logger.info("Starting Google Sheets integration test...")
    
    # Test data
    test_pending = {
        "name": "Test Student",
        "email": "test@example.com",
        "phone": "+1234567890",
        "status": "Pending",
        "created_at": datetime.now(timezone.utc)
    }
    
    test_submission = {
        "submission_id": "test_sub_123",
        "username": "testuser",
        "telegram_id": 123456789,
        "module": "Module 1",
        "type": "text",
        "file_id": "test_file_123",
        "file_name": "test_submission.txt",
        "submitted_at": datetime.now(timezone.utc),
        "status": "Pending"
    }
    
    test_win = {
        "win_id": "test_win_123",
        "username": "testuser",
        "telegram_id": 123456789,
        "type": "achievement",
        "file_id": "test_win_123",
        "file_name": "test_win.jpg",
        "shared_at": datetime.now(timezone.utc)
    }
    
    test_question = {
        "question_id": "test_q_123",
        "username": "testuser",
        "telegram_id": 123456789,
        "question_text": "How do I submit my assignment?",
        "file_id": "",
        "file_name": "",
        "asked_at": datetime.now(timezone.utc),
        "status": "Pending"
    }
    
    try:
        # Test 1: Append pending verification
        logger.info("Test 1: Appending pending verification...")
        result = await run_blocking(append_pending_verification, test_pending)
        logger.info(f"Pending verification result: {result}")
        
        # Test 2: Append submission
        logger.info("Test 2: Appending submission...")
        result = await run_blocking(append_submission, test_submission)
        logger.info(f"Submission result: {result}")
        
        # Test 3: Append win
        logger.info("Test 3: Appending win...")
        result = await run_blocking(append_win, test_win)
        logger.info(f"Win result: {result}")
        
        # Test 4: Append question
        logger.info("Test 4: Appending question...")
        result = await run_blocking(append_question, test_question)
        logger.info(f"Question result: {result}")
        
        # Test 5: List achievers
        logger.info("Test 5: Listing achievers...")
        achievers = await run_blocking(list_achievers)
        logger.info(f"Found {len(achievers)} achievers")
        
        logger.info("✅ All tests completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        return False

async def test_csv_fallback():
    """Test CSV fallback functionality"""
    logger.info("Testing CSV fallback...")
    
    # Check if CSV directory exists
    csv_dir = "/tmp/avap_sheets"
    if os.path.exists(csv_dir):
        logger.info(f"CSV directory exists: {csv_dir}")
        files = os.listdir(csv_dir)
        logger.info(f"CSV files: {files}")
    else:
        logger.warning("CSV directory does not exist - this is expected if Sheets is configured")

if __name__ == "__main__":
    print("AVAP Bot - Google Sheets Integration Test")
    print("=" * 50)
    
    # Check environment variables
    required_env_vars = ["GOOGLE_CREDENTIALS_JSON", "GOOGLE_SHEET_ID"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {missing_vars}")
        logger.info("This is expected - CSV fallback will be used")
    else:
        logger.info("Google Sheets environment variables found")
    
    # Run tests
    success = asyncio.run(test_sheets_integration())
    asyncio.run(test_csv_fallback())
    
    if success:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)
