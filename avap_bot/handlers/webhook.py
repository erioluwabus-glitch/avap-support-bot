"""
Webhook handler for Telegram bot updates and health checks.
"""

import asyncio
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
    Health check endpoint for monitoring and keeping service active.
    """
    try:
        # Do some work to keep the service active
        import time
        start_time = time.time()
        
        # Simulate some work
        await asyncio.sleep(0.1)
        
        # Check if Supabase is accessible
        try:
            from avap_bot.services.supabase_service import get_supabase
            client = get_supabase()
            # Simple query to keep database connection active
            client.table("verified_users").select("id").limit(1).execute()
        except Exception as e:
            logger.warning("Supabase health check failed: %s", e)
        
        processing_time = time.time() - start_time
        
        return JSONResponse(content={
            "status": "healthy",
            "service": "avap-support-bot",
            "version": "2.0.0",
            "timestamp": time.time(),
            "processing_time_ms": round(processing_time * 1000, 2),
            "keep_alive": "active"
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
