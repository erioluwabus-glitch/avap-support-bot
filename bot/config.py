"""
Configuration for the AVAP Support Bot.

Loads environment variables, sets up logging, and defines constants.
"""

import os
import re
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("avap_bot")

# Environment / constants
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) if os.getenv("ADMIN_ID") else None
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")  # e.g. https://avap-support-bot.onrender.com
TZ = os.getenv("TZ", "Africa/Lagos")

# Optional integrations & groups
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_STUDENT_TAG_ID = os.getenv("SYSTEME_VERIFIED_STUDENT_TAG_ID")

VERIFICATION_GROUP_ID = int(os.getenv("VERIFICATION_GROUP_ID")) if os.getenv("VERIFICATION_GROUP_ID") else None
ASSIGNMENTS_GROUP_ID = int(os.getenv("ASSIGNMENTS_GROUP_ID")) if os.getenv("ASSIGNMENTS_GROUP_ID") else None
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID")) if os.getenv("SUPPORT_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID")) if os.getenv("QUESTIONS_GROUP_ID") else None

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set in environment variables. Exiting.")
    raise SystemExit("BOT_TOKEN not set")

# Note: WEBHOOK_BASE_URL is not critical for polling mode, so we don't exit if it's not set.
# The webhook-specific logic will handle this.
WEBHOOK_URL = f"{WEBHOOK_BASE_URL.rstrip('/')}/webhook/{BOT_TOKEN}" if WEBHOOK_BASE_URL else None

# Sqlite DB
DB_PATH = os.getenv("DB_PATH", "avap_bot.db")

# Regex validators
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+\d{10,15}$")

# Optional Google Sheets availability check
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
