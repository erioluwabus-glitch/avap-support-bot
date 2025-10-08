#!/usr/bin/env python3
"""
Comprehensive test for Systeme.io tagging fix
This script tests the improved tagging logic to ensure it works correctly
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncio
from unittest.mock import Mock, AsyncMock, patch
import json

# Mock the httpx library
class MockResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"id": "test_contact_id"}

class MockHttpxClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_log = []

    async def post(self, url, **kwargs):
        self.call_log.append(("POST", url, kwargs))
        return self.responses.get(url, MockResponse(404))

    async def put(self, url, **kwargs):
        self.call_log.append(("PUT", url, kwargs))
        return self.responses.get(url, MockResponse(404))

    async def patch(self, url, **kwargs):
        self.call_log.append(("PATCH", url, kwargs))
        return self.responses.get(url, MockResponse(404))

    async def get(self, url, **kwargs):
        self.call_log.append(("GET", url, kwargs))
        return self.responses.get(url, MockResponse(404))

async def test_systeme_tagging_fix():
    """Test the improved Systeme.io tagging logic"""
    print("🧪 Testing Systeme.io tagging fix...")

    # Mock environment variables
    with patch.dict(os.environ, {
        'SYSTEME_API_KEY': 'test_key_12345678901234567890123456789012345678901234567890',
        'SYSTEME_VERIFIED_TAG_ID': 'verified_tag_123',
        'SYSTEME_BASE_URL': 'https://api.systeme.io'
    }):

        # Import after mocking environment
        from avap_bot.services.systeme_service import _apply_verified_tag, _apply_tag_alternative

        # Test 1: Successful tag application on first endpoint
        print("\n1️⃣ Testing successful tag application...")
        client = MockHttpxClient({
            'https://api.systeme.io/contacts/test_contact_id/tags': MockResponse(200, '{"success": true}')
        })

        success = await _apply_verified_tag('test_contact_id', client, {'X-API-Key': 'test_key'})
        assert success == True, "Tag application should succeed"
        assert len(client.call_log) == 1, "Should only make one API call for successful case"
        print("✅ Successful tag application test passed")

        # Test 2: 404 errors on all endpoints, then alternative method succeeds
        print("\n2️⃣ Testing fallback to alternative methods...")
        client = MockHttpxClient({
            # All standard endpoints return 404
            'https://api.systeme.io/contacts/test_contact_id/tags': MockResponse(404),
            'https://api.systeme.io/api/contacts/test_contact_id/tags': MockResponse(404),
            # Alternative update endpoint succeeds
            'https://api.systeme.io/contacts/test_contact_id': MockResponse(200, '{"success": true}')
        })

        success = await _apply_verified_tag('test_contact_id', client, {'X-API-Key': 'test_key'})
        assert success == True, "Alternative tag application should succeed"
        assert len(client.call_log) >= 3, "Should try multiple endpoints before succeeding"
        print("✅ Alternative method fallback test passed")

        # Test 3: All methods fail
        print("\n3️⃣ Testing all methods fail scenario...")
        client = MockHttpxClient({
            # All endpoints return 404
            'https://api.systeme.io/contacts/test_contact_id/tags': MockResponse(404),
            'https://api.systeme.io/api/contacts/test_contact_id/tags': MockResponse(404),
            'https://api.systeme.io/contacts/test_contact_id': MockResponse(404),
        })

        success = await _apply_verified_tag('test_contact_id', client, {'X-API-Key': 'test_key'})
        assert success == False, "Should return False when all methods fail"
        print("✅ All methods fail scenario test passed")

        print("\n🎉 All Systeme.io tagging fix tests passed!")
        print("✅ Contact creation and tagging should now work reliably")
        print("✅ Multiple fallback methods ensure tags are applied even if API endpoints change")

if __name__ == "__main__":
    try:
        asyncio.run(test_systeme_tagging_fix())
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
