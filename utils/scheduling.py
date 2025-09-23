"""
Scheduling utilities for APScheduler integration.
Handles job scheduling for daily tips and other periodic tasks.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import timezone, timedelta
import os

logger = logging.getLogger(__name__)

# Timezone configuration
TIMEZONE = os.getenv("TIMEZONE", "Africa/Lagos")
DAILY_TIP_HOUR = int(os.getenv("DAILY_TIP_HOUR", "8"))
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

def get_scheduler() -> AsyncIOScheduler:
    """Get configured APScheduler instance with persistent SQLAlchemy job store."""
    db_url = f"sqlite:///{DB_PATH}"
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
    return AsyncIOScheduler(jobstores=jobstores, timezone=TIMEZONE)

def schedule_daily_job(scheduler: AsyncIOScheduler, job_func, *args, **kwargs):
    """
    Schedule a daily job at the configured hour.
    
    Args:
        scheduler: APScheduler instance
        job_func: Function to execute
        *args: Arguments for the job function
        **kwargs: Keyword arguments for the job function
    """
    try:
        scheduler.add_job(
            job_func,
            trigger=CronTrigger(hour=DAILY_TIP_HOUR, minute=0, timezone=TIMEZONE),
            args=args,
            kwargs=kwargs,
            id="daily_tips",
            name="Daily Tips Job",
            replace_existing=True,
            misfire_grace_time=300
        )
        logger.info(f"Scheduled daily tips job for {DAILY_TIP_HOUR}:00 {TIMEZONE} with persistence")
    except Exception as e:
        logger.exception(f"Failed to schedule daily job: {e}")

def schedule_reminder_job(scheduler: AsyncIOScheduler, job_func, *args, **kwargs):
    """
    Schedule a weekly reminder job for Sundays.
    
    Args:
        scheduler: APScheduler instance
        job_func: Function to execute
        *args: Arguments for the job function
        **kwargs: Keyword arguments for the job function
    """
    try:
        scheduler.add_job(
            job_func,
            trigger=CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=TIMEZONE),
            args=args,
            kwargs=kwargs,
            id="sunday_reminder",
            name="Sunday Reminder Job",
            replace_existing=True
        )
        logger.info(f"Scheduled Sunday reminder job for 18:00 {TIMEZONE}")
    except Exception as e:
        logger.exception(f"Failed to schedule reminder job: {e}")

def schedule_faq_check_job(scheduler: AsyncIOScheduler, job_func, *args, **kwargs):
    """
    Schedule a job to check for unanswered questions.
    
    Args:
        scheduler: APScheduler instance
        job_func: Function to execute
        *args: Arguments for the job function
        **kwargs: Keyword arguments for the job function
    """
    try:
        # Check every hour for unanswered questions
        scheduler.add_job(
            job_func,
            trigger=CronTrigger(minute=0, timezone=TIMEZONE),
            args=args,
            kwargs=kwargs,
            id="faq_check",
            name="FAQ Check Job",
            replace_existing=True
        )
        logger.info("Scheduled FAQ check job to run every hour")
    except Exception as e:
        logger.exception(f"Failed to schedule FAQ check job: {e}")
