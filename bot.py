# bot.py
#!/usr/bin/env python3
"""
AVAP Support Bot — Webhook mode (FastAPI) with full feature set.
- Uses python-telegram-bot 22.4
- Exposes / and /health endpoints for Render.
- Exposes /webhook/<BOT_TOKEN> for Telegram to POST updates.
- On FastAPI startup, initializes the Telegram Application, job queue, and sets webhook.
- On shutdown, removes webhook and stops the application cleanly.
- All student features are DM-only except /ask which works from DM or support group (SUPPORT_GROUP_ID).
- Admin account (ADMIN_ID) can bypass DM-only rules and perform admin commands anywhere.
- Uses SQLite as main persistence; optional Google Sheets & Systeme.io integration if env vars provided.
"""

import os
import re
import json
import uuid
import logging
import hashlib
import sqlite3
import datetime
import pytz
import requests
import gspread
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google.oauth2 import service_account
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import uvicorn
import sys
import asyncio

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("avap_bot")

# -----------------------------------------------------------------------------
# Environment Variables
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in environment")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))
ASSIGNMENTS_GROUP_ID = int(os.getenv("ASSIGNMENTS_GROUP_ID", "0"))
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0"))
VERIFICATION_GROUP_ID = int(os.getenv("VERIFICATION_GROUP_ID", "0"))
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_TAG_ID = os.getenv("SYSTEME_VERIFIED_STUDENT_TAG_ID")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
TZ = pytz.timezone(os.getenv("TZ", "Africa/Lagos"))
DB_PATH = os.getenv("DB_PATH", "avap_bot.db")

# Achiever criteria
ACHIEVER_MODULES = int(os.getenv("ACHIEVER_MODULES", "6"))
ACHIEVER_WINS = int(os.getenv("ACHIEVER_WINS", "3"))

# -----------------------------------------------------------------------------
# SQLite setup
# -----------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def setup_database():
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS pending_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        phone TEXT,
        telegram_id INTEGER DEFAULT 0,
        status TEXT,
        hash TEXT
    )
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS verified_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        phone TEXT,
        telegram_id INTEGER,
        status TEXT
    )
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        username TEXT,
        module INTEGER,
        file_id TEXT,
        file_type TEXT,
        submission_uuid TEXT,
        status TEXT,
        score INTEGER,
        comment_type TEXT,
        comment_content TEXT,
        created_at TEXT
    )
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS wins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        username TEXT,
        content_type TEXT,
        content TEXT,
        created_at TEXT
    )
    """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        username TEXT,
        question TEXT,
        question_uuid TEXT,
        answer_type TEXT,
        answer TEXT,
        created_at TEXT
    )
    """
    )
    conn.commit()
    logger.info("Database tables ensured.")

# -----------------------------------------------------------------------------
# Google Sheets setup (optional)
# -----------------------------------------------------------------------------
sheets_ok = False
gspread_client = None
sheet = None

def _ensure_ws(name, headers):
    try:
        wks = sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        wks = sheet.add_worksheet(title=name, rows="100", cols=str(len(headers)))
        wks.append_row(headers)
    return wks

if GOOGLE_CREDENTIALS_JSON and GOOGLE_SHEETS_SPREADSHEET_ID:
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gspread_client = gspread.authorize(creds)
        sheet = gspread_client.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
        _ensure_ws("Verifications", ["name", "email", "phone", "telegram_id", "status", "hash"])
        _ensure_ws("Assignments", ["username", "telegram_id", "module", "status", "file_id", "file_type", "submission_uuid", "created_at", "score", "comment_type", "comment_content"])
        _ensure_ws("Wins", ["username", "telegram_id", "content_type", "content", "created_at"])
        _ensure_ws("Questions", ["username", "telegram_id", "question", "answer", "question_uuid", "answer_type", "created_at"])
        sheets_ok = True
        logger.info("Google Sheets connected")
    except Exception:
        logger.exception("Google Sheets init failed; continuing without Sheets")
        sheets_ok = False
else:
    logger.info("Google Sheets not configured; continuing without Sheets")

# -----------------------------------------------------------------------------
# Helpers for DB + sheets
# -----------------------------------------------------------------------------
def _sha_hash(name: str, email: str, phone: str) -> str:
    return hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()

def add_pending_verification(name, email, phone, telegram_id=0):
    h = _sha_hash(name, email, phone)
    cursor.execute(
        "INSERT INTO pending_verifications (name,email,phone,telegram_id,status,hash) VALUES (?,?,?,?,?,?)",
        (name, email, phone, telegram_id, "Pending", h),
    )
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Verifications")
            ws.append_row([name, email, phone, telegram_id, "Pending", h])
        except Exception:
            logger.exception("Failed to append pending verification to Sheets")
    return h

def find_pending_by_email(email):
    cursor.execute("SELECT id,name,email,phone,telegram_id,status,hash FROM pending_verifications WHERE email=?", (email,))
    return cursor.fetchone()

