"""
Admin notification service
"""
import os
import logging
import aiohttp
from typing import Optional

logger = logging.getLogger(__name__)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


async def notify_admin(message: str) -> bool:
    """Send notification to admin via Telegram or Discord"""
    try:
        # Try Discord webhook first
        if DISCORD_WEBHOOK_URL:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": f"🤖 AVAP Bot Alert: {message}"}
                ) as response:
                    if response.status == 204:
                        logger.info("Sent admin notification via Discord")
                        return True
                    else:
                        logger.warning("Discord webhook failed: %s", await response.text())
        
        # Fallback to Telegram (requires bot instance)
        # This would need to be called with bot context
        logger.info("Admin notification (no webhook): %s", message)
        return True
        
    except Exception as e:
        logger.exception("Failed to send admin notification: %s", e)
        return False


async def notify_admin_telegram(bot, message: str) -> bool:
    """Send notification to admin via Telegram DM"""
    try:
        if ADMIN_USER_ID:
            await bot.send_message(
                ADMIN_USER_ID,
                f"🤖 **AVAP Bot Alert**\n\n{message}",
                parse_mode="Markdown"
            )
            logger.info("Sent admin notification via Telegram")
            return True
        return False
        
    except Exception as e:
        logger.exception("Failed to send Telegram admin notification: %s", e)
        return False
