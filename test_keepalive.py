#!/usr/bin/env python3
"""
Test script to verify keep-alive endpoints are working
"""
import asyncio
import httpx
import time

async def test_endpoints():
    """Test all keep-alive endpoints."""
    base_url = "http://localhost:8080"
    endpoints = ["/ping", "/", "/health"]
    
    print("🧪 Testing keep-alive endpoints...")
    
    async with httpx.AsyncClient() as client:
        for endpoint in endpoints:
            try:
                start_time = time.time()
                response = await client.get(f"{base_url}{endpoint}", timeout=5.0)
                end_time = time.time()
                
                print(f"✅ {endpoint}")
                print(f"   Status: {response.status_code}")
                print(f"   Response time: {(end_time - start_time)*1000:.1f}ms")
                print(f"   Response: {response.json()}")
                print()
                
            except Exception as e:
                print(f"❌ {endpoint} - Error: {e}")
                print()

async def continuous_test():
    """Continuously test endpoints to simulate keep-alive."""
    print("🔄 Starting continuous keep-alive test...")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            await test_endpoints()
            print("⏱️  Waiting 10 seconds...")
            print("-" * 50)
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        print("\n🛑 Test stopped")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "continuous":
        asyncio.run(continuous_test())
    else:
        asyncio.run(test_endpoints())
