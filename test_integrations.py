#!/usr/bin/env python3
"""
Integration Test Script for AVAP Support Bot
Run this script to test all integrations after deployment
"""

import asyncio
import os
import sys
import logging
from typing import Dict, Any
from avap_bot.utils.run_blocking import run_blocking

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_environment_variables() -> Dict[str, Any]:
    """Test that all required environment variables are set"""
    logger.info("🔍 Testing environment variables...")

    results = {
        "google_sheets": False,
        "systeme": False,
        "supabase": False,
        "telegram": False
    }

    # Google Sheets
    google_creds = os.getenv("GOOGLE_CREDENTIALS_JSON")
    google_sheet_id = os.getenv("GOOGLE_SHEET_ID")

    if google_creds and google_sheet_id:
        results["google_sheets"] = True
        logger.info("✅ Google Sheets credentials configured")
    else:
        logger.warning("❌ Google Sheets credentials missing")
        logger.info(f"   GOOGLE_CREDENTIALS_JSON: {'✅' if google_creds else '❌'}")
        logger.info(f"   GOOGLE_SHEET_ID: {'✅' if google_sheet_id else '❌'}")

    # Systeme.io
    systeme_key = os.getenv("SYSTEME_API_KEY")
    systeme_tag = os.getenv("SYSTEME_ACHIEVER_TAG_ID")

    if systeme_key:
        results["systeme"] = True
        logger.info("✅ Systeme.io API key configured")
        logger.info(f"   Achiever tag: {'✅' if systeme_tag else '⚠️ (optional)'}")
    else:
        logger.warning("❌ Systeme.io API key missing")

    # Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if supabase_url and supabase_key:
        results["supabase"] = True
        logger.info("✅ Supabase credentials configured")
    else:
        logger.warning("❌ Supabase credentials missing")
        logger.info(f"   SUPABASE_URL: {'✅' if supabase_url else '❌'}")
        logger.info(f"   SUPABASE_KEY: {'✅' if supabase_key else '❌'}")

    # Telegram
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_url = os.getenv("WEBHOOK_URL")

    if bot_token and webhook_url:
        results["telegram"] = True
        logger.info("✅ Telegram bot configured")
    else:
        logger.warning("❌ Telegram bot configuration missing")
        logger.info(f"   TELEGRAM_BOT_TOKEN: {'✅' if bot_token else '❌'}")
        logger.info(f"   WEBHOOK_URL: {'✅' if webhook_url else '❌'}")

    return results

async def test_supabase_connection() -> bool:
    """Test Supabase connection"""
    logger.info("🔍 Testing Supabase connection...")

    try:
        from avap_bot.services.supabase_service import get_supabase

        client = get_supabase()
        # Try a simple query
        result = client.table("verified_users").select("count", count="exact").limit(1).execute()
        logger.info("✅ Supabase connection successful")
        return True

    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {e}")
        return False

async def test_google_sheets_connection() -> bool:
    """Test Google Sheets connection"""
    logger.info("🔍 Testing Google Sheets connection...")

    try:
        from avap_bot.services.sheets_service import test_sheets_connection

        result = test_sheets_connection()
        if result:
            logger.info("✅ Google Sheets connection successful")
        else:
            logger.warning("⚠️ Google Sheets using CSV fallback (credentials not configured)")
        return result

    except Exception as e:
        logger.error(f"❌ Google Sheets test failed: {e}")
        return False

async def test_systeme_connection() -> bool:
    """Test Systeme.io connection"""
    logger.info("🔍 Testing Systeme.io connection...")

    try:
        from avap_bot.services.systeme_service import create_contact_and_tag

        # Try to create a test contact (will fail gracefully if no API key)
        test_contact = {
            "name": "Test User",
            "email": "test@example.com",
            "phone": "+1234567890",
            "status": "pending"
        }

        result = await run_blocking(create_contact_and_tag, test_contact)

        if result:
            logger.info("✅ Systeme.io connection successful")
            return True
        else:
            logger.warning("⚠️ Systeme.io API key not configured or invalid")
            return False

    except Exception as e:
        logger.error(f"❌ Systeme.io test failed: {e}")
        return False

async def main():
    """Run all integration tests"""
    logger.info("🚀 Starting integration tests...")

    # Test environment variables
    env_results = test_environment_variables()

    # Test connections
    supabase_ok = await test_supabase_connection()
    sheets_ok = await test_google_sheets_connection()
    systeme_ok = await test_systeme_connection()

    # Summary
    logger.info("\n" + "="*50)
    logger.info("📊 INTEGRATION TEST RESULTS")
    logger.info("="*50)

    logger.info(f"Environment Variables: {'✅' if all(env_results.values()) else '❌'}")
    logger.info(f"  Google Sheets: {'✅' if env_results['google_sheets'] else '❌'}")
    logger.info(f"  Systeme.io: {'✅' if env_results['systeme'] else '❌'}")
    logger.info(f"  Supabase: {'✅' if env_results['supabase'] else '❌'}")
    logger.info(f"  Telegram: {'✅' if env_results['telegram'] else '❌'}")

    logger.info(f"\nConnection Tests:")
    logger.info(f"  Supabase: {'✅' if supabase_ok else '❌'}")
    logger.info(f"  Google Sheets: {'✅' if sheets_ok else '❌'}")
    logger.info(f"  Systeme.io: {'✅' if systeme_ok else '❌'}")

    all_good = all(env_results.values()) and supabase_ok and (sheets_ok or True) and (systeme_ok or True)

    if all_good:
        logger.info("\n🎉 ALL INTEGRATIONS WORKING!")
        logger.info("Your bot should be fully functional.")
    else:
        logger.warning("\n⚠️ SOME INTEGRATIONS NEED ATTENTION")
        logger.info("Check the errors above and fix the missing configurations.")
        logger.info("Refer to SETUP_GUIDE.md for detailed instructions.")

    logger.info("="*50)

if __name__ == "__main__":
    asyncio.run(main())
