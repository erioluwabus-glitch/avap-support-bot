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
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, Request, HTTPException
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
from telegram.constants import ParseMode

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

if not WEBHOOK_BASE_URL:
    logger.critical("WEBHOOK_BASE_URL not set. Exiting.")
    raise SystemExit("WEBHOOK_BASE_URL not set")

WEBHOOK_URL = f"{WEBHOOK_BASE_URL.rstrip('/')}/webhook/{BOT_TOKEN}"

# Sqlite DB
DB_PATH = os.getenv("DB_PATH", "avap_bot.db")

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
    GRADE_SCORE,
    GRADE_COMMENT_TYPE,
    GRADE_COMMENT_UPLOAD,
    WIN_TYPE,
    ASK_QUESTION,
    ANSWER_QUESTION,
    GRADE_USERNAME,
    GRADE_MODULE,
) = range(100, 117)

# Regex validators
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+\d{10,15}$")

# FastAPI app
app = FastAPI()

# Telegram Application placeholder (will be initialized on startup)
telegram_app: Optional[Application] = None

# Scheduler for weekly reminders
scheduler = AsyncIOScheduler(timezone=TZ)

# Google Sheets client (optional)
gs_client = None
gs_sheet = None

# Initialize or connect DB
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS pending_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            phone TEXT,
            telegram_id INTEGER DEFAULT 0,
            status TEXT,
            hash TEXT,
            created_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS verified_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            phone TEXT,
            telegram_id INTEGER,
            status TEXT,
            verified_at TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT UNIQUE,
            username TEXT,
            telegram_id INTEGER,
            module INTEGER,
            status TEXT,
            media_type TEXT,
            file_id TEXT,
            score INTEGER,
            comment TEXT,
            timestamp TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS wins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            win_id TEXT UNIQUE,
            username TEXT,
            telegram_id INTEGER,
            content_type TEXT,
            content TEXT,
            timestamp TEXT
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT UNIQUE,
            username TEXT,
            telegram_id INTEGER,
            question TEXT,
            answer TEXT,
            timestamp TEXT
        )"""
    )
    conn.commit()
    return conn

db_conn = init_db()
db_lock = asyncio.Lock()  # guard sqlite usage from async handlers

# Google Sheets helper (optional)
def init_gsheets():
    global gs_client, gs_sheet
    if not GSPREAD_AVAILABLE or not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEETS_SPREADSHEET_ID:
        logger.info("Google Sheets not configured or gspread not installed; skipping.")
        return
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gs_client = gspread.authorize(creds)
        gs_sheet = gs_client.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
        logger.info("Google Sheets connected")
    except Exception as e:
        logger.exception("Failed to initialize Google Sheets: %s", e)
        gs_client = None
        gs_sheet = None

# Systeme.io helper (optional)
def systeme_create_contact(first_name: str, last_name: str, email: str, phone: str) -> Optional[int]:
    if not SYSTEME_API_KEY:
        return None
    try:
        url = "https://api.systeme.io/api/contacts"
        payload = {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone}
        headers = {"Content-Type": "application/json", "X-Auth-Token": SYSTEME_API_KEY}
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        contact_id = data.get("id") or data.get("contact_id")
        # add tag if tag id provided
        if contact_id and SYSTEME_VERIFIED_STUDENT_TAG_ID:
            tag_url = f"https://api.systeme.io/api/contacts/{contact_id}/tags"
            requests.post(tag_url, json={"tag_id": int(SYSTEME_VERIFIED_STUDENT_TAG_ID)}, headers=headers, timeout=10)
        return contact_id
    except Exception as e:
        logger.exception("Systeme.io contact creation failed: %s", e)
        return None

# Utilities
def make_hash(name: str, email: str, phone: str) -> str:
    base = f"{name}{email}{phone}0"
    return hashlib.sha256(base.encode()).hexdigest()

async def is_admin(user_id: int) -> bool:
    return ADMIN_ID and int(user_id) == int(ADMIN_ID)

async def user_verified_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT name, email, phone, telegram_id, status FROM verified_users WHERE telegram_id = ?", (telegram_id,))
        r = cur.fetchone()
        if r:
            return {"name": r[0], "email": r[1], "phone": r[2], "telegram_id": r[3], "status": r[4]}
    return None

async def find_pending_by_hash(h: str):
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT id, name, email, phone, status FROM pending_verifications WHERE hash = ?", (h,))
        return cur.fetchone()

# Reply keyboards (DM-only) — these are fixed buttons that should appear before the input box
MAIN_MENU_KEYBOARD = [
    [KeyboardButton("📤 Submit Assignment"), KeyboardButton("🎉 Share Small Win")],
    [KeyboardButton("📊 Check Status"), KeyboardButton("❓ Ask a Question")],
]

MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True, one_time_keyboard=False)

# ----- Handlers -----

# /start handler - only in DM. If verified -> show main menu (ReplyKeyboardMarkup). If not -> start verification.
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            # In groups, ignore unless admin clickable /add_student etc.
            return
        user = update.effective_user
        if not user:
            return
        vid = await user_verified_by_telegram_id(user.id)
        if vid:
            # Verified -> show main menu
            await update.effective_message.reply_text(
                "✅ You're verified! Choose an action:",
                reply_markup=MAIN_MENU_MARKUP
            )
            # Also send inline menu (for callback-based flows)
            inline = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Submit Assignment", callback_data="submit"),
                 InlineKeyboardButton("🎉 Share Small Win", callback_data="share_win")],
                [InlineKeyboardButton("📊 Check Status", callback_data="status"),
                 InlineKeyboardButton("❓ Ask a Question", callback_data="ask")]
            ])
            await update.effective_message.reply_text("Or use these buttons:", reply_markup=inline)
            return
        # Not verified -> invite to verify
        verify_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]])
        await update.effective_message.reply_text(
            "Welcome! To use AVAP features you must verify your details.\nClick Verify Now to begin.",
            reply_markup=verify_btn
        )
    except Exception:
        logger.exception("Error in start_handler")

# Callback query for main inline buttons
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if not query:
            return
        user = query.from_user
        if query.data == "verify_now":
            await query.answer()
            # Start verify conversation by asking for name
            await query.message.reply_text("Enter your full name:")
            return
        if query.data == "submit":
            await query.answer()
            # If in group, instruct to DM
            if update.effective_chat.type != "private":
                await query.message.reply_text("Please DM me to submit assignments.")
                return
            # kick-off submit flow
            await query.message.reply_text("Which module? (1-12)")
            context.user_data['submit_from_callback'] = True
            return
        if query.data == "share_win":
            await query.answer()
            if update.effective_chat.type != "private":
                await query.message.reply_text("Please DM me to share wins.")
                return
            await query.message.reply_text("What type of win? Choose: Text, Image, Video", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Text", callback_data="win_text"),
                 InlineKeyboardButton("Image", callback_data="win_image"),
                 InlineKeyboardButton("Video", callback_data="win_video")]
            ]))
            return
        if query.data == "status":
            await query.answer()
            if update.effective_chat.type != "private":
                await query.message.reply_text("Please DM me to check your status.")
                return
            await check_status_handler(update, context)
            return
        if query.data == "ask":
            await query.answer()
            # For ask, allow in groups but require /ask command for group flows.
            if update.effective_chat.type != "private":
                await query.message.reply_text("To ask a question in group, please type /ask")
                return
            await query.message.reply_text("What's your question?")
            context.user_data['ask_from_callback'] = True
            return
    except Exception:
        logger.exception("Error in menu_callback")

# Admin: /add_student conversation
async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    # Must be in VERIFICATION_GROUP_ID (optional)
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
    await update.message.reply_text("Enter student's phone (+countrycode e.g. +2341234567890):")
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
    async with db_lock:
        cur = db_conn.cursor()
        try:
            cur.execute(
                "INSERT INTO pending_verifications (name, email, phone, status, hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, email, phone, "Pending", h, created_at),
            )
            db_conn.commit()
        except sqlite3.IntegrityError:
            await update.message.reply_text("A pending student with this email already exists.")
            return ConversationHandler.END
    # Also append to Google Sheets if configured
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("Verifications")
            except Exception:
                sheet = gs_sheet.add_worksheet("Verifications", rows=100, cols=10)
                sheet.append_row(["name", "email", "phone", "telegram_id", "status", "hash", "created_at"])
            sheet.append_row([name, email, phone, 0, "Pending", h, created_at])
    except Exception:
        logger.exception("Failed to append to Google Sheets (non-fatal).")
    await update.message.reply_text(f"Student {name} added. They can verify with these details. Admins can manually verify with /verify_student [email].")
    return ConversationHandler.END

# Admin manual verification: /verify_student [email]
async def verify_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /verify_student [email]")
        return
    email = context.args[0].strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email.")
        return
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT name, phone, hash FROM pending_verifications WHERE email = ? AND status = ?", (email, "Pending"))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("No pending student found with that email. Add with /add_student first.")
            return
        name, phone, h = row
        # Mark verified
        verified_at = datetime.utcnow().isoformat()
        cur.execute("INSERT OR REPLACE INTO verified_users (name, email, phone, telegram_id, status, verified_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, email, phone, 0, "Verified", verified_at))
        cur.execute("UPDATE pending_verifications SET status = ? WHERE email = ?", ("Verified", email))
        db_conn.commit()
    # Update Google Sheets
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("Verifications")
                # naive implementation: find row with that email and update
                cells = sheet.findall(email)
                for c in cells:
                    row_idx = c.row
                    sheet.update_cell(row_idx, 5, "Verified")  # status column
                    sheet.update_cell(row_idx, 4, 0)  # telegram_id
            except Exception:
                pass
    except Exception:
        logger.exception("Failed to sync manual verification to sheets.")
    # Systeme.io sync
    try:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
        systeme_create_contact(first, last, email, phone)
    except Exception:
        logger.exception("Failed to sync to Systeme.io (non-fatal).")
    await update.message.reply_text(f"Student with email {email} verified successfully!")

# Admin remove student /remove_student [telegram_id]
async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_student [telegram_id]")
        return
    try:
        t_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid telegram_id.")
        return
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT email, name FROM verified_users WHERE telegram_id = ?", (t_id,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text(f"No verified student found with Telegram ID {t_id}.")
            return
        email, name = row
        cur.execute("DELETE FROM verified_users WHERE telegram_id = ?", (t_id,))
        cur.execute("UPDATE pending_verifications SET status = ?, telegram_id = ? WHERE email = ?", ("Removed", 0, email))
        db_conn.commit()
    # Optionally tag remove in Systeme.io or update Google Sheets
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("Verifications")
                cells = sheet.findall(email)
                for c in cells:
                    row_idx = c.row
                    sheet.update_cell(row_idx, 5, "Removed")
                    sheet.update_cell(row_idx, 4, "")
            except Exception:
                pass
    except Exception:
        logger.exception("Sheets update failed")
    await update.message.reply_text(f"Student {name} ({t_id}) removed. They must re-verify to regain access.")

# Student verification conversation (/start triggered or verify button)
async def verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow DM verification
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to verify.")
        return ConversationHandler.END
    await update.message.reply_text("Enter your full name:")
    return VERIFY_NAME

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
    email = (update.message.text or "").strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email. Try again.")
        return VERIFY_EMAIL
    name = context.user_data.get('verify_name')
    phone = context.user_data.get('verify_phone')
    h = make_hash(name, email, phone)
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT id, name, email, phone, status FROM pending_verifications WHERE hash = ?", (h,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Details not found. Contact admin or try again.")
            # Offer Verify Now
            verify_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]])
            await update.message.reply_text("Try again or contact admin.", reply_markup=verify_btn)
            return ConversationHandler.END
        # Match found -> mark verified
        pending_id = row[0]
        cur.execute("INSERT OR REPLACE INTO verified_users (name, email, phone, telegram_id, status, verified_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, email, phone, update.effective_user.id, "Verified", datetime.utcnow().isoformat()))
        cur.execute("UPDATE pending_verifications SET telegram_id = ?, status = ? WHERE id = ?", (update.effective_user.id, "Verified", pending_id))
        db_conn.commit()
    # Update Google Sheets
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("Verifications")
                cells = sheet.findall(email)
                for c in cells:
                    row_idx = c.row
                    sheet.update_cell(row_idx, 4, update.effective_user.id)
                    sheet.update_cell(row_idx, 5, "Verified")
            except Exception:
                pass
    except Exception:
        logger.exception("Sheets sync failed")
    # Systeme.io
    try:
        parts = name.split()
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else ""
        systeme_create_contact(first, last, email, phone)
    except Exception:
        logger.exception("Systeme sync error")
    # Welcome and main menu
    await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=MAIN_MENU_MARKUP)
    inline = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Submit Assignment", callback_data="submit"),
         InlineKeyboardButton("🎉 Share Small Win", callback_data="share_win")],
        [InlineKeyboardButton("📊 Check Status", callback_data="status"),
         InlineKeyboardButton("❓ Ask a Question", callback_data="ask")]
    ])
    await update.message.reply_text("Choose an action:", reply_markup=inline)
    # Optionally send welcome landing page here (link or content)
    return ConversationHandler.END

# Submit flow handlers
async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Must be DM and verified
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to submit assignments.")
        return ConversationHandler.END
    vid = await user_verified_by_telegram_id(update.effective_user.id)
    if not vid:
        await update.message.reply_text("Verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
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
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("""INSERT INTO submissions (submission_id, username, telegram_id, module, status, media_type, file_id, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (submission_uuid, username, update.effective_user.id, module, "Submitted", media_type, file_id, timestamp))
        db_conn.commit()
    # Forward to assignments group with grade button
    if ASSIGNMENTS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade:{submission_uuid}")]])
        try:
            await telegram_app.bot.send_message(chat_id=ASSIGNMENTS_GROUP_ID, text=f"Submission from {username} - Module {module} - ID {submission_uuid}", reply_markup=keyboard)
            # forward media (we'll send as file_id)
            if media_type == "image":
                await telegram_app.bot.send_photo(chat_id=ASSIGNMENTS_GROUP_ID, photo=file_id, caption=f"From {username} - Module {module}")
            else:
                await telegram_app.bot.send_video(chat_id=ASSIGNMENTS_GROUP_ID, video=file_id, caption=f"From {username} - Module {module}")
        except Exception:
            logger.exception("Failed to forward submission to assignments group")
    await update.message.reply_text("Boom! Submission received!", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# Grading via inline in assignments group
async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data  # e.g., "grade:<uuid>"
    if not data.startswith("grade:"):
        return
    sub_id = data.split(":", 1)[1]
    # Only admin can grade
    if not await is_admin(query.from_user.id):
        await query.answer("Unauthorized", show_alert=True)
        return
    # Show score selection inline and delete original grade button message to keep group clean
    try:
        await query.message.delete()
    except Exception:
        pass
    score_buttons = [[InlineKeyboardButton(str(i), callback_data=f"score:{sub_id}:{i}") for i in range(1, 6)],
                     [InlineKeyboardButton(str(i), callback_data=f"score:{sub_id}:{i}") for i in range(6, 11)]]
    try:
        await context.bot.send_message(chat_id=ASSIGNMENTS_GROUP_ID, text=f"Grading submission {sub_id}. Select score (1-10):", reply_markup=InlineKeyboardMarkup(score_buttons))
    except Exception:
        logger.exception("Failed to send score selection")

# Score selected callback
async def score_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    parts = query.data.split(":")  # ["score", sub_id, score]
    if len(parts) != 3:
        return
    _, sub_id, score_str = parts
    score = int(score_str)
    # Record score and ask for comment choice
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("UPDATE submissions SET score = ?, status = ? WHERE submission_id = ?", (score, "Graded", sub_id))
        db_conn.commit()
        cur.execute("SELECT username, telegram_id FROM submissions WHERE submission_id = ?", (sub_id,))
        row = cur.fetchone()
    username, t_id = row if row else ("unknown", None)
    # send comment options
    comment_kb = InlineKeyboardMarkup([[InlineKeyboardButton("Comment", callback_data=f"comment_yes:{sub_id}"), InlineKeyboardButton("No Comment", callback_data=f"comment_no:{sub_id}")]])
    try:
        await query.answer()
        await query.message.reply_text(f"Score {score} recorded for {sub_id}. Add a comment?", reply_markup=comment_kb)
    except Exception:
        logger.exception("Failed after score selection")

# Comment choice callback
async def comment_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data
    if data.startswith("comment_no:"):
        sub_id = data.split(":", 1)[1]
        # finalize without comment
        await query.answer()
        try:
            await query.message.reply_text("Grading complete. ✅")
        except Exception:
            pass
        return
    if data.startswith("comment_yes:"):
        sub_id = data.split(":", 1)[1]
        # ask for comment type
        await query.answer()
        await query.message.reply_text("Text, Audio, or Video?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Text", callback_data=f"comment_text:{sub_id}"),
             InlineKeyboardButton("Audio", callback_data=f"comment_audio:{sub_id}"),
             InlineKeyboardButton("Video", callback_data=f"comment_video:{sub_id}")]
        ]))
        return

