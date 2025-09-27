"""
Admin notification service - Send notifications to admin via Telegram
"""
import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
TELEGRAM_API_URL = "https://api.telegram.org/bot"


def notify_admin_sync(message: str) -> bool:
    """Send notification to admin synchronously"""
    try:
        if not BOT_TOKEN or not ADMIN_USER_ID:
            logger.warning("BOT_TOKEN or ADMIN_USER_ID not set, cannot send notification")
            return False
        
        import requests
        
        url = f"{TELEGRAM_API_URL}{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_USER_ID,
            "text": f"🚨 AVAP Bot Alert:\n\n{message}",
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Admin notification sent successfully")
            return True
        else:
            logger.warning("Failed to send admin notification: %s", response.text)
            return False
        
    except Exception as e:
        logger.exception("Failed to send admin notification: %s", e)
        return False


async def notify_admin(message: str) -> bool:
    """Send notification to admin asynchronously"""
    try:
        if not BOT_TOKEN or not ADMIN_USER_ID:
            logger.warning("BOT_TOKEN or ADMIN_USER_ID not set, cannot send notification")
            return False
        
        url = f"{TELEGRAM_API_URL}{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": ADMIN_USER_ID,
            "text": f"🚨 AVAP Bot Alert:\n\n{message}",
            "parse_mode": "HTML"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                logger.info("Admin notification sent successfully")
                return True
            else:
                logger.warning("Failed to send admin notification: %s", response.text)
                return False
        
    except Exception as e:
        logger.exception("Failed to send admin notification: %s", e)
        return False


async def notify_admin_error(error_message: str, context: str = "") -> bool:
    """Send error notification to admin with context"""
    full_message = f"❌ <b>Error in {context}</b>\n\n{error_message}"
    return await notify_admin(full_message)


async def notify_admin_success(success_message: str, context: str = "") -> bool:
    """Send success notification to admin with context"""
    full_message = f"✅ <b>Success in {context}</b>\n\n{success_message}"
    return await notify_admin(full_message)
