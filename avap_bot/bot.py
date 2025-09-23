# bot.py
"""
AVAP Support Bot - webhook-ready single-file application.

Features implemented:
1. Admin: /add_student (pre-register)
2. Student verification (/start flow + Verify Now button)
3. Admin: /verify_student [email]
4. Admin: /remove_student [telegram_id]
5. Assignment submission (modules 1-12) -> forwarded to ASSIGNMENTS_GROUP_ID
6. Grading (inline in assignments group or manual /grade)
7. Share small win (share_win)
8. Ask a question -> forwarded to QUESTIONS_GROUP_ID, admins answer via inline
9. Check status (student progress)
10. Join request handling (approve only if verified)
11. Sunday reminder (APS scheduler)
Webhook endpoints & health endpoints included.
"""

import os
import re
import json
import uuid
import logging
import hashlib
# Removed sqlite3; PostgreSQL async helpers are used via utils.db_async
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

import requests
import aiohttp
from aiohttp import ClientTimeout
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ChatJoinRequest,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)
from telegram.constants import ParseMode, ChatType

# Import new features
from features import (
    daily_tips,
    faq_ai_helper,
    broadcast,
    multilanguage,
    voice_transcription,
    group_matching
)

# Translation utilities
from ..utils.db_access import get_user_language
from ..utils.translator import translate
from ..utils.db_async import init_async_db, close_async_db, db_execute, db_fetchone, db_fetchall
# Backup dependencies
import base64
from io import BytesIO
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
except Exception:
    build = None
    MediaIoBaseUpload = None

# Optional Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except Exception:
    GSPREAD_AVAILABLE = False

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("avap_bot")

# Environment variables - exact names as specified
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0")) if os.getenv("ADMIN_USER_ID") else None
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SYSTEME_IO_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_STUDENT_TAG_ID = os.getenv("SYSTEME_VERIFIED_STUDENT_TAG_ID")
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0")) if os.getenv("SUPPORT_GROUP_ID") else None
ASSIGNMENTS_GROUP_ID = int(os.getenv("ASSIGNMENTS_GROUP_ID", "0")) if os.getenv("ASSIGNMENTS_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0")) if os.getenv("QUESTIONS_GROUP_ID") else None
VERIFICATION_GROUP_ID = int(os.getenv("VERIFICATION_GROUP_ID", "0")) if os.getenv("VERIFICATION_GROUP_ID") else None
# Removed DB_PATH; using DATABASE_URL via utils.db_async
ACHIEVER_MODULES = int(os.getenv("ACHIEVER_MODULES", "6"))
ACHIEVER_WINS = int(os.getenv("ACHIEVER_WING", "3"))
TIMEZONE = os.getenv("TIMEZONE", "Africa/Lagos")

# New feature environment variables
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHISPER_ENDPOINT = os.getenv("WHISPER_ENDPOINT")
UNANSWER_TIMEOUT_HOURS = int(os.getenv("UNANSWER_TIMEOUT_HOURS", "6"))
DAILY_TIP_HOUR = int(os.getenv("DAILY_TIP_HOUR", "8"))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
DAILY_TIPS_TO_DMS = os.getenv("DAILY_TIPS_TO_DMS", "false").lower() == "true"
MATCH_SIZE = int(os.getenv("MATCH_SIZE", "2"))

# Systeme.io configuration
SYSTEME_BASE_URL = "https://api.systeme.io/api"
AVAP_ACTIVATE_LINK = "https://bit.ly/avm-activate"
SYSTEME_KEEP_CONTACT_ON_REMOVE = os.getenv("SYSTEME_KEEP_CONTACT_ON_REMOVE", "False") == "True"
SYSTEME_ACHIEVER_TAG_ID = os.getenv("SYSTEME_ACHIEVER_TAG_ID")

# Validate required environment variables
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set in environment variables. Exiting.")
    raise SystemExit("BOT_TOKEN not set")

if not RENDER_EXTERNAL_URL:
    logger.critical("RENDER_EXTERNAL_URL not set. Exiting.")
    raise SystemExit("RENDER_EXTERNAL_URL not set")

if not ADMIN_USER_ID:
    logger.critical("ADMIN_USER_ID not set. Exiting.")
    raise SystemExit("ADMIN_USER_ID not set")

# Webhook URL - handle both cases where RENDER_EXTERNAL_URL includes or excludes https://
base_url = RENDER_EXTERNAL_URL.strip('/')
if not base_url.startswith('https://'):
    base_url = f"https://{base_url}"
webhook_url = f"{base_url}/webhook/{BOT_TOKEN}"
masked_token = (BOT_TOKEN[:6] + '…') if BOT_TOKEN and len(BOT_TOKEN) > 6 else '***'

# Conversation states
(
    ADD_STUDENT_NAME,
    ADD_STUDENT_PHONE,
    ADD_STUDENT_EMAIL,
    VERIFY_NAME,
    VERIFY_PHONE,
    VERIFY_EMAIL,
    SUBMIT_MODULE,
    SUBMIT_MEDIA_TYPE,
    SUBMIT_MEDIA_UPLOAD,
    WIN_TYPE,
    WIN_UPLOAD,
    ASK_QUESTION,
    ANSWER_QUESTION,
    GRADE_USERNAME,
    GRADE_MODULE,
    GRADING_COMMENT,
    REMOVE_CONFIRM,
    REMOVE_REASON,
) = range(100, 118)

# Grading conversation states (separate from main conversation states)
class GradingStates:
    GRADE_SCORE = 200
    GRADE_COMMENT_CHOICE = 201
    GRADE_COMMENT_TYPE = 202
    GRADING_COMMENT = 203

# Regex validators
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+\d{10,15}$")

# FastAPI app
app = FastAPI()

# Optional rate limiting (slowapi)
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
except Exception:
    limiter = None

# Telegram Application placeholder (will be initialized on startup)
telegram_app: Optional[Application] = None

# Scheduler for weekly reminders
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# Google Sheets client (optional)
gs_client = None
gs_sheet = None

# Removed SQLite; using PostgreSQL via utils.db_async helpers

# Google Sheets helper (optional)
def init_gsheets():
    global gs_client, gs_sheet
    if not GSPREAD_AVAILABLE:
        logger.info("Google Sheets library not installed; skipping Sheets integration.")
        return
    if not GOOGLE_SHEET_ID:
        logger.warning("Google Sheets not configured - missing GOOGLE_SHEET_ID; skipping sync")
        return
    if not GOOGLE_CREDENTIALS_JSON:
        logger.warning("Google Sheets not configured - missing GOOGLE_CREDENTIALS_JSON; skipping sync")
        return
    try:
        # Write credentials to file if provided as JSON string
        creds_value = GOOGLE_CREDENTIALS_JSON
        # Support base64-encoded JSON
        try:
            if not creds_value.strip().startswith('{'):
                import base64
                decoded = base64.b64decode(creds_value).decode('utf-8')
                creds_value = decoded
        except Exception:
            pass
        if creds_value.strip().startswith('{'):
            creds_dict = json.loads(creds_value)
        else:
            # Assume it's a file path
            with open(creds_value, 'r') as f:
                creds_dict = json.load(f)
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gs_client = gspread.authorize(creds)
        gs_sheet = gs_client.open_by_key(GOOGLE_SHEET_ID)
        logger.info("Google Sheets connected")
    except Exception as e:
        logger.exception("Failed to initialize Google Sheets: %s", e)
        gs_client = None
        gs_sheet = None

# Ensure default worksheets exist with headers
def ensure_default_worksheets():
    try:
        if not gs_sheet:
            return
        required = {
            "Verifications": [
                "timestamp", "telegram_id", "name", "email", "phone", "systeme_contact_id", "status"
            ],
            "Submissions": [
                "timestamp", "telegram_id", "module", "content_type", "content", "status", "grade", "comment"
            ],
            "Wins": [
                "timestamp", "telegram_id", "type", "content"
            ],
            "FAQ": [
                "question", "answer", "created_at"
            ],
            "VoiceTranscriptions": [
                "username", "telegram_id", "transcription", "created_at"
            ]
        }
        for title, headers in required.items():
            try:
                sheet = gs_sheet.worksheet(title)
            except Exception:
                sheet = gs_sheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
                sheet.append_row(headers)
    except Exception as e:
        logger.exception(f"Failed ensuring default worksheets: {e}")

# Unified Google Sheets sync helper
async def sync_to_sheets(worksheet_name: str, action: str, data: dict, search_col: int = 1, update_cols: list = None, row_data: list = None) -> bool:
    """Unified Sheets sync: append or upsert by search_col.
    - action: "append" or "update"
    - data: for update requires data['search_value'] to match in column search_col
    - update_cols: list of (col_idx, value) pairs to update in the found row(s)
    - row_data: optional explicit row values for append
    """
    try:
        if not gs_sheet:
            logger.warning("Google Sheets not configured - skipping sync")
            return False
        try:
            sheet = gs_sheet.worksheet(worksheet_name)
        except Exception:
            # Create sheet if it does not exist; headers will be the caller's responsibility
            sheet = gs_sheet.add_worksheet(worksheet_name, rows=200, cols=20)

        if action == "append":
            if row_data is None:
                # Best-effort generic append from a dict
                row_data = [data.get(k, '') for k in ['name', 'email', 'phone', 'telegram_id', 'status', 'hash', 'created_at']]
            sheet.append_row(row_data)
            return True
        elif action == "update":
            search_value = data.get('search_value')
            if not search_value:
                logger.warning("sync_to_sheets update called without search_value")
                return False
            cells = sheet.findall(str(search_value)) if search_col is None else sheet.findall(str(search_value), in_column=search_col)
            if not cells:
                logger.warning(f"No row found in {worksheet_name} for {search_value}")
                return False
            for cell in cells:
                row_idx = cell.row
                if update_cols:
                    for col_idx, value in update_cols:
                        sheet.update_cell(row_idx, col_idx, value)
            return True
        else:
            logger.warning(f"Unknown action for sync_to_sheets: {action}")
            return False
    except Exception as e:
        logger.exception(f"Sheets sync failed for {worksheet_name}: {e}")
        return False