# Comment type callback
async def comment_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data
    typ, sub_id = data.split(":", 1)[0].split("_")[1] if ":" in data else (None, None)
    # simplified: ask admin to send the comment
    await query.answer()
    context.user_data['grading_sub_id'] = sub_id
    context.user_data['grading_expected'] = 'comment'
    await query.message.reply_text("Send the comment (text/audio/video). It will be sent to student and stored.")
    return

# For simplicity, treat next admin message as comment and store it
async def grading_comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('grading_expected') != 'comment':
        return
    sub_id = context.user_data.get('grading_sub_id')
    if not sub_id:
        return
    # extract comment text or file_id
    comment_text = None
    if update.message.text:
        comment_text = update.message.text
    elif update.message.voice:
        comment_text = f"[voice:{update.message.voice.file_id}]"
    elif update.message.video:
        comment_text = f"[video:{update.message.video.file_id}]"
    elif update.message.audio:
        comment_text = f"[audio:{update.message.audio.file_id}]"
    else:
        await update.message.reply_text("Unsupported comment type, please send text, audio or video.")
        return
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("UPDATE submissions SET comment = ? WHERE submission_id = ?", (comment_text, sub_id))
        db_conn.commit()
        cur.execute("SELECT telegram_id FROM submissions WHERE submission_id = ?", (sub_id,))
        r = cur.fetchone()
    t_id = r[0] if r else None
    # send comment to student if possible
    if t_id:
        try:
            if comment_text.startswith("[voice:") or comment_text.startswith("[audio:") or comment_text.startswith("[video:"):
                # parse
                fid = comment_text.split(":", 1)[1].rstrip("]")
                # send as message describing type (more advanced: fetch actual file)
                await telegram_app.bot.send_message(chat_id=t_id, text=f"You received a grader comment (media): {comment_text}")
            else:
                await telegram_app.bot.send_message(chat_id=t_id, text=f"Your submission {sub_id} was graded. Comment: {comment_text}")
        except Exception:
            logger.exception("Failed to send grade comment to student")
    await update.message.reply_text("Comment stored and sent (if possible).")
    context.user_data.pop('grading_expected', None)
    context.user_data.pop('grading_sub_id', None)

