"""
Main entry point for the AVAP Support Bot.
"""
import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application
from fastapi import FastAPI, Request, Response
import uvicorn

from avap_bot.utils.logging_config import setup_logging
from avap_bot.services.supabase_service import init_supabase
from avap_bot.handlers import register_all

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

# Register all handlers
register_all(bot_app)

# --- Webhook and Health Check ---
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}

async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error in webhook: {e}", exc_info=True)
        return Response(status_code=500)

app.post("/webhook")(telegram_webhook)
app.get("/health")(health_check)


async def initialize_services():
    """Initializes services and sets up the bot."""
    logger.info("Initializing services...")
    try:
        # Initialize Supabase
        init_supabase()
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

# --- FastAPI event handlers ---
@app.on_event("startup")
async def on_startup():
    """Actions to perform on application startup."""
    await initialize_services()
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Setting webhook to {webhook_url}")
        await bot_app.bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
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