# Async Systeme.io helpers with comprehensive error handling and retry logic
async def systeme_api_request(method: str, endpoint: str, json_data: dict = None, params: dict = None, max_retries: int = 3) -> dict:
    """Unified async API caller with retry logic and exponential backoff."""
    if not SYSTEME_IO_API_KEY:
        logger.warning("Systeme.io API key not set - skipping API request")
        return None
    
    headers = {"X-API-Key": SYSTEME_IO_API_KEY}
    # Only set JSON content type for methods that send a body
    if method.upper() in {"POST", "PUT", "PATCH"}:
        headers["Content-Type"] = "application/json"
    url = f"{SYSTEME_BASE_URL}{endpoint}"
    timeout = ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(max_retries):
            try:
                async with session.request(method, url, headers=headers, json=json_data, params=params) as resp:
                    if resp.status == 401:
                        logger.error("Systeme.io API key is invalid or expired. Please check your SYSTEME_IO_API_KEY environment variable.")
                        return None
                    elif resp.status == 422:
                        # Validation or filter errors; log and retry with backoff a few times
                        try:
                            err_text = await resp.text()
                        except Exception:
                            err_text = ""
                        logger.warning(f"422 Validation error for {endpoint}: {err_text}")
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            await asyncio.sleep(wait_time)
                            continue
                        return None
                    elif resp.status == 429:  # Rate limit
                        if attempt < max_retries - 1:
                            wait_time = 60 * (2 ** attempt)  # Exponential backoff with 1 minute base
                            logger.warning(f"Rate limited. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error("Rate limit exceeded after all retries")
                            return None
                    
                    resp.raise_for_status()
                    # Safely handle non-JSON responses (e.g., 204 No Content or empty body)
                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    if "application/json" in content_type:
                        return await resp.json()
                    try:
                        text = await resp.text()
                        return {"ok": True, "status": resp.status, "text": text}
                    except Exception:
                        # For DELETE 204 and similar, return a simple success indicator
                        return {"ok": True, "status": resp.status}
            except aiohttp.ClientResponseError as e:
                if e.status == 429 and attempt < max_retries - 1:
                    wait_time = 60 * (2 ** attempt)
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}")
                    await asyncio.sleep(wait_time)
                    continue
                elif attempt == max_retries - 1:
                    logger.exception(f"Systeme.io API request failed after {max_retries} attempts: {e}")
                    return None
                else:
                    wait_time = 2 ** attempt
                    logger.warning(f"API request failed, retrying in {wait_time} seconds: {e}")
                    await asyncio.sleep(wait_time)
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.exception(f"Systeme.io API request failed after {max_retries} attempts: {e}")
                    return None
                else:
                    wait_time = 2 ** attempt
                    logger.warning(f"Unexpected error, retrying in {wait_time} seconds: {e}")
                    await asyncio.sleep(wait_time)
    return None

async def systeme_get_contact_by_email(email: str) -> dict:
    """Check if contact exists by email using Systeme.io filter API."""
    params = {"email": email}
    response = await systeme_api_request("GET", "/contacts", params=params)
    # Some Systeme.io responses may return a list under 'items' or top-level list
    if not response:
        return None
    items = None
    if isinstance(response, dict):
        items = response.get("items") or response.get("data")
    elif isinstance(response, list):
        items = response
    if items and len(items) > 0:
        return items[0]
    return None

async def systeme_create_contact_with_retry(first_name: str, last_name: str, email: str, phone: str) -> str:
    """Create contact async with retry logic."""
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone_number": phone
    }
    response = await systeme_api_request("POST", "/contacts", json_data=payload)
    return response.get("id") if response else None

async def systeme_update_contact(contact_id: str, first_name: str, last_name: str, phone: str):
    """Update contact fields if needed (PUT to avoid 415 on some endpoints)."""
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone
    }
    await systeme_api_request("PUT", f"/contacts/{contact_id}", json_data=payload)

async def systeme_add_and_verify_tag(contact_id: str) -> bool:
    """Add tag and verify it was applied successfully."""
    if not SYSTEME_VERIFIED_STUDENT_TAG_ID:
        logger.warning("No verified student tag ID configured")
        return False
    
    tag_id = int(SYSTEME_VERIFIED_STUDENT_TAG_ID)
    add_payload = {"tag_id": tag_id}
    
    # Add the tag (use POST to avoid 405 on some Systeme.io plans)
    add_response = await systeme_api_request("POST", f"/contacts/{contact_id}/tags", json_data=add_payload)
    if not add_response:
        logger.error(f"Failed to add tag {tag_id} to contact {contact_id}")
        return False
    
    # Verify the tag was added
    tags_response = await systeme_api_request("GET", f"/contacts/{contact_id}/tags")
    if tags_response:
        for tag in tags_response:
            if tag.get("id") == tag_id:
                logger.info(f"Successfully verified tag {tag_id} on contact {contact_id}")
                return True
    
    logger.warning(f"Tag {tag_id} was not found on contact {contact_id} after adding")
    return False

async def notify_admin_systeme_failure(name: str, email: str, error: str, contact_id: str = None):
    """Notify admin about Systeme.io integration failures."""
    if not ADMIN_USER_ID:
        return
    
    error_msg = f"🚨 Systeme.io Integration Failure\n\n"
    error_msg += f"Student: {name}\n"
    error_msg += f"Email: {email}\n"
    error_msg += f"Contact ID: {contact_id or 'N/A'}\n"
    error_msg += f"Error: {error}\n\n"
    error_msg += f"Please check the Systeme.io API key and try manual verification."
    
    try:
        await telegram_app.bot.send_message(chat_id=ADMIN_USER_ID, text=error_msg)
    except Exception as e:
        logger.exception(f"Failed to notify admin about Systeme.io failure: {e}")

async def remove_systeme_contact(contact_id: str) -> bool:
    """Remove Systeme.io contact with tags and handle free plan limitations."""
    if not contact_id or not SYSTEME_IO_API_KEY:
        return True
    
    try:
        # Remove all tags first
        tags_response = await systeme_api_request("GET", f"/contacts/{contact_id}/tags")
        if tags_response:
            for tag in tags_response:
                tag_id = tag.get("id")
                if tag_id:
                    await systeme_api_request("DELETE", f"/contacts/{contact_id}/tags/{tag_id}")
                    logger.info(f"Removed tag {tag_id} from contact {contact_id}")
        
        if SYSTEME_KEEP_CONTACT_ON_REMOVE:
            # Keep contact but notify admin for manual dismissal
            await notify_admin_manual_dismiss(contact_id)
            return True
        else:
            # Delete the contact entirely
            delete_response = await systeme_api_request("DELETE", f"/contacts/{contact_id}")
            return delete_response is not None
            
    except Exception as e:
        logger.exception(f"Failed to remove Systeme.io contact {contact_id}: {e}")
        return False

async def notify_admin_manual_dismiss(contact_id: str):
    """Notify admin that manual dismissal is needed in Systeme.io."""
    if not ADMIN_USER_ID:
        return
    
    message = f"⚠️ Manual Action Needed\n\n"
    message += f"Contact ID: {contact_id}\n"
    message += f"Action: Dismiss enrollment in Systeme.io dashboard\n"
    message += f"Reason: Contact kept due to SYSTEME_KEEP_CONTACT_ON_REMOVE setting"
    
    try:
        await telegram_app.bot.send_message(chat_id=ADMIN_USER_ID, text=message)
    except Exception as e:
        logger.exception(f"Failed to notify admin about manual dismissal: {e}")

async def tag_achiever_in_systeme(telegram_id: int) -> bool:
    """Tag student as achiever in Systeme.io."""
    if not SYSTEME_ACHIEVER_TAG_ID or not SYSTEME_IO_API_KEY:
        return True
    
    try:
        # Get contact ID from verified_users
        row = await db_fetchone(
            "SELECT systeme_contact_id FROM verified_users WHERE telegram_id = ? AND removed_at IS NULL",
            (telegram_id,)
        )
        if not row or not row[0]:
            logger.warning(f"No Systeme.io contact ID found for telegram_id {telegram_id}")
            return False
        contact_id = row[0]
        
        # Add achiever tag
        tag_id = int(SYSTEME_ACHIEVER_TAG_ID)
        add_payload = {"tag_id": tag_id}
        response = await systeme_api_request("POST", f"/contacts/{contact_id}/tags", json_data=add_payload)
        
        if response:
            logger.info(f"Successfully added achiever tag to contact {contact_id}")
            return True
        else:
            logger.warning(f"Failed to add achiever tag to contact {contact_id}")
            return False
            
    except Exception as e:
        logger.exception(f"Failed to tag achiever in Systeme.io: {e}")
        return False

# Legacy sync function for backward compatibility
def systeme_create_contact(first_name: str, last_name: str, email: str, phone: str) -> Optional[str]:
    """Legacy sync function - calls async version."""
    if not SYSTEME_IO_API_KEY:
        logger.warning("Systeme.io API key not set - skipping contact creation")
        return None
    
    try:
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            contact_id = loop.run_until_complete(systeme_create_contact_with_retry(first_name, last_name, email, phone))
            if contact_id and SYSTEME_VERIFIED_STUDENT_TAG_ID:
                loop.run_until_complete(systeme_add_and_verify_tag(contact_id))
            return contact_id
        finally:
            loop.close()
    except Exception as e:
        logger.exception("Legacy Systeme.io contact creation failed: %s", e)
        return None

# Utilities
def make_hash(name: str, email: str, phone: str) -> str:
    base = f"{name}{email}{phone}0"
    return hashlib.sha256(base.encode()).hexdigest()

async def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID and int(user_id) == int(ADMIN_USER_ID)

from ..utils.user_utils import user_verified_by_telegram_id

async def find_pending_by_hash(h: str):
    return await db_fetchone(
        "SELECT id, name, email, phone, status FROM pending_verifications WHERE hash = ?",
        (h,)
    )

# Main menu reply keyboard (permanently fixed below typing area)
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
    [KeyboardButton("📤 Submit Assignment"), KeyboardButton("🎉 Share Small Win")],
        [KeyboardButton("📊 Check Status"), KeyboardButton("❓ Ask a Question")]
    ], resize_keyboard=True, is_persistent=True)

