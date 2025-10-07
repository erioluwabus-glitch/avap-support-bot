"""
Admin notification service - Send notifications to admin via Telegram
"""
import os
import logging
import time
import asyncio
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
TELEGRAM_API_URL = "https://api.telegram.org/bot"


def _get_retry_delay(attempt: int, status_code: int = None) -> float:
    """Calculate retry delay with exponential backoff"""
    if status_code == 429:  # Rate limited
        # Use Retry-After header if available, otherwise exponential backoff
        return min(2 ** attempt, 300)  # Max 5 minutes
    elif status_code == 401:  # Unauthorized - don't retry
        return 0  # No retry
    else:
        # Exponential backoff for other errors
        return min(2 ** attempt, 60)  # Max 1 minute


async def _send_with_retry(url: str, payload: dict, max_retries: int = 3) -> bool:
    """Send request with retry logic for 429 and temporary errors"""
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)

                if response.status_code == 200:
                    return True
                elif response.status_code == 401:
                    logger.warning("Telegram API returned 401 - check bot token")
                    return False  # Don't retry 401 errors
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = int(retry_after) if retry_after else _get_retry_delay(attempt, 429)
                    logger.warning(f"Rate limited by Telegram API, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                        continue
                elif response.status_code >= 500:
                    # Server errors - retry with exponential backoff
                    delay = _get_retry_delay(attempt)
                    logger.warning(f"Telegram API server error {response.status_code}, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
                        continue
                else:
                    logger.warning(f"Telegram API returned {response.status_code}: {response.text}")
                    return False

        except httpx.TimeoutException:
            delay = _get_retry_delay(attempt)
            logger.warning(f"Request timeout, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                await asyncio.sleep(delay)
                continue
        except Exception as e:
            delay = _get_retry_delay(attempt)
            logger.warning(f"Request failed: {e}, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                await asyncio.sleep(delay)
                continue

    logger.error(f"Failed to send after {max_retries + 1} attempts")
    return False


def _get_retry_delay_sync(attempt: int, status_code: int = None) -> float:
    """Calculate retry delay with exponential backoff (sync version)"""
    if status_code == 429:  # Rate limited
        return min(2 ** attempt, 300)  # Max 5 minutes
    elif status_code == 401:  # Unauthorized - don't retry
        return 0  # No retry
    else:
        return min(2 ** attempt, 60)  # Max 1 minute


def _send_with_retry_sync(url: str, payload: dict, max_retries: int = 3) -> bool:
    """Send request with retry logic for 429 and temporary errors (sync version)"""
    import requests
    import time

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                logger.warning("Telegram API returned 401 - check bot token")
                return False  # Don't retry 401 errors
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = int(retry_after) if retry_after else _get_retry_delay_sync(attempt, 429)
                logger.warning(f"Rate limited by Telegram API, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    time.sleep(delay)
                    continue
            elif response.status_code >= 500:
                # Server errors - retry with exponential backoff
                delay = _get_retry_delay_sync(attempt)
                logger.warning(f"Telegram API server error {response.status_code}, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    time.sleep(delay)
                    continue
            else:
                logger.warning(f"Telegram API returned {response.status_code}: {response.text}")
                return False

        except requests.exceptions.Timeout:
            delay = _get_retry_delay_sync(attempt)
            logger.warning(f"Request timeout, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                time.sleep(delay)
                continue
        except Exception as e:
            delay = _get_retry_delay_sync(attempt)
            logger.warning(f"Request failed: {e}, retrying in {delay}s (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                time.sleep(delay)
                continue

    logger.error(f"Failed to send after {max_retries + 1} attempts")
    return False


def notify_admin_sync(message: str) -> bool:
    """Send notification to admin synchronously with retry logic"""
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

        # Use retry logic for Telegram API calls
        success = _send_with_retry_sync(url, payload, max_retries=2)

        if success:
            logger.info("Admin notification sent successfully")
        else:
            logger.warning("Failed to send admin notification after retries")

        return success

    except Exception as e:
        logger.exception("Failed to send admin notification: %s", e)
        return False


async def notify_admin(message: str) -> bool:
    """Send notification to admin asynchronously with retry logic"""
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

        # Use retry logic for Telegram API calls
        success = await _send_with_retry(url, payload, max_retries=2)

        if success:
            logger.info("Admin notification sent successfully")
        else:
            logger.warning("Failed to send admin notification after retries")

        return success

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


async def notify_admin_telegram(bot, message: str) -> bool:
    """Send notification to admin via Telegram bot (legacy function name)"""
    return await notify_admin(message)