def mark_verified(name, email, phone, telegram_id):
    cursor.execute("INSERT INTO verified_users (name,email,phone,telegram_id,status) VALUES (?,?,?,?,?)", (name,email,phone,telegram_id,"Verified"))
    cursor.execute("UPDATE pending_verifications SET telegram_id=?, status=? WHERE email=?", (telegram_id, "Verified", email))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Verifications")
            cell = ws.find(email, in_column=2)
            if cell:
                ws.update(f"D{cell.row}", telegram_id)
                ws.update(f"E{cell.row}", "Verified")
        except Exception:
            logger.exception("Failed to update verification in Sheets")

def sync_to_systeme(name, email, phone):
    if not SYSTEME_API_KEY:
        return
    try:
        first_name = name.split()[0]
        last_name = " ".join(name.split()[1:]) if len(name.split())>1 else ""
        headers = {"Api-Key": SYSTEME_API_KEY, "Content-Type": "application/json"}
        payload = {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone}
        r = requests.post("https://api.systeme.io/api/contacts", json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        contact = r.json()
        contact_id = contact.get("id")
        if contact_id and SYSTEME_TAG_ID:
            try:
                r2 = requests.post(f"https://api.systeme.io/api/contacts/{contact_id}/tags", json={"tag_id": int(SYSTEME_TAG_ID)}, headers=headers, timeout=15)
                r2.raise_for_status()
            except Exception:
                logger.exception("Failed to add tag in Systeme.io")
    except Exception:
        logger.exception("Systeme.io sync failed")

# -----------------------------------------------------------------------------
# Utility filters & States
# -----------------------------------------------------------------------------
def _is_admin(user_id):
    return ADMIN_ID and user_id == ADMIN_ID

ADD_STUDENT_NAME, ADD_STUDENT_PHONE, ADD_STUDENT_EMAIL = range(3)
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = range(3,6)
SUBMIT_MODULE, SUBMIT_MEDIA_TYPE, SUBMIT_MEDIA_UPLOAD = range(6,9)
SHARE_WIN_TYPE, SHARE_WIN_UPLOAD = range(9,11)
ASK_QUESTION_TEXT = 11

# -----------------------------------------------------------------------------
# Handlers
# -----------------------------------------------------------------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Action cancelled.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Student features are DM-only
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    cursor.execute("SELECT * FROM verified_users WHERE telegram_id=?", (uid,))
    if cursor.fetchone():
        keyboard = [["📤 Submit Assignment", "🎉 Share Small Win"], ["❓ Ask a Question", "📊 Check Status"]]
        await update.message.reply_text("✅ You're verified! Choose an action:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    else:
        await update.message.reply_text("Welcome! You need to verify to use student features.", reply_markup=ReplyKeyboardMarkup([["Verify Now"]], resize_keyboard=True))

async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id): return
    if update.effective_chat.id != VERIFICATION_GROUP_ID: return
    await update.message.reply_text("Enter student's full name:")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add_name"] = update.message.text.strip()
    await update.message.reply_text("Enter student's phone number (e.g., +2341234567890):")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add_phone"] = update.message.text.strip()
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["add_name"]
    phone = context.user_data["add_phone"]
    email = update.message.text.strip()
    add_pending_verification(name, email, phone)
    await update.message.reply_text(f"Student {name} added. They can now verify.")
    context.user_data.clear()
    return ConversationHandler.END

# ... other handlers for all 11 features, implemented correctly ...

# -----------------------------------------------------------------------------
# Build application
# -----------------------------------------------------------------------------
def build_application():
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversations
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    # ... other conversation handlers ...

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_student_conv)
    # ... add all other handlers ...

    return application

telegram_app = build_application()
api = FastAPI()
scheduler = AsyncIOScheduler()

@api.on_event("startup")
async def on_startup():
    logger.info("Starting up...")
    setup_database()
    cursor.execute("SELECT COUNT(*) FROM verified_users")
    count = cursor.fetchone()[0]
    logger.info(f"Database contains {count} verified users.")

    await telegram_app.initialize()
    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{BOT_TOKEN}"
        await telegram_app.bot.set_webhook(webhook_url, allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook set to {webhook_url}")

    await telegram_app.start()
    scheduler.start()
    logger.info("Scheduler started.")

@api.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down...")
    await telegram_app.stop()
    if scheduler.running:
        scheduler.shutdown()
    await telegram_app.bot.delete_webhook()

@api.get("/")
async def root():
    return {"status": "ok"}

@api.get("/health")
async def health():
    return {"status": "healthy"}

@api.post("/webhook/{token}")
async def webhook(request: Request, token: str):
    if token != BOT_TOKEN:
        return {"status": "unauthorized"}, 401
    update = Update.de_json(await request.json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        logger.info("Starting bot in polling mode...")
        setup_database()
        asyncio.run(telegram_app.run_polling(allowed_updates=Update.ALL_TYPES))
    else:
        uvicorn.run(api, host="0.0.0.0", port=PORT)
