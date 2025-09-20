"""
Runs the bot in polling mode for local development and testing.
"""
import asyncio
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.config import BOT_TOKEN, logger
from bot.database import init_db
from bot.main import register_handlers
from telegram.ext import Application

async def main():
    """Initializes and runs the bot in polling mode."""
    logger.info("Starting bot in polling mode...")

    # Initialize database
    init_db()

    # Build the application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register all the handlers
    register_handlers(application)

    logger.info("Bot initialized. Starting polling...")

    # Start the bot
    await application.initialize()
    await application.start()

    # Run the bot until the user presses Ctrl-C
    # We use a Future that never completes to keep the event loop running.
    await asyncio.Future()

    # Stop the bot
    await application.stop()
    await application.shutdown()
    logger.info("Bot shut down gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {e}")
