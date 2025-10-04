#!/usr/bin/env python3
"""
External keep-alive monitor for AVAP Support Bot
This script can be run externally to ping the bot and keep it alive
"""
import asyncio
import httpx
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot URL - replace with your actual bot URL
BOT_URL = "https://your-bot-name.onrender.com"  # Replace with your actual URL

async def ping_bot():
    """Ping the bot to keep it alive."""
    try:
        async with httpx.AsyncClient() as client:
            # Ping multiple endpoints
            endpoints = ["/ping", "/", "/health"]
            
            for endpoint in endpoints:
                try:
                    response = await client.get(f"{BOT_URL}{endpoint}", timeout=5.0)
                    if response.status_code == 200:
                        logger.info(f"✅ {endpoint} - OK")
                    else:
                        logger.warning(f"⚠️ {endpoint} - Status {response.status_code}")
                except Exception as e:
                    logger.error(f"❌ {endpoint} - Error: {e}")
            
    except Exception as e:
        logger.error(f"Failed to ping bot: {e}")

async def main():
    """Main monitoring loop."""
    logger.info(f"Starting keep-alive monitor for {BOT_URL}")
    
    while True:
        await ping_bot()
        await asyncio.sleep(30)  # Ping every 30 seconds

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Monitor stopped")
    except Exception as e:
        logger.error(f"Monitor failed: {e}")
