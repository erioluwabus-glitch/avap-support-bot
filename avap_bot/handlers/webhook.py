"""
Webhook handlers for Telegram updates
"""
import logging
import asyncio
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)


async def webhook_handler(request: Request, bot_token: str) -> Dict[str, str]:
    """Handle incoming webhook updates"""
    try:
        # Verify webhook token
        expected_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if expected_token != bot_token:
            logger.warning("Invalid webhook token")
            raise HTTPException(status_code=403, detail="Forbidden")
        
        # Get update data
        update_data = await request.json()
        
        # Process update asynchronously
        asyncio.create_task(_process_update(update_data))
        
        # Return immediately to prevent Telegram retries
        return {"status": "ok"}
        
    except Exception as e:
        logger.exception("Webhook handler error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


async def _process_update(update_data: Dict[str, Any]):
    """Process Telegram update in background"""
    try:
        # This would be called with the bot application instance
        # For now, just log the update
        logger.info("Processing update: %s", update_data.get("update_id"))
        
        # In real implementation, you'd call:
        # await application.process_update(Update.de_json(update_data, bot))
        
    except Exception as e:
        logger.exception("Failed to process update: %s", e)


async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {"status": "ok", "service": "avap-bot"}


def register_handlers(application):
    """Register webhook handlers with the application"""
    # Webhook handlers don't need to register with the application
    # They are handled by FastAPI endpoints
    pass