# Grading helper functions
def score_keyboard(uuid: str) -> InlineKeyboardMarkup:
    """Generate score selection keyboard"""
    buttons = [
        [InlineKeyboardButton(str(i), callback_data=f"score_{i}_{uuid}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"score_{i}_{uuid}") for i in range(6, 11)]
    ]
    return InlineKeyboardMarkup(buttons)

def comment_choice_keyboard(uuid: str) -> InlineKeyboardMarkup:
    """Generate comment choice keyboard"""
    buttons = [
        [InlineKeyboardButton("Comment", callback_data=f"comment_yes_{uuid}"),
         InlineKeyboardButton("No Comment", callback_data=f"comment_no_{uuid}")]
    ]
    return InlineKeyboardMarkup(buttons)

def comment_type_keyboard(uuid: str) -> InlineKeyboardMarkup:
    """Generate comment type keyboard"""
    buttons = [
        [InlineKeyboardButton("Text", callback_data=f"comment_type_text_{uuid}"),
         InlineKeyboardButton("Audio", callback_data=f"comment_type_audio_{uuid}"),
         InlineKeyboardButton("Video", callback_data=f"comment_type_video_{uuid}")]
    ]
    return InlineKeyboardMarkup(buttons)

async def finalize_grading(update: Update, context: ContextTypes.DEFAULT_TYPE, comment: str = None):
    """Finalize grading process - save to DB, notify student, cleanup"""
    try:
        uuid = context.user_data.get('grading_uuid')
        score = context.user_data.get('grading_score')
        comment_type = context.user_data.get('comment_type', 'text')
        
        if not uuid or not score:
            logger.error("Missing grading data in finalize_grading")
            return
        
        # Save to database
        await db_execute(
            "UPDATE submissions SET score = ?, status = ?, graded_at = ? WHERE submission_id = ?",
            (int(score), "Graded", datetime.utcnow().isoformat(), uuid)
        )
        if comment:
            await db_execute(
                "UPDATE submissions SET comment = ?, comment_type = ? WHERE submission_id = ?",
                (comment, comment_type, uuid)
            )
        # Get student info
        row = await db_fetchone(
            "SELECT telegram_id, username FROM submissions WHERE submission_id = ?",
            (uuid,)
        )
        
        if row:
            student_tg, username = row
            # Notify student
            try:
                msg = f"Your submission has been graded!\nScore: {score}/10"
                if comment:
                    msg += f"\nComment: {comment}"
                await telegram_app.bot.send_message(chat_id=student_tg, text=msg)
            except Exception as e:
                logger.exception("Failed to notify student: %s", e)
        
        # Sheets: update grading info via unified helper
        try:
            updated = await sync_to_sheets(
                "Submissions",
                "update",
                {"search_value": uuid},
                search_col=1,
                update_cols=[(5, "Graded"), (9, int(score)), (10, comment or "")]
            )
            if not updated:
                await sync_to_sheets(
                    "Submissions",
                    "append",
                    {},
                    row_data=[uuid, username or "", student_tg if row else "", "", "Graded", "", "", "", int(score), comment or ""]
                )
        except Exception:
            logger.exception("Failed to update grading info in Sheets")

        # Cleanup
        context.user_data.pop('grading_uuid', None)
        context.user_data.pop('grading_score', None)
        context.user_data.pop('comment_type', None)
        context.user_data.pop('grading_expected', None)

        logger.info(f"Grading finalized for submission {uuid} with score {score}")

    except Exception as e:
        logger.exception("Error in finalize_grading: %s", e)

# ----- Handlers -----

# Helper to send translated text based on user language
async def reply_translated(update: Update, text: str, reply_markup=None):
    try:
        user_id = update.effective_user.id if update.effective_user else 0
        target_lang = await get_user_language(user_id)
    except Exception:
        target_lang = DEFAULT_LANGUAGE
    try:
        out_text = translate(text, target_lang)
    except Exception:
        out_text = text
    await update.message.reply_text(out_text, reply_markup=reply_markup)

# /start handler - only in DM. If verified -> show main menu. If not -> start verification.
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != ChatType.PRIVATE:
            await reply_translated(update, "Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
            return
        
        user = update.effective_user
        if not user:
            return
            
        vid = await user_verified_by_telegram_id(user.id)
        if vid:
            # Verified -> show main menu
            await reply_translated(update, "✅ You're verified! Welcome to AVAP!", reply_markup=get_main_menu_keyboard())
            return
        
        # Not verified -> invite to verify
        verify_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]])
        await reply_translated(update, "Welcome! To use AVAP features you must verify your details.\nClick Verify Now to begin.", reply_markup=verify_btn)
    except Exception as e:
        logger.exception("Error in start_handler: %s", e)

# Callback query for main inline buttons
# Menu callback handler (for inline buttons) - DM ONLY
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if not query:
            return
        await query.answer()
        # Only work in DM
        if update.effective_chat.type != ChatType.PRIVATE:
            await query.answer("This feature only works in DM. Use /ask in group to ask questions.")
            return
        
        data = query.data
        if data == "submit":
            if not await user_verified_by_telegram_id(query.from_user.id):
                await query.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
                return
            await query.message.reply_text("Which module? (1-12):")
            return SUBMIT_MODULE
            
        elif data == "share_win":
            if not await user_verified_by_telegram_id(query.from_user.id):
                await query.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
            return
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Text", callback_data="win_text")],
                [InlineKeyboardButton("Image", callback_data="win_image")],
                [InlineKeyboardButton("Video", callback_data="win_video")]
            ])
            await query.message.reply_text("How would you like to share your win?", reply_markup=keyboard)
            return WIN_UPLOAD
            
        elif data == "status":
            if not await user_verified_by_telegram_id(query.from_user.id):
                await query.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
                return
            await check_status_handler(update, context)
            return
            
        elif data == "ask":
            if not await user_verified_by_telegram_id(query.from_user.id):
                await query.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
                return
            await query.message.reply_text("What's your question?")
            return ASK_QUESTION
            
    except Exception as e:
        logger.exception("Error in menu_callback: %s", e)

# Verify now callback for conversation entry
async def verify_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    await query.message.reply_text("Enter your full name:")
    return VERIFY_NAME

# Cancel command handler
async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation and return to main menu"""
    context.user_data.clear()
    try:
        if update and update.message:
            await update.message.reply_text("Operation cancelled.", reply_markup=get_main_menu_keyboard())
    except Exception:
        pass
    return ConversationHandler.END

# Reply keyboard button handlers
async def submit_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await reply_translated(update, "Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return
    
    # Check if verified
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return
    
    await update.message.reply_text("Which module? (1-12)")
    return SUBMIT_MODULE

async def share_win_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await reply_translated(update, "Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return
    
    # Check if verified
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return
    
    await update.message.reply_text("What type of win? Choose:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Text", callback_data="win_text"),
                 InlineKeyboardButton("Image", callback_data="win_image"),
                 InlineKeyboardButton("Video", callback_data="win_video")]
            ]))
    return WIN_TYPE

async def status_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return
    
    # Check if verified
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return
    
    await check_status_handler(update, context)

async def ask_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("To ask a question in group, please type /ask")
        return
    
    # Check if verified
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return
    
    await update.message.reply_text("What's your question?")
    return ASK_QUESTION

# Admin: /add_student conversation
async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await reply_translated(update, "You are not authorized to perform this action.")
        return ConversationHandler.END
    
    # Must be in VERIFICATION_GROUP_ID
    if VERIFICATION_GROUP_ID and update.effective_chat.id != VERIFICATION_GROUP_ID:
        await update.message.reply_text("Use /add_student in the verification group.")
        return ConversationHandler.END
    
    await update.message.reply_text("Enter student's full name:")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Try again:")
        return ADD_STUDENT_NAME
    context.user_data['new_student_name'] = name
    await update.message.reply_text("Enter student's phone number (e.g., +2341234567890):")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = (update.message.text or "").strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Invalid phone format. Use +<countrycode><number>. Try again:")
        return ADD_STUDENT_PHONE
    context.user_data['new_student_phone'] = phone
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email. Try again:")
        return ADD_STUDENT_EMAIL
    
    name = context.user_data.get('new_student_name')
    phone = context.user_data.get('new_student_phone')
    h = make_hash(name, email, phone)
    created_at = datetime.utcnow().isoformat()
    
    try:
        await db_execute(
            "INSERT INTO pending_verifications (name, email, phone, status, hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, phone, "Pending", h, created_at),
        )
    except Exception:
        await update.message.reply_text("A pending student with this email already exists.")
        return ConversationHandler.END
    
    # Also append to Google Sheets if configured via unified helper
    try:
        await sync_to_sheets(
            "Verifications",
            "append",
            {"name": name, "email": email, "phone": phone, "telegram_id": 0, "status": "Pending", "hash": h, "created_at": created_at},
            row_data=[name, email, phone, 0, "Pending", h, created_at]
        )
    except Exception:
        logger.exception("Failed to append to Google Sheets (non-fatal).")
    
    await reply_translated(update, f"Student {name} added. They can verify with these details. Admins can manually verify with /verify_student [email].")
    return ConversationHandler.END

# Admin manual verification: /verify_student [email]
async def verify_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    if len(context.args) < 1:
        await reply_translated(update, "Usage: /verify_student [email]")
        return
    
    email = context.args[0].strip()
    if not EMAIL_RE.match(email):
        await reply_translated(update, "Invalid email.")
        return
    
    row = await db_fetchone(
        "SELECT name, phone, hash FROM pending_verifications WHERE email = ? AND status = ?",
        (email, "Pending")
    )
    if not row:
        await reply_translated(update, "No pending student found with that email. Add with /add_student first.")
        return
    
    name, phone, h = row
    # Mark verified
    verified_at = datetime.utcnow().isoformat()
    await db_execute(
        "INSERT INTO verified_users (name, email, phone, telegram_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, phone = EXCLUDED.phone, status = EXCLUDED.status",
        (name, email, phone, 0, "Verified", verified_at)
    )
    await db_execute(
        "UPDATE pending_verifications SET status = ? WHERE email = ?",
        ("Verified", email)
    )
    
    # Update Google Sheets via unified helper
    try:
        await sync_to_sheets(
            "Verifications",
            "update",
            {"search_value": email},
            search_col=2,
            update_cols=[(5, "Verified"), (4, 0)]
        )
    except Exception:
        logger.exception("Failed to sync manual verification to sheets.")
    
    # Enhanced Systeme.io sync with async helpers
    systeme_success = False
    contact_id = None
    try:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

        # Check if contact exists first
        existing_contact = await systeme_get_contact_by_email(email)
        if existing_contact:
            contact_id = existing_contact['id']
            logger.info(f"Existing Systeme.io contact found: {contact_id}")
            # Update fields if needed
            await systeme_update_contact(contact_id, first, last, phone)
        else:
            contact_id = await systeme_create_contact_with_retry(first, last, email, phone)

        if contact_id:
            # Add and verify tag
            tagging_success = await systeme_add_and_verify_tag(contact_id)
            if tagging_success:
                systeme_success = True
                logger.info(f"Systeme.io contact {contact_id} created/updated and tagged successfully")
            else:
                logger.warning(f"Systeme.io contact {contact_id} created but tagging failed")

            # Update the verified_users table with systeme contact ID
            await db_execute(
                "UPDATE verified_users SET systeme_contact_id = ? WHERE email = ?",
                (contact_id, email)
            )
        else:
            raise ValueError("Contact creation failed")

    except Exception as e:
        logger.exception(f"Systeme.io integration failed: {e}")
        await notify_admin_systeme_failure(name, email, str(e), contact_id)
    
    await update.message.reply_text(f"Student with email {email} verified successfully!")

# Enhanced remove student functionality
async def find_student_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """Find student by email, name, or telegram ID with partial matching."""
    identifier = (identifier or "").strip()
    # Email exact (case-insensitive)
    if "@" in identifier:
        row = await db_fetchone(
            "SELECT telegram_id, name, email, phone, systeme_contact_id FROM verified_users WHERE LOWER(email) = LOWER(?) AND removed_at IS NULL",
            (identifier,)
        )
        if row:
            return {"telegram_id": row[0], "name": row[1], "email": row[2], "phone": row[3], "systeme_contact_id": row[4]}
    # Telegram ID
    try:
        t_id = int(identifier)
        row = await db_fetchone(
            "SELECT telegram_id, name, email, phone, systeme_contact_id FROM verified_users WHERE telegram_id = ? AND removed_at IS NULL",
            (t_id,)
        )
        if row:
            return {"telegram_id": row[0], "name": row[1], "email": row[2], "phone": row[3], "systeme_contact_id": row[4]}
    except ValueError:
        pass
    # Partial name (case-insensitive)
    rows = await db_fetchall(
        "SELECT telegram_id, name, email, phone, systeme_contact_id FROM verified_users WHERE LOWER(name) LIKE ? AND removed_at IS NULL",
        (f"%{identifier.lower()}%",)
    )
    if len(rows) == 1:
        row = rows[0]
        return {"telegram_id": row[0], "name": row[1], "email": row[2], "phone": row[3], "systeme_contact_id": row[4]}
    elif len(rows) > 1:
        return {"multiple_matches": [(row[0], row[1], row[2]) for row in rows]}
    return None

async def remove_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced remove student command with batch support and confirmation."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return ConversationHandler.END
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_student [identifier1,identifier2,...]\n\nIdentifiers: email, name, or telegram ID")
        return ConversationHandler.END
    
    # Parse identifiers (comma-separated)
    identifiers = [id.strip() for id in " ".join(context.args).split(",")]
    students_to_remove = []
    multiple_matches = []
    
    for identifier in identifiers:
        result = await find_student_by_identifier(identifier)
        if result and "multiple_matches" in result:
            multiple_matches.append((identifier, result["multiple_matches"]))
        elif result:
            students_to_remove.append(result)
        else:
            await update.message.reply_text(f"❌ No student found for identifier: {identifier}")
    
    if not students_to_remove and not multiple_matches:
        await update.message.reply_text("❌ No students found to remove.")
        return ConversationHandler.END
    
    # Handle multiple matches
    if multiple_matches:
        for identifier, matches in multiple_matches:
            buttons = []
            for t_id, name, email in matches:
                buttons.append([InlineKeyboardButton(f"{name} ({email})", callback_data=f"remove_specific_{t_id}")])
            buttons.append([InlineKeyboardButton("Cancel", callback_data="cancel_remove")])
            
            await update.message.reply_text(
                f"Multiple matches found for '{identifier}':",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return REMOVE_CONFIRM
    
    # Store students to remove and show confirmation
    context.user_data['students_to_remove'] = students_to_remove
    
    # Create confirmation message
    msg = "⚠️ Confirm Student Removal\n\n"
    for student in students_to_remove:
        msg += f"• {student['name']} ({student['email']})\n"
    
    msg += f"\nThis will:\n"
    msg += f"• Remove access to all bot features\n"
    msg += f"• Revoke Systeme.io course access\n"
    msg += f"• Log the removal with reason\n\n"
    msg += f"Are you sure?"
    
    buttons = [
        [InlineKeyboardButton("✅ Confirm Removal", callback_data="confirm_remove")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")]
    ]
    
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))
    return REMOVE_CONFIRM

async def remove_student_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle remove student confirmation."""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    if query.data == "cancel_remove":
        await query.edit_message_text("❌ Removal cancelled.")
        return ConversationHandler.END
    
    if query.data == "confirm_remove":
        await query.edit_message_text("Please provide a reason for removal (optional but recommended):")
        return REMOVE_REASON
    
    if query.data.startswith("remove_specific_"):
        t_id = int(query.data.split("_", 2)[2])
        # Find the specific student and add to removal list
        result = await find_student_by_identifier(str(t_id))
        if result:
            context.user_data['students_to_remove'] = [result]
            await query.edit_message_text("Please provide a reason for removal (optional but recommended):")
            return REMOVE_REASON
    
    return ConversationHandler.END

