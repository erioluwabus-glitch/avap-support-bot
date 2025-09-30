"""
Test Supabase operations
"""
import asyncio
import os
import logging
from avap_bot.services.supabase_service import init_supabase, get_supabase, add_pending_verification, check_verified_user

logger = logging.getLogger(__name__)


async def test_supabase_connection():
    """Test Supabase connection"""
    try:
        client = init_supabase()
        logger.info("✅ Supabase connection successful")
        return True
    except Exception as e:
        logger.error("❌ Supabase connection failed: %s", e)
        return False


async def test_add_pending_verification():
    """Test adding pending verification"""
    try:
        test_data = {
            "name": "Test Student",
            "email": "test@example.com",
            "phone": "+1234567890",
            "status": "Pending"
        }
        
        result = await add_pending_verification(test_data)
        if result:
            logger.info("✅ Add pending verification successful: %s", result.get('id'))
            return True
        else:
            logger.error("❌ Add pending verification failed")
            return False
    except Exception as e:
        logger.error("❌ Add pending verification error: %s", e)
        return False


async def test_check_verified_user():
    """Test checking verified user"""
    try:
        # Test with non-existent user
        result = check_verified_user(999999999)
        if result is None:
            logger.info("✅ Check verified user (non-existent) successful")
            return True
        else:
            logger.warning("⚠️ Check verified user returned unexpected result: %s", result)
            return False
    except Exception as e:
        logger.error("❌ Check verified user error: %s", e)
        return False


async def run_tests():
    """Run all tests"""
    logger.info("🧪 Starting Supabase tests...")
    
    tests = [
        ("Connection", test_supabase_connection),
        ("Add Pending", test_add_pending_verification),
        ("Check Verified", test_check_verified_user),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info("Running test: %s", test_name)
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error("Test %s failed with exception: %s", test_name, e)
            results.append((test_name, False))
    
    # Summary
    logger.info("\n📊 Test Results:")
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info("%s: %s", test_name, status)
        if result:
            passed += 1
    
    logger.info("\n🎯 Tests passed: %d/%d", passed, len(results))
    return passed == len(results)


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Check environment variables
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        logger.error("❌ SUPABASE_URL and SUPABASE_KEY must be set")
        exit(1)
    
    # Run tests
    success = asyncio.run(run_tests())
    exit(0 if success else 1)
