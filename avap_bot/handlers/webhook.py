"""
Webhook handler for Telegram bot updates and health checks.
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Create router for webhook endpoints
router = APIRouter()

@router.post("/webhook")
async def webhook_handler(request: Request) -> JSONResponse:
    """
    Handle incoming Telegram webhook updates.
    """
    try:
        # Get the update data
        update_data = await request.json()
        logger.info("Received webhook update: %s", update_data.get("update_id"))
        
        # Process the update through the bot
        from avap_bot.bot import application
        await application.process_update(update_data)
        
        return JSONResponse(content={"status": "ok"})
    
    except Exception as e:
        logger.error("Error processing webhook: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for monitoring.
    """
    try:
        # Basic health check
        return JSONResponse(content={
            "status": "healthy",
            "service": "avap-support-bot",
            "version": "1.0.0"
        })
    
    except Exception as e:
        logger.error("Health check failed: %s", e)
        raise HTTPException(status_code=500, detail="Health check failed")

def register_handlers(application):
    """
    Register webhook handlers with the FastAPI application.
    This function is called by the handler registration system.
    """
    # The webhook endpoints are already registered with the router
    # and will be included when the router is added to the main app
    pass