async def remove_student_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process student removal with reason."""
    reason = update.message.text.strip() if update.message.text else "No reason provided"
    students_to_remove = context.user_data.get('students_to_remove', [])
    
    if not students_to_remove:
        await update.message.reply_text("❌ No students to remove.")
        return ConversationHandler.END
    
    removed_count = 0
    failed_count = 0
    
    for student in students_to_remove:
        try:
            # Soft delete in database
            await db_execute(
                "UPDATE verified_users SET removed_at = ? WHERE telegram_id = ?",
                (datetime.utcnow().isoformat(), student['telegram_id'])
            )
            await db_execute(
                "UPDATE pending_verifications SET status = ?, telegram_id = ? WHERE email = ?",
                ("Removed", 0, student['email'])
            )
            await db_execute(
                "INSERT INTO removals (telegram_id, admin_id, reason) VALUES (?, ?, ?)",
                (student['telegram_id'], update.effective_user.id, reason)
            )
            
            # Update Google Sheets
            try:
                if gs_sheet:
                    sheet = gs_sheet.worksheet("Verifications")
                    cells = sheet.findall(student['email'])
                    for c in cells:
                        row_idx = c.row
                        sheet.update_cell(row_idx, 5, "Removed")
                        sheet.update_cell(row_idx, 4, "")
            except Exception:
                logger.exception("Sheets update failed")
            
            # Remove from Systeme.io
            if student.get('systeme_contact_id'):
                await remove_systeme_contact(student['systeme_contact_id'])
            
            # Notify student
            try:
                await telegram_app.bot.send_message(
                    chat_id=student['telegram_id'],
                    text=f"🚫 Your access to AVAP has been revoked.\n\nReason: {reason}\n\nContact support if you believe this is an error."
                )
            except Exception:
                logger.exception(f"Failed to notify student {student['telegram_id']}")
            
            removed_count += 1
            
        except Exception as e:
            logger.exception(f"Failed to remove student {student['name']}: {e}")
            failed_count += 1
    
    # Send summary
    msg = f"✅ Removal Complete\n\n"
    msg += f"Removed: {removed_count}\n"
    if failed_count > 0:
        msg += f"Failed: {failed_count}\n"
    msg += f"Reason: {reason}"
    
    await update.message.reply_text(msg)
    return ConversationHandler.END

# Admin-only help command: lists all features and commands
async def admin_help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    if (ADMIN_IDS and user_id in ADMIN_IDS) or (await is_admin(user_id)):
        help_text = (
            "Admin Help - AVAP Bot\n\n"
            "Core Commands:\n"
            "- /start - Start menu (DM only)\n"
            "- /status - Check student status (DM)\n\n"
            "Admin Commands:\n"
            "- /add_student - Add a student (flow)\n"
            "- /remove_student <email|name> - Remove student (flow)\n"
            "- /verify_student <email> - Manually verify student\n"
            "- /get_submission <submission_id> - View submission\n"
            "- /list_achievers - List badge earners\n"
            "- /broadcast <message> - DM all verified users\n"
            "- /add_tip <text> - Add Daily Tip\n"
            "- /match - Join matching queue (student)\n"
            "- /match_status - View/Manage matching queue (admin)\n\n"
            "Student Commands:\n"
            "- /ask [question] - Ask a question (group/DM)\n"
            "- /setlang <code> - Set language (e.g., en, fr, es)\n\n"
            "Notes:\n"
            "- Assignment and Win flows use on-screen buttons in DM.\n"
            "- Daily Tips auto-post 08:00 WAT.\n"
        )
        await update.message.reply_text(help_text)
    else:
        await update.message.reply_text("This command is for admins only.")

# Legacy remove student command for backward compatibility
async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy remove student command - redirects to enhanced version."""
    return await remove_student_start(update, context)

# Admin get submission /get_submission [submission_id] or /get_submission @username M#
async def get_submission_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /get_submission <submission_id> OR /get_submission @username M#")
        return
    
    arg0 = context.args[0]
    lookup_by_username = arg0.startswith("@") and len(context.args) >= 2
    
        if lookup_by_username:
            username = arg0.lstrip("@")
            module_token = context.args[1]
            module_num = None
            if module_token.lower().startswith("m") and module_token[1:].isdigit():
                module_num = int(module_token[1:])
            elif module_token.isdigit():
                module_num = int(module_token)
            if not module_num:
                await update.message.reply_text("Invalid module. Use M1/M2/M3 or a number.")
                return
        row = await db_fetchone(
                "SELECT submission_id, module, media_type, media_file_id, score, comment, created_at, telegram_id FROM submissions WHERE username = ? AND module = ? ORDER BY created_at DESC LIMIT 1",
            (username, module_num)
            )
            if not row:
                await update.message.reply_text(f"No submission found for @{username} module {module_num}.")
                return
            sub_id, module, media_type, media_file_id, score, comment, created_at, telegram_id = row
        else:
            sub_id = arg0
        row = await db_fetchone(
                "SELECT module, content_type, content, score, comment, created_at, telegram_id FROM submissions WHERE submission_id = ?",
            (sub_id,)
            )
            if not row:
                await update.message.reply_text(f"No submission found with ID {sub_id}.")
                return
            module, content_type, content, score, comment, created_at, telegram_id = row
            media_type = content_type or "text"
            media_file_id = content or ""
        
        # Get student info
    student_info = await db_fetchone("SELECT name, email FROM verified_users WHERE telegram_id = ?", (telegram_id,))
        student_name = student_info[0] if student_info else "Unknown"
        student_email = student_info[1] if student_info else "Unknown"
    
    # Format submission info
    msg = f"📋 Submission Details:\n"
    msg += f"ID: {sub_id}\n"
    msg += f"Student: {student_name} ({student_email})\n"
    msg += f"Module: {module}\n"
    msg += f"Type: {media_type}\n"
    msg += f"Created: {created_at}\n"
    msg += f"Score: {score if score is not None else 'Not graded'}\n"
    if comment:
        msg += f"Comment: {comment}\n"
    
    await update.message.reply_text(msg)
    
    # Send the actual content if it's media
    if media_type in ['image', 'video'] and media_file_id:
        try:
            if media_type == 'image':
                await update.message.reply_photo(photo=media_file_id, caption=f"Module {module} submission")
            elif media_type == 'video':
                await update.message.reply_video(video=media_file_id, caption=f"Module {module} submission")
        except Exception as e:
            await update.message.reply_text(f"Could not send media: {str(e)}")

