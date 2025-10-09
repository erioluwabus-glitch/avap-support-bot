"""
Robust HTTP client with 429 rate limiting handling
"""
import time
import random
import requests
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def request_with_429_handling(method: str, url: str, headers: Optional[Dict[str, str]] = None, **kwargs) -> requests.Response:
    """
    Make HTTP request with robust 429 handling including Retry-After and exponential backoff.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        headers: Request headers
        **kwargs: Additional requests parameters
        
    Returns:
        requests.Response object
    """
    max_attempts = 6
    base_delay = 1.0
    max_delay = 300  # 5 minutes max delay
    
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            
            # If not 429, return immediately
            if resp.status_code != 429:
                return resp
            
            # Handle 429 - check Retry-After header
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    # Retry-After can be seconds or HTTP date
                    wait = int(retry_after)
                except ValueError:
                    # If it's an HTTP date, fallback to exponential backoff
                    wait = base_delay * (2 ** (attempt - 1))
            else:
                # No Retry-After header - use exponential backoff with jitter
                wait = base_delay * (2 ** (attempt - 1))
                # Add jitter +/- 20% to prevent thundering herd
                jitter = random.uniform(-0.2, 0.2) * wait
                wait = max(0.5, wait + jitter)
            
            # Cap the wait time
            wait = min(wait, max_delay)
            
            logger.warning("Received 429; attempt %d. Waiting %.1fs before retry.", attempt, wait)
            logger.warning("Request: %s %s", method, url)
            logger.warning("Response headers: %s", dict(resp.headers))
            
            # If this is the last attempt, return the 429 response
            if attempt == max_attempts:
                logger.error("Exhausted retries for %s %s", method, url)
                return resp
            
            time.sleep(wait)
            
        except requests.RequestException as e:
            logger.error("Request failed on attempt %d: %s", attempt, e)
            if attempt == max_attempts:
                raise
            # Wait before retry on network errors too
            wait = base_delay * (2 ** (attempt - 1))
            time.sleep(min(wait, 30))  # Cap network error retry delay
    
    # This should never be reached, but just in case
    return resp

def get_webhook_info(bot_token: str) -> Dict[str, Any]:
    """
    Get webhook info from Telegram API with 429 handling.
    
    Args:
        bot_token: Telegram bot token
        
    Returns:
        Dict with webhook info or error
    """
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    
    try:
        resp = request_with_429_handling("GET", url)
        return resp.json()
    except Exception as e:
        logger.error("Failed to get webhook info: %s", e)
        return {"ok": False, "error": str(e)}

def set_webhook_if_needed(bot_token: str, webhook_url: str) -> bool:
    """
    Set webhook only if needed (check current webhook first).
    
    Args:
        bot_token: Telegram bot token
        webhook_url: Desired webhook URL
        
    Returns:
        True if webhook was set or already correct, False on error
    """
    try:
        # First, get current webhook info
        info = get_webhook_info(bot_token)
        if not info.get("ok"):
            logger.warning("getWebhookInfo failed: %s", info)
            return False
        
        current_url = info["result"].get("url", "")
        if current_url == webhook_url:
            logger.info("Webhook already set and matches URL. Skipping setWebhook.")
            return True
        
        # Webhook URL is different or not set - update it
        logger.info("Setting webhook to %s", webhook_url)
        url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        data = {"url": webhook_url, "allowed_updates": ["message", "callback_query"]}
        
        resp = request_with_429_handling("POST", url, data=data)
        result = resp.json()
        
        if result.get("ok"):
            logger.info("Webhook set successfully")
            return True
        else:
            logger.error("Failed to set webhook: %s", result)
            return False
            
    except Exception as e:
        logger.error("Error setting webhook: %s", e)
        return False
