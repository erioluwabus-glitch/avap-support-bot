"""
Main entry point for the AVAP Support Bot.
"""
import os
import logging
import asyncio
import time
from telegram import Update
from telegram.ext import Application
from fastapi import FastAPI, Request, Response
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from avap_bot.utils.logging_config import setup_logging
from avap_bot.services.supabase_service import init_supabase
from avap_bot.handlers import register_all
from avap_bot.handlers.tips import schedule_daily_tips
from avap_bot.utils.cancel_registry import CancelRegistry
from avap_bot.features.cancel_feature import register_cancel_handlers, register_test_handlers

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# Create the FastAPI app
app = FastAPI()

# Create the Telegram bot application
bot_app = Application.builder().token(BOT_TOKEN).build()

# Initialize cancel registry and store in bot data
cancel_registry = CancelRegistry()
bot_app.bot_data['cancel_registry'] = cancel_registry

# Register all handlers
register_all(bot_app)

# Register cancel handlers
register_cancel_handlers(bot_app)

# Register test handlers (development only)
register_test_handlers(bot_app)

# Create scheduler for daily tips
scheduler = AsyncIOScheduler()
scheduler.start()
logger.debug("Scheduler started for daily tips")

# --- Webhook and Health Check ---
async def keep_alive_check(bot):
    """Ultra-aggressive keep-alive check to prevent Render timeouts."""
    try:
        # Perform database check to keep connection alive
        from avap_bot.services.supabase_service import get_supabase
        client = get_supabase()
        client.table("verified_users").select("id").limit(1).execute()

        # Make multiple HTTP requests to simulate heavy activity
        import httpx
        import asyncio
        
        # Make several concurrent requests to show activity
        async def make_request(url, timeout=2.0):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=timeout)
                    return response.status_code
            except:
                return None
        
        # Fire multiple requests concurrently
        tasks = [
            make_request("http://localhost:8080/health"),
            make_request("http://localhost:8080/health"),
            make_request("http://localhost:8080/health")
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful_requests = sum(1 for r in results if r == 200)
        
        if successful_requests > 0:
            logger.debug(f"Keep-alive: {successful_requests}/3 requests successful")
        else:
            logger.debug("Keep-alive: All requests failed (expected during startup)")

    except Exception as e:
        logger.debug(f"Keep-alive check failed: {e}")
        # Try to reinitialize if there are issues
        try:
            from avap_bot.services.supabase_service import init_supabase
            init_supabase()
            logger.debug("Reinitialized Supabase connection")
        except Exception as reinit_error:
            logger.debug(f"Failed to reinitialize Supabase: {reinit_error}")


async def ping_self():
    """Simple ping to keep the service alive."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.get("http://localhost:8080/ping", timeout=1.0)
    except:
        pass  # Silent fail to avoid log spam


async def health_check():
    """Comprehensive health check endpoint with keep-alive functionality."""
    try:
        # Check if Supabase is still connected
        from avap_bot.services.supabase_service import get_supabase
        client = get_supabase()
        client.table("verified_users").select("id").limit(1).execute()

        # Check if bot application is initialized
        if not bot_app or not hasattr(bot_app, 'bot'):
            raise RuntimeError("Bot application not initialized")

        # Check if scheduler is running
        if not scheduler or scheduler.state == 0:
            logger.warning("Scheduler may not be running properly")

        # Log health check activity to prevent timeouts (less verbose)
        logger.debug("Health check passed - Bot is alive and responsive")

        return {
            "status": "healthy",
            "service": "avap-support-bot",
            "version": "2.0.0",
            "timestamp": time.time(),
            "uptime": "active",
            "supabase_connected": True,
            "bot_initialized": True,
            "scheduler_running": scheduler.running if scheduler else False,
            "keep_alive": "active"
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        logger.debug(f"Received webhook request to: {request.url.path}")
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        logger.debug("Successfully processed webhook update")
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error in webhook: {e}", exc_info=True)
        return Response(status_code=500)

# Handle webhook with bot token in path (Telegram standard format)
app.post("/webhook/{bot_token}")(telegram_webhook)
app.get("/health")(health_check)

# Simple ping endpoint for keep-alive
@app.get("/ping")
async def ping():
    """Simple ping endpoint for keep-alive."""
    return {"status": "pong", "timestamp": time.time()}

# Root endpoint for basic health check
@app.get("/")
async def root():
    """Root endpoint."""
    return {"status": "ok", "service": "avap-support-bot"}


async def initialize_services():
    """Initializes services and sets up the bot."""
    logger.debug("Initializing services...")
    try:
        # Initialize Supabase
        init_supabase()

        # Initialize the Telegram Application
        logger.debug("Initializing Telegram Application...")
        await bot_app.initialize()
        logger.debug("Telegram Application initialized successfully")

        # Schedule daily tips
        await schedule_daily_tips(bot_app.bot, scheduler)

        # Schedule ultra-aggressive keep-alive health checks every 30 seconds
        scheduler.add_job(
            keep_alive_check,
            'interval',
            seconds=30,
            args=[bot_app.bot],
            id='keep_alive',
            replace_existing=True
        )
        logger.debug("Ultra-aggressive keep-alive health checks scheduled every 30 seconds")
        
        # Schedule simple ping every 15 seconds
        scheduler.add_job(
            ping_self,
            'interval',
            seconds=15,
            id='ping_self',
            replace_existing=True
        )
        logger.debug("Simple ping scheduled every 15 seconds")

        logger.info("Services initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize services: {e}", exc_info=True)
        # Exit if services fail to initialize
        raise

async def main_polling():
    """Main function to start the bot in polling mode."""
    await initialize_services()
    logger.info("Starting bot in polling mode for local development...")
    await bot_app.run_polling(allowed_updates=["message", "callback_query"])

# Background task to continuously ping health endpoint
async def background_keepalive():
    """Background task that continuously pings the health endpoint."""
    import asyncio
    import httpx
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                # Ping multiple endpoints to show activity
                await asyncio.gather(
                    client.get("http://localhost:8080/ping", timeout=1.0),
                    client.get("http://localhost:8080/", timeout=1.0),
                    client.get("http://localhost:8080/health", timeout=1.0),
                    return_exceptions=True
                )
        except:
            pass  # Silent fail
        await asyncio.sleep(5)  # Ping every 5 seconds


# --- FastAPI event handlers ---
@app.on_event("startup")
async def on_startup():
    """Actions to perform on application startup."""
    # Initialize services first (including Telegram Application)
    await initialize_services()

    # Start background keepalive task
    asyncio.create_task(background_keepalive())
    logger.info("Background keepalive task started")

    # Set webhook URL - construct proper Telegram webhook URL
    webhook_base = os.getenv("WEBHOOK_URL")
    bot_token = os.getenv("BOT_TOKEN")

    if webhook_base and bot_token:
        # Construct proper webhook URL: https://your-app.com/webhook/BOT_TOKEN
        webhook_url = f"{webhook_base.rstrip('/')}/webhook/{bot_token}"
        logger.info(f"Setting webhook with WEBHOOK_URL: {webhook_base}")
        logger.info(f"Setting webhook with BOT_TOKEN: {bot_token[:20]}...")  # Only log first 20 chars for security
        logger.info(f"Setting webhook to: {webhook_url}")
        await bot_app.bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        logger.info("Webhook set successfully")
    elif webhook_base:
        logger.warning("WEBHOOK_URL set but BOT_TOKEN missing. Webhook not configured.")
    else:
        logger.warning("WEBHOOK_URL not set. Bot will not receive updates unless webhook is set manually.")

@app.on_event("shutdown")
async def on_shutdown():
    """Actions to perform on application shutdown."""
    logger.info("Shutting down...")
    if os.getenv("WEBHOOK_URL"):
        await bot_app.bot.delete_webhook()

if __name__ == "__main__":
    # This block is for local development with polling
    # To run: python -m avap_bot.bot
    try:
        asyncio.run(main_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}", exc_info=True)