# Student verification conversation
async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Try again.")
        return VERIFY_NAME
    context.user_data['verify_name'] = name
    await update.message.reply_text("Enter your phone (+countrycode):")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = (update.message.text or "").strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Invalid phone format. Try again.")
        return VERIFY_PHONE
    context.user_data['verify_phone'] = phone
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip().lower()  # Sanitize
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email. Try again.")
        return VERIFY_EMAIL
    
    name = context.user_data.get('verify_name')
    phone = context.user_data.get('verify_phone')
    h = make_hash(name, email, phone)
    
    row = await db_fetchone(
        "SELECT id, name, email, phone, status FROM pending_verifications WHERE hash = ?",
        (h,)
    )
        if not row:
            await update.message.reply_text("Details not found. Contact an admin or try again.")
            # Offer Verify Now
            verify_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]])
            await update.message.reply_text("Try again or contact admin.", reply_markup=verify_btn)
            return ConversationHandler.END
        
        # Match found -> mark verified
        pending_id = row[0]
        await db_execute(
            "INSERT INTO verified_users (name, email, phone, telegram_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, phone = EXCLUDED.phone, telegram_id = EXCLUDED.telegram_id, status = EXCLUDED.status",
            (name, email, phone, update.effective_user.id, "Verified", datetime.utcnow().isoformat())
        )
        await db_execute(
            "UPDATE pending_verifications SET telegram_id = ?, status = ? WHERE id = ?",
            (update.effective_user.id, "Verified", pending_id)
        )
    
    # Update Google Sheets via unified helper
    try:
        await sync_to_sheets(
            "Verifications",
            "update",
            {"search_value": email},
            search_col=2,
            update_cols=[(4, update.effective_user.id), (5, "Verified")]
        )
    except Exception:
        logger.exception("Sheets sync failed")
    
    # Enhanced Systeme.io integration with async helpers
    systeme_success = False
    contact_id = None
    try:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

        # Check if contact exists first
        existing_contact = await systeme_get_contact_by_email(email)
        if existing_contact:
            contact_id = existing_contact['id']
            logger.info(f"Existing Systeme.io contact found: {contact_id}")
            # Update fields if needed
            await systeme_update_contact(contact_id, first, last, phone)
        else:
            contact_id = await systeme_create_contact_with_retry(first, last, email, phone)

        if contact_id:
            # Add and verify tag
            tagging_success = await systeme_add_and_verify_tag(contact_id)
            if tagging_success:
                systeme_success = True
                logger.info(f"Systeme.io contact {contact_id} created/updated and tagged successfully")
            else:
                logger.warning(f"Systeme.io contact {contact_id} created but tagging failed")

            # Update DB with contact ID
            await db_execute(
                "UPDATE verified_users SET systeme_contact_id = ? WHERE telegram_id = ?",
                (contact_id, update.effective_user.id)
            )
        else:
            raise ValueError("Contact creation failed")

    except Exception as e:
        logger.exception(f"Systeme.io integration failed: {e}")
        await notify_admin_systeme_failure(name, email, str(e), contact_id)

    # Send web link to student immediately after verification
    try:
        await update.message.reply_text(
            f"🎉 Welcome to AVAP! Your verification is complete.\n\n"
            f"📚 Access your course materials here: {AVAP_ACTIVATE_LINK}\n\n"
            f"This link contains all instructions on how to access your course.",
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.exception(f"Failed to send web link to student: {e}")
        # Fallback message without link
        await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=get_main_menu_keyboard())

    # User feedback based on Systeme.io success
    if systeme_success:
        logger.info(f"Student {name} ({email}) verified successfully with full Systeme.io integration")
    else:
        logger.warning(f"Student {name} ({email}) verified in bot but Systeme.io sync had issues")
    
    # Clean up and end conversation
    context.user_data.clear()
    return ConversationHandler.END

# Assignment submission handlers
async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return ConversationHandler.END
    
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return ConversationHandler.END
    
    text = (update.message.text or "").strip()
    try:
        module = int(text)
        if not (1 <= module <= 12):
            raise ValueError()
    except Exception:
        await update.message.reply_text("Module must be an integer between 1 and 12. Try again:")
        return SUBMIT_MODULE
    
    context.user_data['submit_module'] = module
    # Ask media type
    await update.message.reply_text("Video or Image?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Video", callback_data="media_video"), InlineKeyboardButton("Image", callback_data="media_image")]
    ]))
    return SUBMIT_MEDIA_TYPE

