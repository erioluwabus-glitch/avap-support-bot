#!/usr/bin/env python3
"""
Keep-alive monitoring script for AVAP Support Bot
Use this to verify the hybrid keep-alive system is working correctly
"""
import requests
import time
import json
from datetime import datetime

def test_health_endpoint():
    """Test the health endpoint"""
    url = "https://avap-support-bot-93z2.onrender.com/health"
    try:
        response = requests.get(url, timeout=10)
        return {
            "status": response.status_code,
            "response_time": response.elapsed.total_seconds(),
            "success": response.status_code == 200
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "success": False
        }

def test_ping_endpoint():
    """Test the ping endpoint"""
    url = "https://avap-support-bot-93z2.onrender.com/ping"
    try:
        response = requests.get(url, timeout=10)
        return {
            "status": response.status_code,
            "response_time": response.elapsed.total_seconds(),
            "success": response.status_code == 200
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "success": False
        }

def monitor_keepalive():
    """Monitor the keep-alive system"""
    print("🔍 AVAP Bot Keep-Alive Monitor")
    print("=" * 50)
    
    # Test health endpoint
    print("Testing /health endpoint...")
    health_result = test_health_endpoint()
    if health_result["success"]:
        print(f"✅ Health endpoint: OK (Status: {health_result['status']}, Time: {health_result['response_time']:.2f}s)")
    else:
        print(f"❌ Health endpoint: FAILED ({health_result.get('error', 'Unknown error')})")
    
    # Test ping endpoint
    print("Testing /ping endpoint...")
    ping_result = test_ping_endpoint()
    if ping_result["success"]:
        print(f"✅ Ping endpoint: OK (Status: {ping_result['status']}, Time: {ping_result['response_time']:.2f}s)")
    else:
        print(f"❌ Ping endpoint: FAILED ({ping_result.get('error', 'Unknown error')})")
    
    # Summary
    print("\n📊 Summary:")
    if health_result["success"] and ping_result["success"]:
        print("✅ Both endpoints are responding correctly")
        print("✅ Bot should stay awake with current configuration")
        print("\n🎯 Next steps:")
        print("1. Set up external pingers (Pulsetic, Cron-Job.org)")
        print("2. Monitor for 24 hours to confirm 24/7 uptime")
        print("3. Test Telegram bot responses during off-hours")
    else:
        print("❌ Some endpoints are not responding")
        print("🔧 Troubleshooting:")
        print("1. Check if Render service is running")
        print("2. Verify environment variables are set")
        print("3. Check Render logs for errors")
    
    print(f"\n⏰ Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    monitor_keepalive()
