#!/usr/bin/env python3
"""
Test script to verify Systeme.io validation fix
This will be deleted after testing is complete
"""
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_systeme_validation():
    """Test the fixed Systeme.io validation"""
    print("Testing Systeme.io validation fix...")
    
    try:
        from avap_bot.services.systeme_service import validate_api_key, test_systeme_connection
        
        print("1. Testing validate_api_key()...")
        result = validate_api_key()
        print(f"   Result: {result}")
        
        print("2. Testing test_systeme_connection()...")
        connection_result = test_systeme_connection()
        print(f"   Result: {connection_result}")
        
        if result:
            print("✅ Systeme.io validation successful!")
        else:
            print("❌ Systeme.io validation failed!")
            
        return result
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_systeme_validation()
    if success:
        print("\n🎉 Systeme.io validation fix is working!")
    else:
        print("\n❌ Systeme.io validation fix needs more work!")