async def submit_media_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    media_type = "video" if query.data == "media_video" else "image"
    context.user_data['submit_media_type'] = media_type
    await query.message.reply_text(f"Send your {media_type} now:")
    return SUBMIT_MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Validate media
    media_type = context.user_data.get('submit_media_type')
    file_id = None
    if media_type == "image":
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        else:
            await update.message.reply_text("Please send a photo.")
            return SUBMIT_MEDIA_UPLOAD
    else:
        if update.message.video:
            file_id = update.message.video.file_id
        else:
            await update.message.reply_text("Please send a video.")
            return SUBMIT_MEDIA_UPLOAD
    
    submission_uuid = str(uuid.uuid4())
    module = context.user_data.get('submit_module')
    username = update.effective_user.username or update.effective_user.full_name
    timestamp = datetime.utcnow().isoformat()
    
    await db_execute(
        """INSERT INTO submissions (submission_id, username, telegram_id, module, status, media_type, media_file_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (submission_uuid, username, update.effective_user.id, module, "Submitted", media_type, file_id, timestamp)
    )
    # Sheets: log submission via unified helper
    try:
        await sync_to_sheets(
            "Submissions",
            "append",
            {},
            row_data=[submission_uuid, username, update.effective_user.id, module, "Submitted", media_type, file_id, timestamp]
        )
    except Exception:
        logger.exception("Failed to append submission to Sheets")
    
    # Forward to assignments group with grade button
    if ASSIGNMENTS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{submission_uuid}")]])
        try:
            await telegram_app.bot.send_message(chat_id=ASSIGNMENTS_GROUP_ID, text=f"Submission from {username} - Module {module}: {file_id}", reply_markup=keyboard)
            # forward media
            if media_type == "image":
                await telegram_app.bot.send_photo(chat_id=ASSIGNMENTS_GROUP_ID, photo=file_id, caption=f"From {username} - Module {module}")
            else:
                await telegram_app.bot.send_video(chat_id=ASSIGNMENTS_GROUP_ID, video=file_id, caption=f"From {username} - Module {module}")
        except Exception:
            logger.exception("Failed to forward submission to assignments group")
    
    # Check for achiever badge after submission
    try:
        wins_count = (await db_fetchone("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,)))[0]
        submitted_count = (await db_fetchone("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status IN ('Submitted', 'Graded')", (update.effective_user.id,)))[0]
        await check_and_award_achiever_badge(update.effective_user.id, wins_count, submitted_count)
    except Exception as e:
        logger.exception(f"Failed to check badge after submission: {e}")
    
    await update.message.reply_text("Boom! Submission received!", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# Grading handlers - Updated for ConversationHandler
async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for grading conversation"""
    query = update.callback_query
    if not query:
        return
    
    data = query.data  # e.g., "grade_{uuid}"
    if not data.startswith("grade_"):
        return
    
    # Only admin can grade
    if not await is_admin(query.from_user.id):
        await query.answer("You are not authorized to perform this action.", show_alert=True)
        return ConversationHandler.END
    
    sub_id = data.split("_", 1)[1]
    context.user_data['grading_uuid'] = sub_id
    
    logger.info(f"Starting grading conversation for submission: {sub_id}")
    
    # Show score selection
    try:
        await query.edit_message_text(f"Grading submission {sub_id}. Select score (1-10):", reply_markup=score_keyboard(sub_id))
    except Exception as e:
        logger.exception("Failed to show score selection: %s", e)
        await query.answer("Error starting grading process")
        return ConversationHandler.END
    
    return GradingStates.GRADE_SCORE

async def score_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle score selection in grading conversation"""
    query = update.callback_query
    if not query:
        return
    
    data = query.data
    logger.info(f"score_selected_callback received data: {data}")
    
    parts = data.split("_")  # ["score", score, sub_id]
    if len(parts) != 3:
        logger.warning(f"Invalid score callback data format: {data}")
        await query.answer("Invalid score selection")
        return ConversationHandler.END
    
    _, score_str, sub_id = parts
    try:
        score = int(score_str)
    except ValueError:
        logger.warning(f"Invalid score value: {score_str}")
        await query.answer("Invalid score value")
        return ConversationHandler.END
    
    # Store score in context
    context.user_data['grading_score'] = score
    
    logger.info(f"Score {score} selected for submission {sub_id}")
    
    # Show comment choice
    try:
        await query.edit_message_text(f"Score {score} recorded. Add a comment?", reply_markup=comment_choice_keyboard(sub_id))
    except Exception as e:
        logger.exception("Failed to show comment choice: %s", e)
        await query.answer("Error showing comment options")
        return ConversationHandler.END
    
    return GradingStates.GRADE_COMMENT_CHOICE

async def comment_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle comment choice in grading conversation"""
    query = update.callback_query
    if not query:
        return
    
    data = query.data
    logger.info(f"comment_choice_callback received data: {data}")
    
    if data.startswith("comment_no_"):
        sub_id = data.split("_", 2)[2]
        logger.info(f"Comment choice: No comment for sub_id: {sub_id}")
        
        # Finalize without comment
        await query.answer()
        await finalize_grading(update, context)
        
        try:
            await query.edit_message_text("Grading complete. ✅")
        except Exception:
            pass
        return ConversationHandler.END
    
    if data.startswith("comment_yes_"):
        sub_id = data.split("_", 2)[2]
        logger.info(f"Comment choice: Yes comment for sub_id: {sub_id}")
        
        # Ask for comment type
        try:
            await query.edit_message_text("Choose comment type:", reply_markup=comment_type_keyboard(sub_id))
        except Exception as e:
            logger.exception("Failed to show comment type options: %s", e)
            await query.answer("Error showing comment type options")
            return ConversationHandler.END
        
        return GradingStates.GRADE_COMMENT_TYPE
    
    # Invalid data
    logger.warning(f"Invalid comment choice data: {data}")
    await query.answer("Invalid comment choice")
    return ConversationHandler.END

async def comment_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle comment type selection in grading conversation"""
    query = update.callback_query
    if not query:
        return
    
    data = query.data
    logger.info(f"comment_type_callback received data: {data}")
    
    parts = data.split("_")
    if len(parts) >= 4:
        comment_type = parts[2]  # text, audio, video
        sub_id = parts[3]
        logger.info(f"Processing comment type: {comment_type}, sub_id: {sub_id}")
        
        # Store comment type in context
        context.user_data['comment_type'] = comment_type
        
        # Prompt for input
        try:
            if comment_type == "text":
                await query.edit_message_text("Send your text comment now:")
            elif comment_type == "audio":
                await query.edit_message_text("Send your audio comment now:")
            elif comment_type == "video":
                await query.edit_message_text("Send your video comment now:")
            else:
                await query.edit_message_text("Send your comment now:")
        except Exception as e:
            logger.exception("Failed to prompt for comment: %s", e)
            await query.answer("Error prompting for comment")
            return ConversationHandler.END
        
        return GradingStates.GRADING_COMMENT
    else:
        logger.warning(f"Invalid callback data format: {data}")
        await query.answer("Invalid callback data")
        return ConversationHandler.END

# Grading comment handlers for different media types
async def grading_comment_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text comment in grading conversation"""
    if context.user_data.get('comment_type') != 'text':
        return
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a text comment.")
        return GradingStates.GRADING_COMMENT
    comment_text = (update.message.text or "").strip()
    if not comment_text:
        await update.message.reply_text("Empty comment. Try again.")
        return GradingStates.GRADING_COMMENT
    logger.info(f"Received text comment: {comment_text}")
    
    await finalize_grading(update, context, comment=comment_text)
    await update.message.reply_text("Text comment stored and sent to student.")
    
    return ConversationHandler.END

async def grading_comment_receive_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle audio comment in grading conversation"""
    if context.user_data.get('comment_type') != 'audio':
        return
    
    if update.message.voice:
        file_id = update.message.voice.file_id
        comment_text = f"[voice:{file_id}]"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        comment_text = f"[audio:{file_id}]"
    else:
        await update.message.reply_text("Please send a voice message or audio file.")
        return
    
    logger.info(f"Received audio comment: {comment_text}")
    
    await finalize_grading(update, context, comment=comment_text)
    await update.message.reply_text("Audio comment stored and sent to student.")
    
    return ConversationHandler.END

async def grading_comment_receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video comment in grading conversation"""
    if context.user_data.get('comment_type') != 'video':
        return
    
    if update.message.video:
        file_id = update.message.video.file_id
        comment_text = f"[video:{file_id}]"
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
        comment_text = f"[video_note:{file_id}]"
    else:
        await update.message.reply_text("Please send a video file.")
        return
    
    logger.info(f"Received video comment: {comment_text}")
    
    await finalize_grading(update, context, comment=comment_text)
    await update.message.reply_text("Video comment stored and sent to student.")
    
    return ConversationHandler.END

# Share small win flow
async def win_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    typ = None
    if data == "win_text":
        typ = "text"
    elif data == "win_image":
        typ = "image"
    elif data == "win_video":
        typ = "video"
    context.user_data['win_type'] = typ
    await query.message.reply_text(f"Send your {typ} now:")
    return WIN_UPLOAD

async def win_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only process if we're in the win conversation state
    if context.user_data.get('win_type') is None:
        return
    
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return ConversationHandler.END
    
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return ConversationHandler.END
    
    typ = context.user_data.get('win_type')
    content = None
    if typ == "text":
        content = update.message.text
        if not content or len(content.strip()) == 0:
            await update.message.reply_text("Empty text. Try again.")
            return WIN_UPLOAD
    elif typ == "image":
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return WIN_UPLOAD
        content = update.message.photo[-1].file_id
    elif typ == "video":
        if not update.message.video:
            await update.message.reply_text("Please send a video.")
            return WIN_UPLOAD
        content = update.message.video.file_id
    
    win_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    await db_execute(
        "INSERT INTO wins (win_id, username, telegram_id, content_type, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (win_id, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, typ, content, timestamp)
    )
    # Sheets: log win via unified helper
    try:
        await sync_to_sheets(
            "Wins",
            "append",
            {},
            row_data=[win_id, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, typ, content, timestamp]
        )
    except Exception:
        logger.exception("Failed to append win to Sheets")
    
    # Forward to support group
    if SUPPORT_GROUP_ID:
        try:
            if typ == "text":
                await telegram_app.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=f"Win from {update.effective_user.full_name}: {content}")
            elif typ == "image":
                await telegram_app.bot.send_photo(chat_id=SUPPORT_GROUP_ID, photo=content, caption=f"Win from {update.effective_user.full_name}")
            else:
                await telegram_app.bot.send_video(chat_id=SUPPORT_GROUP_ID, video=content, caption=f"Win from {update.effective_user.full_name}")
        except Exception:
            logger.exception("Failed to forward win to support group")
    
    # Check for achiever badge after sharing win
    try:
        wins_count = (await db_fetchone("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,)))[0]
        submitted_count = (await db_fetchone("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status IN ('Submitted', 'Graded')", (update.effective_user.id,)))[0]
        await check_and_award_achiever_badge(update.effective_user.id, wins_count, submitted_count)
    except Exception as e:
        logger.exception(f"Failed to check badge after win: {e}")
    
    await update.message.reply_text("Awesome win shared!", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# Ask question flow (students)
async def ask_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If in group, require /ask command
    if update.effective_chat.type != ChatType.PRIVATE:
        if len(context.args) < 1:
            await update.message.reply_text("Usage: /ask <question>")
        return
        question_text = " ".join(context.args).strip()
        if not question_text:
            await update.message.reply_text("Please provide a question.")
            return
        
        # Check if verified
        if not await user_verified_by_telegram_id(update.effective_user.id):
            await update.message.reply_text("Please verify first! DM the bot to verify.")
            return
        
        qid = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        await db_execute(
            "INSERT INTO questions (question_id, username, telegram_id, question, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (qid, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, question_text, "Open", timestamp)
        )
        
        # Forward to questions group with Answer button
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{qid}")]])
        await telegram_app.bot.send_message(QUESTIONS_GROUP_ID, f"❓ Question from @{update.effective_user.username or update.effective_user.full_name}:\n\n{question_text}", reply_markup=keyboard)
        await update.message.reply_text("✅ Question sent to support team!")
        return ConversationHandler.END
    
    # If in DM, start conversation
    else:
        if not await user_verified_by_telegram_id(update.effective_user.id):
            await update.message.reply_text("Please verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return
    await update.message.reply_text("What's your question?")
    return ASK_QUESTION

async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text or len(update.message.text.strip()) == 0:
        await update.message.reply_text("Empty question. Try again.")
        return ASK_QUESTION
    
    question_text = update.message.text.strip()
    qid = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    await db_execute(
        "INSERT INTO questions (question_id, username, telegram_id, question, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (qid, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, question_text, "Open", timestamp)
    )
    
    # Forward to questions group with Answer button
    if QUESTIONS_GROUP_ID:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{qid}")]])
        try:
            await telegram_app.bot.send_message(chat_id=QUESTIONS_GROUP_ID, text=f"Question from {update.effective_user.full_name}: {question_text}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward question to questions group")
    
    await update.message.reply_text("Question sent! We'll get back to you.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# Admin clicks Answer in questions group
async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not await is_admin(query.from_user.id):
        await query.answer("You are not authorized to perform this action.", show_alert=True)
        return
    data = query.data
    if not data.startswith("answer_"):
        return
    qid = data.split("_", 1)[1]
    context.user_data['answer_question_id'] = qid
    await query.answer()
    await query.message.reply_text("Send your answer (Text, Audio, Video). It will be forwarded to the student.")
    return ANSWER_QUESTION

async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qid = context.user_data.get('answer_question_id')
    if not qid:
        await update.message.reply_text("No question in progress.")
        return ConversationHandler.END
    
    # Get question info
    row = await db_fetchone("SELECT telegram_id, question FROM questions WHERE question_id = ?", (qid,))
        if not row:
            await update.message.reply_text("Question not found.")
            return ConversationHandler.END
        student_tg, question_text = row
        # Save answer as text for simplicity
        ans = update.message.text or "[non-text answer]"
    await db_execute(
        "UPDATE questions SET answer = ?, answered_by = ?, answered_at = ?, status = ? WHERE question_id = ?",
        (ans, update.effective_user.id, datetime.utcnow().isoformat(), "Answered", qid)
    )
    
    # Send answer to student
    try:
        await telegram_app.bot.send_message(chat_id=student_tg, text=f"Answer to your question: {ans}")
    except Exception:
        logger.exception("Failed to send answer to student")
    
    # Record FAQ in Google Sheets if configured
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("FAQ")
            except Exception:
                sheet = gs_sheet.add_worksheet("FAQ", rows=100, cols=10)
                sheet.append_row(["question", "answer", "created_at"])
            sheet.append_row([question_text, ans, datetime.utcnow().isoformat()])
            logger.info("FAQ recorded in Google Sheets")
    except Exception as e:
        logger.exception("Failed to record FAQ in Google Sheets: %s", e)
    
    await update.message.reply_text("Answer sent and FAQ recorded!")
    context.user_data.pop('answer_question_id', None)
    return ConversationHandler.END

# Check status
async def check_and_award_achiever_badge(telegram_id: int, wins_count: int, submitted_count: int) -> bool:
    """Check and award achiever badge if criteria met."""
    try:
        # Check if already has badge
        row = await db_fetchone(
            "SELECT notified, systeme_tagged FROM student_badges WHERE telegram_id = ? AND badge_type = ?",
            (telegram_id, "achiever")
        )
            
            if row:
                # Already has badge, check if we need to complete notifications/tagging
                notified, systeme_tagged = row
                if not notified:
                    await notify_badge_earned(telegram_id, "achiever")
                    await db_execute(
                        "UPDATE student_badges SET notified = TRUE WHERE telegram_id = ? AND badge_type = ?",
                        (telegram_id, "achiever")
                    )
                
                if not systeme_tagged:
                    await tag_achiever_in_systeme(telegram_id)
                    await db_execute(
                        "UPDATE student_badges SET systeme_tagged = TRUE WHERE telegram_id = ? AND badge_type = ?",
                        (telegram_id, "achiever")
                    )
                
                return True
        
        # Check if criteria met
        if wins_count >= ACHIEVER_WINS and submitted_count >= ACHIEVER_MODULES:
            # Award badge
            await db_execute(
                "INSERT INTO student_badges (telegram_id, badge_type) VALUES (?, ?) ON CONFLICT (telegram_id, badge_type) DO NOTHING",
                (telegram_id, "achiever")
            )
            
            # Notify and tag
            await notify_badge_earned(telegram_id, "achiever")
            await tag_achiever_in_systeme(telegram_id)
            
            # Update tracking flags
            await db_execute(
                "UPDATE student_badges SET notified = TRUE, systeme_tagged = TRUE WHERE telegram_id = ? AND badge_type = ?",
                (telegram_id, "achiever")
            )
            
            return True
        
        return False
        
    except Exception as e:
        logger.exception(f"Failed to check/award achiever badge for {telegram_id}: {e}")
        return False

async def notify_badge_earned(telegram_id: int, badge_type: str):
    """Notify student about earning a badge."""
    try:
        if badge_type == "achiever":
            message = f"🏆 Congratulations! You've earned the AVAP Achiever Badge!\n\n"
            message += f"You've shared {ACHIEVER_WINS} wins and submitted {ACHIEVER_MODULES} assignments.\n"
            message += f"Keep up the great work! 🎉"
        else:
            message = f"🏆 Congratulations! You've earned the {badge_type} badge!"
        
        await telegram_app.bot.send_message(chat_id=telegram_id, text=message)
    except Exception as e:
        logger.exception(f"Failed to notify badge earned for {telegram_id}: {e}")

async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await reply_translated(update, "Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return
    
    vid = await user_verified_by_telegram_id(update.effective_user.id)
    if not vid:
        await reply_translated(update, "Please verify first!")
        return
    
    # Gather assignments and wins count
    subs = await db_fetchall(
        "SELECT module, status, score, comment FROM submissions WHERE telegram_id = ?",
        (update.effective_user.id,)
    )
    wins_count = (await db_fetchone("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,)))[0]
    submitted_count = (await db_fetchone("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status IN ('Submitted', 'Graded')", (update.effective_user.id,)))[0]
    graded_count = (await db_fetchone("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Graded")))[0]
    
    # Check and award achiever badge
    has_achiever_badge = await check_and_award_achiever_badge(update.effective_user.id, wins_count, submitted_count)
    
    # Format submissions with comments
    completed = []
    for r in subs:
        module_info = f"M{r[0]}: {r[1]} (score={r[2]})"
        if r[3]:  # If there's a comment
            module_info += f"\n  💬 Comment: {r[3]}"
        completed.append(module_info)
    
    msg = f"📊 Your Status:\n\n"
    msg += f"Completed modules:\n{chr(10).join(completed) if completed else 'None'}\n\n"
    msg += f"🎉 Wins shared: {wins_count}\n"
    msg += f"📝 Assignments submitted: {submitted_count}"
    
    # Show achiever badge status
    if has_achiever_badge:
        msg += "\n\n🏆 AVAP Achiever Badge earned!"
    else:
        remaining_wins = max(0, ACHIEVER_WINS - wins_count)
        remaining_subs = max(0, ACHIEVER_MODULES - submitted_count)
        if remaining_wins > 0 or remaining_subs > 0:
            msg += f"\n\n🏆 Achiever Badge: {remaining_wins} wins and {remaining_subs} assignments to go!"
    
    await reply_translated(update, msg, reply_markup=get_main_menu_keyboard())
    return

async def list_achievers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all students who have earned the achiever badge."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    achievers = await db_fetchall(
        """
            SELECT vu.name, vu.email, vu.telegram_id, sb.earned_at, 
                   (SELECT COUNT(*) FROM wins WHERE telegram_id = vu.telegram_id) as wins_count,
                   (SELECT COUNT(*) FROM submissions WHERE telegram_id = vu.telegram_id AND status IN ('Submitted', 'Graded')) as subs_count
            FROM student_badges sb
            JOIN verified_users vu ON sb.telegram_id = vu.telegram_id
            WHERE sb.badge_type = 'achiever' AND vu.removed_at IS NULL
            ORDER BY sb.earned_at DESC
        """
    )
    
    if not achievers:
        await update.message.reply_text("No achievers found.")
        return
    
    msg = f"🏆 AVAP Achievers ({len(achievers)} total)\n\n"
    for name, email, tg_id, earned_at, wins, subs in achievers:
        msg += f"• {name} ({email})\n"
        msg += f"  Wins: {wins}, Submissions: {subs}\n"
        msg += f"  Earned: {earned_at}\n\n"
    
    await update.message.reply_text(msg)

# Join request handling
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cjr: ChatJoinRequest = update.chat_join_request
    user = cjr.from_user
    # Only allow if verified
    vid = await user_verified_by_telegram_id(user.id)
    try:
        if vid:
            await telegram_app.bot.approve_chat_join_request(chat_id=cjr.chat.id, user_id=user.id)
            await telegram_app.bot.send_message(chat_id=user.id, text="Welcome! You were approved to join the group.")
        else:
            await telegram_app.bot.decline_chat_join_request(chat_id=cjr.chat.id, user_id=user.id)
            await telegram_app.bot.send_message(chat_id=user.id, text="You must verify first to join this group. Please DM the bot to verify.")
    except Exception:
        logger.exception("Failed to handle chat_join_request")

# Sunday reminder job
async def sunday_reminder_job():
    rows = await db_fetchall("SELECT telegram_id, name FROM verified_users WHERE status = ?", ("Verified",))
    for r in rows:
        t_id, name = r[0], r[1]
        try:
            await telegram_app.bot.send_message(chat_id=t_id, text="🌞 Sunday Reminder: Check your progress with /status and share a win with /share_win!", reply_markup=get_main_menu_keyboard())
        except Exception:
            logger.exception("Failed to send reminder to %s", t_id)

# FastAPI endpoints
@app.get("/")
async def root():
    return {"message": "AVAP Bot running"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/debug-webhook")
async def debug_webhook():
    """Debug webhook URL and current webhook info"""
    try:
        base_url = RENDER_EXTERNAL_URL.strip('/')
        if not base_url.startswith('https://'):
            base_url = f"https://{base_url}"
        webhook_url = f"{base_url}/webhook/{BOT_TOKEN}"
        webhook_info = await telegram_app.bot.get_webhook_info()
        return {
            "status": "success",
            "constructed_webhook_url": webhook_url,
            "current_webhook_info": webhook_info.to_dict(),
            "render_external_url": RENDER_EXTERNAL_URL,
            "bot_token_length": len(BOT_TOKEN) if BOT_TOKEN else 0
        }
    except Exception as e:
        logger.exception("Failed to get webhook info: %s", e)
        return {"status": "error", "message": str(e)}

@app.post("/setup-webhook")
async def setup_webhook():
    """Manual webhook setup endpoint"""
    try:
        base_url = RENDER_EXTERNAL_URL.strip('/')
        if not base_url.startswith('https://'):
            base_url = f"https://{base_url}"
        webhook_url = f"{base_url}/webhook/{BOT_TOKEN}"
        
        # Clear pending updates first
        await telegram_app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Cleared pending updates")
        
        # Wait a moment
        await asyncio.sleep(2)
        
        # Set webhook with specific parameters
        await telegram_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "chat_join_request"]
        )
        
        # Verify webhook was set
        webhook_info = await telegram_app.bot.get_webhook_info()
        
        return {
            "status": "success", 
            "webhook_url": webhook_url,
            "webhook_info": webhook_info.to_dict()
        }
    except Exception as e:
        logger.exception("Failed to set webhook manually: %s", e)
        return {"status": "error", "message": str(e)}

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    
    try:
        body = await request.json()
        update = Update.de_json(body, telegram_app.bot)
        
        # Ensure application is initialized
        if not telegram_app:
            logger.error("Application not initialized")
            raise HTTPException(status_code=500, detail="Application not initialized")
        
        # Handle chat join requests directly
        if update.chat_join_request:
            await chat_join_request_handler(update, None)
        else:
            await telegram_app.process_update(update)
        
        return {"ok": True}
    except Exception as e:
        logger.exception("Error processing webhook: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# Optional Prometheus metrics endpoint
try:
    from prometheus_client import Counter, generate_latest
    updates_counter = Counter('telegram_updates_total', 'Total Telegram updates processed')

    @app.get("/metrics")
    async def metrics():
        return Response(content=generate_latest(), media_type="text/plain")
except Exception:
    pass

# Database dump endpoint (admin-only)
@app.get("/dbdump")
async def dbdump():
    try:
        if not ADMIN_USER_ID:
            raise HTTPException(status_code=403, detail="Admin not configured")
        tables = {
            "verified_users": "SELECT id, name, email, phone, telegram_id, status, systeme_contact_id, language, created_at, removed_at FROM verified_users",
            "pending_verifications": "SELECT id, name, email, phone, telegram_id, status, hash, created_at FROM pending_verifications",
            "submissions": "SELECT id, submission_id, username, telegram_id, module, status, media_type, media_file_id, score, grader_id, comment, comment_type, created_at, graded_at FROM submissions",
            "wins": "SELECT id, win_id, username, telegram_id, content_type, content, created_at FROM wins",
            "questions": "SELECT id, question_id, username, telegram_id, question, status, created_at, answer, answered_by, answered_at FROM questions",
            "student_badges": "SELECT id, telegram_id, badge_type, earned_at, notified, systeme_tagged FROM student_badges",
            "removals": "SELECT id, telegram_id, admin_id, reason, removed_at FROM removals",
        }
        payload = {}
        for name, sql in tables.items():
            rows = await db_fetchall(sql)
            payload[name] = rows
        return JSONResponse(payload)
    except Exception as e:
        logger.exception("DB dump failed: %s", e)
        raise HTTPException(status_code=500, detail="DB dump failed")

# Handler registration
def register_handlers(app_obj: Application):
    # Basic handlers
    app_obj.add_handler(CommandHandler("start", start_handler))
    app_obj.add_handler(CommandHandler("cancel", cancel_handler))
    app_obj.add_handler(CommandHandler("help", admin_help_handler))
    
    # Admin handlers
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,
    )
    app_obj.add_handler(add_student_conv)
    app_obj.add_handler(CommandHandler("verify_student", verify_student_cmd))
    app_obj.add_handler(CommandHandler("remove_student", remove_student_cmd))
    app_obj.add_handler(CommandHandler("get_submission", get_submission_cmd))
    app_obj.add_handler(CommandHandler("list_achievers", list_achievers_cmd))
    app_obj.add_handler(CommandHandler("backup", admin_backup))
# Admin: /backup → JSON dump to Discord webhook or Google Drive (service account)
async def admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    if not ADMIN_USER_ID or int(update.effective_user.id) != int(ADMIN_USER_ID):
        if update.message:
            await update.message.reply_text("You are not authorized to run backups.")
        return
    try:
        rows = await db_fetchall("SELECT * FROM verified_users")
        backup_str = json.dumps(rows, default=str)
        logger.info({"event": "backup_started", "rows": len(rows)})

        discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
        drive_creds_b64 = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")

        if discord_webhook:
            try:
                async with aiohttp.ClientSession() as session:
                    truncated = backup_str[:2000]
                    resp = await session.post(discord_webhook, json={"content": f"Backup (JSON): {truncated}..."})
                    if resp.status in (200, 201, 204):
                        await update.message.reply_text("Backup sent to Discord!")
                    else:
                        await update.message.reply_text(f"Discord upload failed: {resp.status}")
            except Exception as e:
                logger.exception(f"Discord upload failed: {e}")
                await update.message.reply_text("Discord upload failed.")
            return

        if drive_creds_b64:
            if not build or not MediaIoBaseUpload:
                await update.message.reply_text("Google Drive client not available on server.")
                return
            try:
                creds_json = base64.b64decode(drive_creds_b64).decode('utf-8')
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=['https://www.googleapis.com/auth/drive']
                )
                service = build('drive', 'v3', credentials=creds)
                file_metadata = {
                    'name': f'verifications_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                }
                media = MediaIoBaseUpload(BytesIO(backup_str.encode('utf-8')), mimetype='application/json')
                file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                file_id = file.get('id')
                logger.info({"event": "drive_upload_success", "file_id": file_id})
                await update.message.reply_text(f"Backup uploaded to Google Drive: https://drive.google.com/file/d/{file_id}")
                return
            except json.JSONDecodeError as e:
                logger.error({"event": "drive_creds_error", "message": f"Invalid JSON in GOOGLE_DRIVE_CREDENTIALS_JSON: {e}"})
                await update.message.reply_text("Invalid Google credentials JSON.")
                return
            except Exception as e:
                logger.error({"event": "drive_upload_error", "message": str(e)})
                await update.message.reply_text(f"Google Drive upload failed: {str(e)}")
                return

        # Fallback: show truncated JSON in chat
        await update.message.reply_text(f"Backup data (JSON): {backup_str[:2000]}... (Set Discord or Drive envs for full upload)")
    except Exception as e:
        logger.exception(f"Backup failed: {e}")
        if update.message:
            await update.message.reply_text("Unexpected error during backup.")

    
    # Verification conversation for students
    verify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(verify_now_callback, pattern="^verify_now$")],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,
    )
    app_obj.add_handler(verify_conv)

    # Remove student conversation
    remove_conv = ConversationHandler(
        entry_points=[CommandHandler("remove_student", remove_student_start)],
        states={
            REMOVE_CONFIRM: [CallbackQueryHandler(remove_student_confirm_callback, pattern="^(confirm_remove|cancel_remove|remove_specific_.+)$")],
            REMOVE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_student_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,
    )
    app_obj.add_handler(remove_conv)

    # Submission conversation
    submit_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📤 Submit Assignment$") & filters.ChatType.PRIVATE, submit_button_handler),
            MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, submit_module_handler)
        ],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, submit_module_handler)],
            SUBMIT_MEDIA_TYPE: [CallbackQueryHandler(submit_media_type_callback, pattern="^media_(text|audio|video|image)$")],
            SUBMIT_MEDIA_UPLOAD: [MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, submit_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,
    )
    app_obj.add_handler(submit_conv)

    # Grading conversation - Complete flow in single ConversationHandler
    grading_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grade_callback, pattern="^grade_")],
        states={
            GradingStates.GRADE_SCORE: [
                CallbackQueryHandler(score_selected_callback, pattern="^score_")
            ],
            GradingStates.GRADE_COMMENT_CHOICE: [
                CallbackQueryHandler(comment_choice_callback, pattern="^comment_(yes|no)_")
            ],
            GradingStates.GRADE_COMMENT_TYPE: [
                CallbackQueryHandler(comment_type_callback, pattern="^comment_type_(text|audio|video)_")
            ],
            GradingStates.GRADING_COMMENT: [
                # Handle text input
                MessageHandler(filters.TEXT & ~filters.COMMAND, grading_comment_receive_text),
                # Handle audio (voice messages)
                MessageHandler(filters.VOICE, grading_comment_receive_audio),
                # Handle audio files
                MessageHandler(filters.AUDIO, grading_comment_receive_audio),
                # Handle video
                MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, grading_comment_receive_video),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,  # Important for callback queries
        name="grading_conversation",  # For logging/identification
        persistent=False,  # Set to True if you want to persist across restarts
        conversation_timeout=300,  # 5 minutes timeout
    )
    app_obj.add_handler(grading_conv)

    # Wins conversation
    win_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🎉 Share Small Win$") & filters.ChatType.PRIVATE, share_win_button_handler),
            CallbackQueryHandler(win_type_callback, pattern="^win_(text|image|video)$")
        ],
        states={
            WIN_TYPE: [CallbackQueryHandler(win_type_callback, pattern="^win_(text|image|video)$")],
            WIN_UPLOAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, win_receive), 
                        MessageHandler(filters.PHOTO & ~filters.COMMAND, win_receive),
                        MessageHandler(filters.VIDEO & ~filters.COMMAND, win_receive)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False,
    )
    app_obj.add_handler(win_conv)

    # Ask questions conversation
    ask_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ask", ask_start_cmd), 
            MessageHandler(filters.Regex("^❓ Ask a Question$") & filters.ChatType.PRIVATE, ask_button_handler)
        ],
        states={ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)]},
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False
    )
    app_obj.add_handler(ask_conv)
    
    # Answer conversation
    answer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(answer_callback, pattern="^answer_")],
        states={ANSWER_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_receive)]},
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False
    )
    app_obj.add_handler(answer_conv)
    
    # Menu callback handler (for other inline buttons) - DM ONLY
    app_obj.add_handler(CallbackQueryHandler(menu_callback, pattern="^(submit|share_win|status|ask)$"))
    
    # Reply keyboard button handlers - DM ONLY (handled by conversation handlers above)
    # app_obj.add_handler(MessageHandler(filters.Regex("^📤 Submit Assignment$") & filters.ChatType.PRIVATE, submit_button_handler))
    # app_obj.add_handler(MessageHandler(filters.Regex("^🎉 Share Small Win$") & filters.ChatType.PRIVATE, share_win_button_handler))
    app_obj.add_handler(MessageHandler(filters.Regex("^📊 Check Status$") & filters.ChatType.PRIVATE, status_button_handler))
    
    # Check status
    app_obj.add_handler(CommandHandler("status", check_status_handler))
    app_obj.add_handler(CallbackQueryHandler(check_status_handler, pattern="^status$"))
    
    # Register new feature handlers
    daily_tips.register_handlers(app_obj)
    faq_ai_helper.register_handlers(app_obj)
    broadcast.register_handlers(app_obj)
    multilanguage.register_handlers(app_obj)
    voice_transcription.register_handlers(app_obj)
    group_matching.register_handlers(app_obj)
    
    # Chat join request handler - handle in main update processing
    # PTB 22.4 handles this differently, we'll process it in the webhook