# Share small win flow
async def win_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
    return WIN_TYPE

async def win_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to share wins.")
        return ConversationHandler.END
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
        return ConversationHandler.END
    typ = context.user_data.get('win_type')
    content = None
    if typ == "text":
        content = update.message.text
        if not content or len(content.strip()) == 0:
            await update.message.reply_text("Empty text. Try again.")
            return WIN_TYPE
    elif typ == "image":
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return WIN_TYPE
        content = update.message.photo[-1].file_id
    elif typ == "video":
        if not update.message.video:
            await update.message.reply_text("Please send a video.")
            return WIN_TYPE
        content = update.message.video.file_id
    win_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("INSERT INTO wins (win_id, username, telegram_id, content_type, content, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (win_id, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, typ, content, timestamp))
        db_conn.commit()
    # forward to support group
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
    await update.message.reply_text("Awesome win shared!", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# Ask question flow (students)
async def ask_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If in group, require /ask command (this is that flow)
    if update.effective_chat.type != "private":
        # user will type /ask <question> OR bot will enter ask conversation
        await update.message.reply_text("Please DM me to ask a question, or type /ask in this chat followed by your question.")
        return
    # DM flow
    if not await user_verified_by_telegram_id(update.effective_user.id):
        await update.message.reply_text("Verify first!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]]))
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
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("INSERT INTO questions (question_id, username, telegram_id, question, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (qid, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, question_text, timestamp))
        db_conn.commit()
    # forward to questions group with Answer button
    if QUESTIONS_GROUP_ID:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer:{qid}")]])
        try:
            await telegram_app.bot.send_message(chat_id=QUESTIONS_GROUP_ID, text=f"Question from {update.effective_user.full_name}: {question_text}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward question to questions group")
    await update.message.reply_text("Question sent! We'll get back to you.", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# Admin clicks Answer in questions group
async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not await is_admin(query.from_user.id):
        await query.answer("Unauthorized", show_alert=True)
        return
    data = query.data
    if not data.startswith("answer:"):
        return
    qid = data.split(":", 1)[1]
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
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT telegram_id FROM questions WHERE question_id = ?", (qid,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Question not found.")
            return ConversationHandler.END
        student_tg = row[0]
        # Save answer as text for simplicity
        ans = update.message.text or "[non-text answer]"
        cur.execute("UPDATE questions SET answer = ? WHERE question_id = ?", (ans, qid))
        db_conn.commit()
    # Send answer to student
    try:
        await telegram_app.bot.send_message(chat_id=student_tg, text=f"Answer to your question: {ans}")
    except Exception:
        logger.exception("Failed to send answer to student")
    await update.message.reply_text("Answer sent!")
    context.user_data.pop('answer_question_id', None)
    return ConversationHandler.END

# Check status
async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # works in DM
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to check your status.")
        return
    vid = await user_verified_by_telegram_id(update.effective_user.id)
    if not vid:
        await update.message.reply_text("Verify first!")
        return
    email = vid['email']
    # Gather assignments and wins count
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT module, status, score, comment FROM submissions WHERE telegram_id = ?", (update.effective_user.id,))
        subs = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,))
        wins_count = cur.fetchone()[0]
    completed = [f"M{r[0]}: {r[1]} (score={r[2]})" for r in subs]
    msg = f"Completed modules:\n{chr(10).join(completed) or 'None'}\nWins: {wins_count}"
    await update.message.reply_text(msg, reply_markup=MAIN_MENU_MARKUP)

# Join request handling
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # update.chat_join_request available
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
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT telegram_id, name FROM verified_users WHERE status = ?", ("Verified",))
        rows = cur.fetchall()
    for r in rows:
        t_id, name = r[0], r[1]
        try:
            await telegram_app.bot.send_message(chat_id=t_id, text="🌞 Sunday Reminder: Check your progress with /status and share a win with /sharewin!", reply_markup=MAIN_MENU_MARKUP)
        except Exception:
            logger.exception("Failed to send reminder to %s", t_id)

# Webhook / FastAPI endpoints
@app.get("/")
async def root():
    return {"ok": True, "mode": "webhook"}

@app.get("/health")
async def health():
    return {"ok": True, "mode": "webhook"}

@app.post("/webhook/set")
async def set_webhook_endpoint():
    # set webhook
    bot = telegram_app.bot
    try:
        await bot.delete_webhook()
        await bot.set_webhook(WEBHOOK_URL)
        return {"ok": True, "webhook": WEBHOOK_URL}
    except Exception as e:
        logger.exception("Failed to set webhook")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/delete")
async def delete_webhook_endpoint():
    try:
        await telegram_app.bot.delete_webhook()
        return {"ok": True}
    except Exception as e:
        logger.exception("Failed to delete webhook")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token path")
    body = await request.json()
    update = Update.de_json(body, telegram_app.bot)
    # process update
    # ensure application is initialized
    try:
        await telegram_app.process_update(update)
    except RuntimeError as e:
        # If application wasn't initialized, log and return 500
        logger.exception("Application not initialized: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}

# ----- Application build & startup/shutdown -----
def register_handlers(app_obj: Application):
    # basic handlers
    app_obj.add_handler(CommandHandler("start", start_handler))
    # admin
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[],
        per_message=False,
    )
    app_obj.add_handler(add_student_conv)
    app_obj.add_handler(CommandHandler("verify_student", verify_student_cmd))
    app_obj.add_handler(CommandHandler("remove_student", remove_student_cmd))
    # verification conversation for students
    verify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^verify_now$"), CommandHandler("verify", verify_start), CommandHandler("start_verify", verify_start)],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
        },
        fallbacks=[],
        per_message=False,
    )
    app_obj.add_handler(verify_conv)

    # menu callback handler (submit/share/status/ask)
    app_obj.add_handler(CallbackQueryHandler(menu_callback, pattern="^(submit|share_win|status|ask|verify_now)$"))

    # submission conversation
    submit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, submit_module_handler)],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, submit_module_handler)],
            SUBMIT_MEDIA_TYPE: [CallbackQueryHandler(submit_media_type_callback, pattern="^media_(video|image)$")],
            SUBMIT_MEDIA_UPLOAD: [MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, submit_media_upload)],
        },
        fallbacks=[],
        per_message=False,
    )
    app_obj.add_handler(submit_conv)

    # callback handlers for grading/score/comment
    app_obj.add_handler(CallbackQueryHandler(grade_callback, pattern="^grade:"))
    app_obj.add_handler(CallbackQueryHandler(score_selected_callback, pattern="^score:"))
    app_obj.add_handler(CallbackQueryHandler(comment_choice_callback, pattern="^comment_"))
    app_obj.add_handler(CallbackQueryHandler(comment_type_callback, pattern="^comment_(text|audio|video):?"))

    # receive grading comments as normal messages from admin
    app_obj.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, grading_comment_receive))

    # wins
    app_obj.add_handler(CallbackQueryHandler(win_type_callback, pattern="^win_(text|image|video)$"))
    app_obj.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, win_receive), group=4)  # will act in DM flows

    # ask
    app_obj.add_handler(CommandHandler("ask", ask_start_cmd))
    app_obj.add_handler(ConversationHandler(
        entry_points=[CommandHandler("ask", ask_start_cmd)],
        states={ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)]},
        fallbacks=[],
        per_message=False
    ))
    # answer callback and answer conversation
    app_obj.add_handler(CallbackQueryHandler(answer_callback, pattern="^answer:"))
    app_obj.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(answer_callback, pattern="^answer:")],
        states={ANSWER_QUESTION: [MessageHandler(filters.ALL & ~filters.COMMAND, answer_receive)]},
        fallbacks=[],
        per_message=False
    ))

    # Check status via callback or /status
    app_obj.add_handler(CommandHandler("status", lambda u, c: check_status_handler(u, c)))
    app_obj.add_handler(CallbackQueryHandler(lambda u, c: check_status_handler(u, c), pattern="^status$"))

    # chat_join_request handler
    app_obj.add_handler(MessageHandler(filters.StatusUpdate.CHAT_JOIN_REQUEST, chat_join_request_handler))

    # generic callback handler for menu and others
    app_obj.add_handler(CallbackQueryHandler(menu_callback))

