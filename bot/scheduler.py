"""
Handles scheduled tasks for the bot using APScheduler.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

from .config import TZ, logger
from .database import get_all_verified_users
from .models import MAIN_MENU_MARKUP

# Initialize the scheduler with the specified timezone
scheduler = AsyncIOScheduler(timezone=TZ)

async def sunday_reminder_job(application: Application):
    """
    Sends a weekly reminder to all verified students on Sunday evenings.
    """
    logger.info("Running Sunday reminder job...")
    try:
        verified_users = await get_all_verified_users()
        if not verified_users:
            logger.info("No verified users found to send reminders to.")
            return

        for user in verified_users:
            telegram_id, name = user['telegram_id'], user['name']
            message = (
                f"👋 Hello {name}!\n\n"
                "Just a friendly Sunday reminder to keep up the great work!\n\n"
                "✅ Check your progress with the 'Check Status' button.\n"
                "🎉 Don't forget to share your small wins with the community!\n\n"
                "Have a productive week ahead!"
            )
            try:
                await application.bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    reply_markup=MAIN_MENU_MARKUP
                )
            except Exception:
                logger.warning(f"Failed to send reminder to user {telegram_id}. They may have blocked the bot.", exc_info=True)

        logger.info(f"Successfully sent reminders to {len(verified_users)} users.")

    except Exception:
        logger.exception("An error occurred during the sunday_reminder_job.")


def setup_scheduler(application: Application):
    """
    Adds all jobs to the scheduler and starts it.
    """
    try:
        # Schedule the reminder job to run every Sunday at 6:00 PM in the specified timezone
        scheduler.add_job(
            lambda: sunday_reminder_job(application),
            CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=TZ),
            id="sunday_reminder",
            name="Weekly Sunday Reminder"
        )
        scheduler.start()
        logger.info("Scheduler started successfully with the reminder job scheduled.")
    except Exception:
        logger.exception("Failed to start the scheduler.")