# Startup and shutdown events
@app.on_event("startup")
async def on_startup():
    global telegram_app
    logger.info("Starting up AVAP bot - webhook mode")
    
    # Initialize async DB (aiosqlite)
    try:
        await init_async_db()
    except Exception as e:
        logger.exception("Failed to initialize async DB: %s", e)

    # Initialize Google Sheets
    init_gsheets()
    ensure_default_worksheets()
    
    # Build application
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    logger.info("Application built; registering handlers...")
    register_handlers(telegram_app)
    
    # Initialize and start application
    logger.info("Initializing Telegram Application")
    await telegram_app.initialize()
    logger.info("Starting Telegram Application")
    await telegram_app.start()
    
    # Setup scheduler
    try:
        scheduler.add_job(sunday_reminder_job, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=TIMEZONE), id="sunday_reminder")
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.exception("Failed to start scheduler: %s", e)
    
    # Initialize new features
    try:
        # Initialize database for new features
        from ..utils.db_access import init_database
        init_database()
        
        # Schedule daily tips job
        daily_tips.schedule_daily_job(telegram_app)
        
        # Schedule FAQ check job
        faq_ai_helper.schedule_faq_check(telegram_app)
        
        logger.info("New features initialized successfully")
    except Exception as e:
        logger.exception("Failed to initialize new features: %s", e)
    
    # Skip webhook setup during startup - we'll set it manually via endpoint
    logger.info("Skipping webhook setup during startup - will set manually via endpoint")
    logger.info("Webhook URL should be: %s", webhook_url)