# On startup: initialize telegram application, register handlers, start scheduler, set webhook
@app.on_event("startup")
async def on_startup():
    global telegram_app
    logger.info("Starting up AVAP bot - webhook mode")
    init_gsheets()
    # build application
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    logger.info("Application built; registering handlers...")
    register_handlers(telegram_app)
    # initialize and start application (this sets up job_queue etc)
    logger.info("Initializing Telegram Application")
    await telegram_app.initialize()
    logger.info("Starting Telegram Application")
    await telegram_app.start()
    # Setup scheduler
    try:
        scheduler.add_job(sunday_reminder_job, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=TZ), id="sunday_reminder")
        scheduler.start()
        logger.info("Scheduler started")
    except Exception:
        logger.exception("Failed to start scheduler")
    # delete old webhook and set new one
    try:
        logger.info("Deleting old webhook (if any) and setting new webhook to %s", WEBHOOK_URL)
        await telegram_app.bot.delete_webhook()
        await telegram_app.bot.set_webhook(WEBHOOK_URL)
        logger.info("Webhook set")
    except Exception:
        logger.exception("Failed to set webhook")

@app.on_event("shutdown")
async def on_shutdown():
    global telegram_app
    logger.info("Shutting down AVAP bot")
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    if telegram_app:
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception:
            logger.exception("Error shutting down Telegram application")

# Entry point for local development (uvicorn will import FastAPI app directly in Render)
if __name__ == "__main__":
    # For local dev - run uvicorn directly
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting uvicorn for webhook on port %s", port)
    uvicorn.run("bot:app", host="0.0.0.0", port=port, log_level="info")