@app.on_event("shutdown")
async def on_shutdown():
    global telegram_app
    logger.info("Shutting down AVAP bot")
    
    try:
        scheduler.shutdown(wait=False)
    except Exception as e:
        logger.exception("Error shutting down scheduler: %s", e)
    
    if telegram_app:
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception as e:
            logger.exception("Error shutting down Telegram application: %s", e)

@app.get("/trigger_backup")
async def trigger_backup():
    try:
        rows = await db_fetchall("SELECT * FROM verified_users")
        backup_str = json.dumps(rows, default=str)
        logger.info({"event": "triggered_backup", "rows": len(rows)})

        discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")
        drive_creds_b64 = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON")

        if discord_webhook:
            async with aiohttp.ClientSession() as session:
                await session.post(discord_webhook, json={"content": f"Automated Backup (JSON): {backup_str[:2000]}..."})
        elif drive_creds_b64 and build and MediaIoBaseUpload:
            creds_json = base64.b64decode(drive_creds_b64).decode('utf-8')
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
            service = build('drive', 'v3', credentials=creds)
            file_metadata = {'name': f'auto_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'}
            media = MediaIoBaseUpload(BytesIO(backup_str.encode('utf-8')), mimetype='application/json')
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return {"status": "backup_complete"}
    except Exception as e:
        logger.error({"event": "triggered_backup_error", "message": str(e)})
        return {"status": "backup_failed"}

# Entry point for local development
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting uvicorn for webhook on port %s", port)
    logger.info("Bot version: 1.0.1 - Fixed ASK_QUESTION state")
    uvicorn.run("bot:app", host="0.0.0.0", port=port, log_level="info")
