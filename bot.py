#!/usr/bin/env python3
"""
Complete bot.py - All features (1..11) implemented, SQLite embedded, Google Sheets via env,
Systeme.io sync, FastAPI health endpoint, runs on Render with single asyncio loop.

Before deploying to Render, set these environment variables in Render Dashboard:
 - BOT_TOKEN (preferred) OR TELEGRAM_TOKEN (fallback)
 - GOOGLE_CREDENTIALS      -> entire JSON contents of service account
 - GOOGLE_SHEET_ID         -> spreadsheet id (between /d/ and /edit)
 - SYSTEME_API_KEY         -> Systeme.io API key (required for CRM sync)
 - SYSTEME_VERIFIED_TAG_ID -> Systeme.io tag id for marking verified students (optional)
 - ADMIN_ID                -> numeric Telegram ID for the primary admin (optional but recommended)
 - VERIFICATION_GROUP_ID   -> numeric Telegram chat id for verification group (optional)
 - ASSIGNMENTS_GROUP_ID    -> numeric Telegram chat id for assignments group (optional)
 - QUESTIONS_GROUP_ID      -> numeric Telegram chat id for questions group (optional)
 - SUPPORT_GROUP_ID        -> numeric Telegram chat id for support group (optional)
 - LANDING_PAGE_LINK       -> URL to send as welcome material (optional)
 - PORT                   -> port for web server (Render sets automatically)
 - TZ                     -> timezone (default 'Africa/Lagos')

Requirements (in requirements.txt):
python-telegram-bot[job-queue]==22.4
fastapi==0.111.0
uvicorn[standard]==0.30.0
gspread==6.1.2
google-auth==2.34.0
httpx==0.27.2
requests==2.32.3
"""

import os
import re
import json
import uuid
import sqlite3
import hashlib
import logging
import datetime
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Tuple

import httpx
import gspread
from google.oauth2.service_account import Credentials
from fastapi import FastAPI
import uvicorn

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ChatJoinRequest,
    ChatMember,
    User,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ChatJoinRequestHandler,
)

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("avap_bot")

# -------------------------
# ENV / CONFIG
# -------------------------
def _env(key: str, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key, default)
    if required and not v:
        logger.error("Missing required environment variable: %s", key)
    else:
        logger.info("Env %s loaded: %s", key, bool(v))
    return v

BOT_TOKEN = _env("BOT_TOKEN") or _env("TELEGRAM_TOKEN")
GOOGLE_CREDENTIALS = _env("GOOGLE_CREDENTIALS")
GOOGLE_SHEET_ID = _env("GOOGLE_SHEET_ID")
SYSTEME_API_KEY = _env("SYSTEME_API_KEY")
SYSTEME_VERIFIED_TAG_ID = _env("SYSTEME_VERIFIED_TAG_ID")  # optional
ADMIN_ID = int(_env("ADMIN_ID") or 0) if _env("ADMIN_ID") else None
VERIFICATION_GROUP_ID = int(_env("VERIFICATION_GROUP_ID") or 0) if _env("VERIFICATION_GROUP_ID") else None
ASSIGNMENTS_GROUP_ID = int(_env("ASSIGNMENTS_GROUP_ID") or 0) if _env("ASSIGNMENTS_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(_env("QUESTIONS_GROUP_ID") or 0) if _env("QUESTIONS_GROUP_ID") else None
SUPPORT_GROUP_ID = int(_env("SUPPORT_GROUP_ID") or 0) if _env("SUPPORT_GROUP_ID") else None
LANDING_PAGE_LINK = _env("LANDING_PAGE_LINK", default="https://your-landing-page-link.com")
PORT = int(_env("PORT") or 10000)
TZ = _env("TZ", default="Africa/Lagos")

# -------------------------
# VALIDATION regexes
# -------------------------
RE_PHONE = re.compile(r"^\+\d{10,15}$")
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# -------------------------
# Reply keyboards & inline
# -------------------------
STUDENT_MENU = ReplyKeyboardMarkup(
    [["📤 Submit Assignment", "🎉 Share Small Win"], ["📊 Check Status", "❓ Ask a Question"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

VERIFY_INLINE = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Verify Now", callback_data="verify_now")]])

# -------------------------
# STATES for ConversationHandler
# -------------------------
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
    GRADE_COMMENT_CONTENT,
    SHARE_WIN_TYPE,
    SHARE_WIN_UPLOAD,
    ASK_QUESTION_TEXT,
    ANSWER_QUESTION_CONTENT,
    MANUAL_GRADE_USERNAME,
    MANUAL_GRADE_MODULE,
) = range(18)

# -------------------------
# SQLITE DB (embedded)
# -------------------------
DB_FILE = "database.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Create tables if not exist
c.execute(
    """
CREATE TABLE IF NOT EXISTS pending_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    telegram_id INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Pending',
    hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
c.execute(
    """
CREATE TABLE IF NOT EXISTS verified_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    telegram_id INTEGER NOT NULL UNIQUE,
    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
c.execute(
    """
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    telegram_id INTEGER NOT NULL,
    module INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    file_id TEXT NOT NULL,
    status TEXT DEFAULT 'Submitted',
    submission_uuid TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    score INTEGER,
    comment_type TEXT,
    comment_content TEXT
)
"""
)
c.execute(
    """
CREATE TABLE IF NOT EXISTS wins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    telegram_id INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
c.execute(
    """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    telegram_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    question_uuid TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
conn.commit()

# -------------------------
# Google Sheets init (optional)
# -------------------------
gclient = None
sheet = None
sheets_ok = False
verif_ws = assignments_ws = wins_ws = faq_ws = None

if GOOGLE_CREDENTIALS and GOOGLE_SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDENTIALS),
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        gclient = gspread.authorize(creds)
        sheet = gclient.open_by_key(GOOGLE_SHEET_ID)
        # Ensure worksheets exist (create if missing)
        def _ensure_ws(name, headers):
            try:
                ws = sheet.worksheet(name)
            except Exception:
                ws = sheet.add_worksheet(title=name, rows="1000", cols=str(len(headers)))
                ws.append_row(headers)
            return ws

        verif_ws = _ensure_ws("Verifications", ["id", "name", "phone", "email", "telegram_id", "status", "hash", "created_at"])
        assignments_ws = _ensure_ws("Assignments", ["username", "telegram_id", "module", "media_type", "file_id", "status", "submission_uuid", "created_at", "score", "comment_type", "comment_content"])
        wins_ws = _ensure_ws("Wins", ["username", "telegram_id", "content_type", "content", "created_at"])
        faq_ws = _ensure_ws("Questions", ["username", "telegram_id", "question", "answer", "question_uuid", "created_at"])
        sheets_ok = True
        logger.info("Google Sheets connected and worksheets prepared.")
    except Exception as e:
        logger.exception("Failed to initialize Google Sheets: %s", e)
        sheets_ok = False
else:
    logger.warning("Google Sheets not configured (GOOGLE_CREDENTIALS or GOOGLE_SHEET_ID missing).")

# -------------------------
# Helper functions: DB & Sheets
# -------------------------
def _sha_hash(name: str, email: str, phone: str) -> str:
    seed = f"{name}{email}{phone}0"
    return hashlib.sha256(seed.encode()).hexdigest()

def db_add_pending(name: str, phone: str, email: str) -> Tuple[bool, Optional[str]]:
    h = _sha_hash(name, email, phone)
    try:
        c.execute(
            "INSERT INTO pending_verifications (name, phone, email, hash, status) VALUES (?, ?, ?, ?, 'Pending')",
            (name, phone, email, h),
        )
        conn.commit()
        # also append to sheet
        if sheets_ok and verif_ws:
            try:
                verif_ws.append_row([None, name, phone, email, 0, "Pending", h, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append pending verification to sheet")
        return True, h
    except sqlite3.IntegrityError:
        logger.warning("Pending or existing entry for email already exists: %s", email)
        return False, None
    except Exception:
        logger.exception("Failed to add pending verification to DB")
        return False, None

def db_find_pending_by_hash(h: str):
    c.execute("SELECT * FROM pending_verifications WHERE hash = ? LIMIT 1", (h,))
    return c.fetchone()

def db_find_pending_by_details(name: str, phone: str, email: str):
    c.execute("SELECT * FROM pending_verifications WHERE name = ? AND phone = ? AND email = ? LIMIT 1", (name, phone, email))
    return c.fetchone()

def db_verify_user_by_pending(pending_row, telegram_id: int) -> bool:
    try:
        # pending_row may be sqlite Row
        name = pending_row["name"]
        phone = pending_row["phone"]
        email = pending_row["email"]
        # Insert into verified users
        c.execute(
            "INSERT OR REPLACE INTO verified_users (name, phone, email, telegram_id) VALUES (?, ?, ?, ?)",
            (name, phone, email, telegram_id),
        )
        conn.commit()
        # Update pending record
        c.execute("UPDATE pending_verifications SET telegram_id = ?, status = 'Verified' WHERE id = ?", (telegram_id, pending_row["id"]))
        conn.commit()
        # Update sheets
        if sheets_ok and verif_ws:
            try:
                # find row with matching hash or email and update (simple approach: append a verified row as fallback)
                # naive approach: append verified row
                verif_ws.append_row([None, name, phone, email, telegram_id, "Verified", pending_row["hash"], datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to update Verifications sheet on verify")
        return True
    except Exception:
        logger.exception("Failed to verify user in DB")
        return False

def db_manual_verify_by_email(email: str, telegram_id: Optional[int] = 0) -> bool:
    c.execute("SELECT * FROM pending_verifications WHERE email = ? LIMIT 1", (email,))
    r = c.fetchone()
    if not r:
        return False
    return db_verify_user_by_pending(r, telegram_id or 0)

def db_remove_verified(telegram_id: int) -> bool:
    try:
        c.execute("SELECT * FROM verified_users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
        r = c.fetchone()
        if not r:
            return False
        # Move status in pending_verifications or update sheet
        c.execute("DELETE FROM verified_users WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        # Update sheets if possible (append a removed record)
        if sheets_ok and verif_ws:
            try:
                verif_ws.append_row([None, r["name"], r["phone"], r["email"], 0, "Removed", "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to mark removed in sheet")
        # Optionally tag/remove in Systeme.io handled outside
        return True
    except Exception:
        logger.exception("Failed to remove verified user")
        return False

def db_add_submission(username: str, telegram_id: int, module: int, media_type: str, file_id: str) -> str:
    sub_uuid = str(uuid.uuid4())
    try:
        c.execute(
            "INSERT INTO submissions (username, telegram_id, module, media_type, file_id, submission_uuid) VALUES (?, ?, ?, ?, ?, ?)",
            (username, telegram_id, int(module), media_type, file_id, sub_uuid),
        )
        conn.commit()
        # Append to sheet
        if sheets_ok and assignments_ws:
            try:
                assignments_ws.append_row([username, telegram_id, module, media_type, file_id, "Submitted", sub_uuid, datetime.datetime.utcnow().isoformat(), "", "", ""])
            except Exception:
                logger.exception("Failed to append assignment to sheet")
        return sub_uuid
    except Exception:
        logger.exception("Failed to add submission to DB")
        return sub_uuid

def db_set_submission_graded(sub_uuid: str, score: int, comment_type: Optional[str], comment_content: Optional[str]):
    try:
        c.execute("UPDATE submissions SET status='Graded', score=?, comment_type=?, comment_content=? WHERE submission_uuid = ?", (score, comment_type, comment_content, sub_uuid))
        conn.commit()
        # update sheet if possible (naive: append a grading row or try to find row)
        if sheets_ok and assignments_ws:
            try:
                # For simplicity: append a small "graded" note row
                assignments_ws.append_row(["Graded", sub_uuid, score, comment_type or "", comment_content or "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append grading to sheet")
        return True
    except Exception:
        logger.exception("Failed to mark submission graded")
        return False

def db_add_win(username: str, telegram_id: int, content_type: str, content: str):
    try:
        c.execute("INSERT INTO wins (username, telegram_id, content_type, content) VALUES (?, ?, ?, ?)", (username, telegram_id, content_type, content))
        conn.commit()
        if sheets_ok and wins_ws:
            try:
                wins_ws.append_row([username, telegram_id, content_type, content, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append win to sheet")
        return True
    except Exception:
        logger.exception("Failed to add win to DB")
        return False

def db_add_question(username: str, telegram_id: int, question_text: str) -> str:
    q_uuid = str(uuid.uuid4())
    try:
        c.execute("INSERT INTO questions (username, telegram_id, question, question_uuid) VALUES (?, ?, ?, ?)", (username, telegram_id, question_text, q_uuid))
        conn.commit()
        if sheets_ok and faq_ws:
            try:
                faq_ws.append_row([username, telegram_id, question_text, "", q_uuid, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append question to sheet")
        return q_uuid
    except Exception:
        logger.exception("Failed to add question to DB")
        return q_uuid

def db_get_verified_by_tid(telegram_id: int):
    c.execute("SELECT * FROM verified_users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
    return c.fetchone()

# -------------------------
# Systeme.io integration (async)
# -------------------------
async def systeme_create_contact_and_tag(email: str, first_name: str, phone: Optional[str] = None) -> bool:
    """
    Create contact in Systeme.io and tag with SYSTEME_VERIFIED_TAG_ID (if provided).
    Uses httpx.AsyncClient.
    """
    if not SYSTEME_API_KEY:
        logger.info("SYSTEME_API_KEY not set; skipping Systeme.io sync")
        return False
    headers = {"Accept": "application/json", "Content-Type": "application/json", "X-API-Key": SYSTEME_API_KEY}
    payload = {"email": email, "first_name": first_name}
    if phone:
        payload["phone"] = phone
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(f"https://api.systeme.io/api/contacts", headers=headers, json=payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                contact_id = data.get("id")
                logger.info("Systeme contact created/exists id=%s for %s", contact_id, email)
                # tag if tag id provided
                if SYSTEME_VERIFIED_TAG_ID and contact_id:
                    try:
                        await client.post(f"https://api.systeme.io/api/contacts/{contact_id}/tags", headers=headers, json={"tag_id": SYSTEME_VERIFIED_TAG_ID})
                    except Exception:
                        logger.exception("Failed to tag contact in Systeme.io")
                return True
            elif resp.status_code in (409, 422):
                logger.info("Systeme contact likely exists, status %s", resp.status_code)
                return True
            else:
                logger.warning("Unexpected Systeme response %s: %s", resp.status_code, resp.text[:200])
                return False
        except Exception:
            logger.exception("Systeme.io request failed")
            return False

# -------------------------
# Utilities
# -------------------------
def get_display_name(user: User) -> str:
    if not user:
        return "Unknown"
    return user.full_name if getattr(user, "full_name", None) else (user.username or f"{user.first_name}")

def is_admin_user(user_id: int, chat_id: Optional[int] = None, bot=None) -> bool:
    # quick check vs ADMIN_ID env var, else check chat admin (if chat_id provided)
    try:
        if ADMIN_ID and user_id == ADMIN_ID:
            return True
        if chat_id and bot:
            member = bot.get_chat_member(chat_id, user_id)
            # get_chat_member may be sync or return coroutine depending on context; we'll handle in async flows
            # But this helper is used in sync contexts seldom; prefer explicit checks in handlers.
    except Exception:
        pass
    return False

# -------------------------
# Handlers: verification & admin flows
# -------------------------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tid = user.id
    if db_get_verified_by_tid(tid):
        await update.message.reply_text("✅ You're verified. Choose an action:", reply_markup=STUDENT_MENU)
    else:
        await update.message.reply_text("Welcome! Please verify to access features.", reply_markup=VERIFY_INLINE)

# 1) ADD STUDENT (Admin) - /add_student (starts conversation) - admin-only in verification group
async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin initiates adding a student. Must be used in VERIFICATION_GROUP_ID if configured."""
    caller = update.effective_user
    chat = update.effective_chat
    if VERIFICATION_GROUP_ID and chat and chat.id != VERIFICATION_GROUP_ID:
        await update.message.reply_text(f"/add_student should be used inside the verification group.")
        return ConversationHandler.END
    # Check admin: either ADMIN_ID or chat admin
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to validate admin for add_student")
    if not allowed:
        await update.message.reply_text("Only admins can add students.")
        return ConversationHandler.END
    await update.message.reply_text("Enter student's full name (min 3 characters):")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 3:
        await update.message.reply_text("Name too short. Please enter at least 3 characters.")
        return ADD_STUDENT_NAME
    context.user_data["add_name"] = text
    await update.message.reply_text("Enter student's phone number (e.g., +2341234567890):")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not RE_PHONE.match(phone):
        await update.message.reply_text("Invalid phone format. Use + and digits, 10-15 digits. Example: +2341234567890")
        return ADD_STUDENT_PHONE
    context.user_data["add_phone"] = phone
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email format. Try again.")
        return ADD_STUDENT_EMAIL
    name = context.user_data.get("add_name")
    phone = context.user_data.get("add_phone")
    ok, h = db_add_pending(name, phone, email)
    if ok:
        await update.message.reply_text(
            f"Student {name} added (Pending). They can verify with these details. Admins can manually verify with /verify_student [email]."
        )
    else:
        await update.message.reply_text(f"Failed to add student. A pending or existing record may already exist for {email}.")
    context.user_data.clear()
    return ConversationHandler.END

# 2) STUDENT VERIFICATION (self-verify): /verify or inline button
async def verify_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if db_get_verified_by_tid(user.id):
        await update.message.reply_text("✅ You are already verified.", reply_markup=STUDENT_MENU)
        return ConversationHandler.END
    await update.message.reply_text("Enter your full name (min 3 characters):")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("Name too short. Enter at least 3 characters.")
        return VERIFY_NAME
    context.user_data["v_name"] = name
    await update.message.reply_text("Enter your phone number (e.g., +2341234567890):")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not RE_PHONE.match(phone):
        await update.message.reply_text("Invalid phone. Use format +countrycode and digits.")
        return VERIFY_PHONE
    context.user_data["v_phone"] = phone
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email. Try again.")
        return VERIFY_EMAIL
    name = context.user_data.get("v_name")
    phone = context.user_data.get("v_phone")
    # check pending via DB or sheets
    pending = db_find_pending_by_details(name, phone, email)
    if not pending and sheets_ok:
        # Try to find in sheets by email
        try:
            rows = verif_ws.get_all_records()
            match_row = None
            for r in rows:
                if (r.get("email") or "").strip().lower() == email.strip().lower():
                    match_row = r
                    break
            if match_row:
                # build fake pending row-like object
                pending = {"id": None, "name": match_row.get("name"), "phone": match_row.get("phone"), "email": match_row.get("email"), "hash": match_row.get("hash") or _sha_hash(name, email, phone)}
        except Exception:
            logger.exception("Failed to query verifications sheet")
    if not pending:
        await update.message.reply_text("Details not found. Contact admin or try again.", reply_markup=VERIFY_INLINE)
        context.user_data.clear()
        return ConversationHandler.END
    # verify in DB
    # if pending is sqlite Row convert to mapping
    pending_map = pending if isinstance(pending, dict) or hasattr(pending, "keys") else dict(pending)
    # get a standard representation: if sqlite Row, we used db_find_pending_by_details which returns a sqlite Row
    if hasattr(pending, "keys"):
        # sqlite Row - use db_verify_user_by_pending
        success = db_verify_user_by_pending(pending, update.effective_user.id)
    else:
        # dict from sheet - insert to verified_users and mark sheet
        try:
            # insert into verified_users
            c.execute("INSERT OR REPLACE INTO verified_users (name, phone, email, telegram_id) VALUES (?, ?, ?, ?)", (name, phone, email, update.effective_user.id))
            conn.commit()
            # append verified to sheet
            if sheets_ok and verif_ws:
                try:
                    verif_ws.append_row([None, name, phone, email, update.effective_user.id, "Verified", _sha_hash(name, email, phone), datetime.datetime.utcnow().isoformat()])
                except Exception:
                    logger.exception("Failed to append verified row to sheet")
            success = True
        except Exception:
            logger.exception("Failed to add verified user from sheet match")
            success = False

    if success:
        # sync to Systeme.io (async)
        try:
            await systeme_create_contact_and_tag(email, name, phone)
        except Exception:
            logger.exception("Systeme.io sync failed")
        await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=STUDENT_MENU)
        await update.message.reply_text(f"Please visit: {LANDING_PAGE_LINK}")
    else:
        await update.message.reply_text("Verification failed. Contact admin.")
    context.user_data.clear()
    return ConversationHandler.END

async def verify_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline verify button in DM - attempts to verify by checking pending by telegram_id or asks to run /verify conversation."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    # check if user already in verified
    if db_get_verified_by_tid(user.id):
        await query.message.reply_text("✅ You are already verified.", reply_markup=STUDENT_MENU)
        return
    # See if there's a pending record with telegram_id == user.id
    c.execute("SELECT * FROM pending_verifications WHERE telegram_id = ? LIMIT 1", (user.id,))
    pending = c.fetchone()
    if pending:
        ok = db_verify_user_by_pending(pending, user.id)
        if ok:
            await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
            await query.message.reply_text("✅ Verified! Welcome.", reply_markup=STUDENT_MENU)
            return
    # else instruct user to run /verify
    await query.message.reply_text("Please run /verify to complete verification (we'll ask name/phone/email).")

# 3) MANUAL VERIFICATION BY ADMIN: /verify_student [email]
async def verify_student_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    txt = (update.message.text or "").strip()
    parts = txt.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /verify_student user@example.com")
        return
    email = parts[1].strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email format.")
        return
    # admin check
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        # try chat admin if in group
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to check admin status for verify_student")
    if not allowed:
        await update.message.reply_text("Only admins can verify students manually.")
        return
    # find pending by email in DB or sheet
    c.execute("SELECT * FROM pending_verifications WHERE email = ? LIMIT 1", (email,))
    pending = c.fetchone()
    if not pending and sheets_ok:
        try:
            rows = verif_ws.get_all_records()
            pending_row = None
            for r in rows:
                if (r.get("email") or "").strip().lower() == email.strip().lower() and (r.get("status") or "").lower() != "verified":
                    pending_row = r
                    break
            if pending_row:
                # add to pending table so we can reuse logic
                ok_new, h = db_add_pending(pending_row.get("name"), pending_row.get("phone"), pending_row.get("email"))
                if ok_new:
                    c.execute("SELECT * FROM pending_verifications WHERE email = ? LIMIT 1", (email,))
                    pending = c.fetchone()
        except Exception:
            logger.exception("Failed to find pending in sheet for manual verify")
    if not pending:
        await update.message.reply_text(f"No pending student found with email {email}. Add with /add_student first.")
        return
    # perform verify (we will set telegram_id to 0 unless admin supplies a specific id)
    # If admin used form: /verify_student email 123456789 then parse id
    telegram_id = 0
    # try to parse optional telegram id after email
    if len(parts) == 2:
        # maybe admin provided "/verify_student email,tid" not implemented; keep telegram_id as 0 (for testing)
        pass
    ok = db_verify_user_by_pending(pending, telegram_id)
    if ok:
        # Systeme sync
        try:
            await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
        except Exception:
            logger.exception("Systeme.io sync failed for manual verify")
        await update.message.reply_text(f"Student with email {email} verified successfully!")
    else:
        await update.message.reply_text("Failed to verify student. Check logs.")

# 4) REMOVE VERIFIED STUDENT: /remove_student [telegram_id]
async def remove_student_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    txt = (update.message.text or "").strip()
    parts = txt.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /remove_student <telegram_id>")
        return
    try:
        target_tid = int(parts[1].strip())
    except ValueError:
        await update.message.reply_text("Invalid telegram id.")
        return
    # admin check
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to validate admin for remove_student")
    if not allowed:
        await update.message.reply_text("Only admins can remove students.")
        return
    ok = db_remove_verified(target_tid)
    if ok:
        # Optionally remove from Systeme.io or tag as removed — not implemented robustly here (depends on Systeme API)
        await update.message.reply_text(f"Student {target_tid} removed. They must re-verify to regain access.")
    else:
        await update.message.reply_text(f"No verified student found with Telegram ID {target_tid}.")

# -------------------------
# 5) ASSIGNMENT SUBMISSION flow
# -------------------------
async def submit_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # initial entry when user presses keyboard
    user = update.effective_user
    if not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    await update.message.reply_text("Which module is this for? (1-12)")
    return SUBMIT_MODULE

async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if not (1 <= val <= 12):
            raise ValueError
        context.user_data["submit_module"] = val
        # ask for media type
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Image", callback_data="media_image"), InlineKeyboardButton("Video", callback_data="media_video")]])
        await update.message.reply_text("Select media type:", reply_markup=kb)
        return SUBMIT_MEDIA_TYPE
    except Exception:
        await update.message.reply_text("Please enter a valid module number (1-12).")
        return SUBMIT_MODULE

async def submit_media_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "media_image":
        context.user_data["submit_media_type"] = "image"
    else:
        context.user_data["submit_media_type"] = "video"
    await q.message.reply_text(f"Please send your {context.user_data['submit_media_type']} now.")
    return SUBMIT_MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = get_display_name(user)
    tid = user.id
    module = context.user_data.get("submit_module")
    m_type = context.user_data.get("submit_media_type")
    file_id = None
    if m_type == "image" and update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif m_type == "video" and update.message.video:
        file_id = update.message.video.file_id
    else:
        await update.message.reply_text(f"Please send a valid {m_type}.")
        return SUBMIT_MEDIA_UPLOAD
    sub_uuid = db_add_submission(username, tid, module, m_type, file_id)
    # forward to assignments group with grade button
    if ASSIGNMENTS_GROUP_ID:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{sub_uuid}")]])
        try:
            if m_type == "image":
                await context.bot.send_photo(ASSIGNMENTS_GROUP_ID, file_id, caption=f"Submission: {username} - Module {module} (id:{sub_uuid})", reply_markup=kb)
            else:
                await context.bot.send_video(ASSIGNMENTS_GROUP_ID, file_id, caption=f"Submission: {username} - Module {module} (id:{sub_uuid})", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward submission to assignments group")
    await update.message.reply_text("Boom! Submission received!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 6) GRADING (inline and manual)
# -------------------------
async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    caller = q.from_user
    # admin only
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(q.message.chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to check admin within grade_inline_start")
    if not allowed:
        await q.message.reply_text("Only admins can grade.")
        return ConversationHandler.END
    # get uuid
    payload = q.data.replace("grade_", "")
    sub_uuid = payload
    # store uuid
    context.user_data["grade_uuid"] = sub_uuid
    # ask for score (1-10)
    buttons = [[InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
               [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]]
    await q.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup(buttons))
    return GRADE_SCORE

async def grade_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    score = int(q.data.replace("score_", ""))
    context.user_data["grade_score"] = score
    # ask comment choice
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Add Comment", callback_data="comment_yes"), InlineKeyboardButton("No Comment", callback_data="comment_no")]])
    await q.message.reply_text("Add a comment?", reply_markup=kb)
    return GRADE_COMMENT_TYPE

async def grade_comment_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "comment_no":
        # apply grading now
        uuidv = context.user_data.get("grade_uuid")
        score = context.user_data.get("grade_score")
        db_set_submission_graded(uuidv, score, None, None)
        await q.message.reply_text("✅ Graded (no comment).")
        context.user_data.clear()
        return ConversationHandler.END
    else:
        # ask type
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Text", callback_data="comment_text"), InlineKeyboardButton("Audio", callback_data="comment_audio"), InlineKeyboardButton("Video", callback_data="comment_video")]])
        await q.message.reply_text("Choose comment type:", reply_markup=kb)
        return GRADE_COMMENT_CONTENT

async def grade_comment_collect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctype = q.data.replace("comment_", "")
    context.user_data["grade_comment_type"] = ctype
    await q.message.reply_text(f"Send the {ctype} now (if audio/video, send as file).")
    return GRADE_COMMENT_CONTENT

async def grade_comment_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # collects comment content depending on type (text or media file ids)
    ctype = context.user_data.get("grade_comment_type", "text")
    comment_content = None
    if ctype == "text":
        comment_content = update.message.text.strip()
    elif ctype == "audio" and update.message.audio:
        comment_content = update.message.audio.file_id
    elif ctype == "video" and update.message.video:
        comment_content = update.message.video.file_id
    else:
        await update.message.reply_text("Please send valid comment content.")
        return GRADE_COMMENT_CONTENT
    uuidv = context.user_data.get("grade_uuid")
    score = context.user_data.get("grade_score")
    db_set_submission_graded(uuidv, score, ctype, comment_content)
    await update.message.reply_text("✅ Graded and comment saved.")
    context.user_data.clear()
    return ConversationHandler.END

# Manual grading via /grade
async def grade_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to validate admin for /grade")
    if not allowed:
        await update.message.reply_text("Only admins can use /grade.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username to grade:")
    return MANUAL_GRADE_USERNAME

async def grade_manual_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    context.user_data["manual_grade_username"] = username
    await update.message.reply_text("Enter module number (1-12):")
    return MANUAL_GRADE_MODULE

async def grade_manual_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mod = int(update.message.text.strip())
        if not (1 <= mod <= 12):
            raise ValueError
        username = context.user_data.get("manual_grade_username")
        # find a submission status 'Submitted'
        c.execute("SELECT * FROM submissions WHERE username = ? AND module = ? AND status = 'Submitted' ORDER BY created_at ASC LIMIT 1", (username, mod))
        row = c.fetchone()
        if not row:
            await update.message.reply_text("No submitted assignment found for that user & module.")
            context.user_data.clear()
            return ConversationHandler.END
        # populate grade_uuid and proceed like inline
        context.user_data["grade_uuid"] = row["submission_uuid"]
        # ask score
        buttons = [[InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
                   [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]]
        await update.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup(buttons))
        return GRADE_SCORE
    except Exception:
        await update.message.reply_text("Invalid module number. Operation cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

# -------------------------
# 7) SHARE SMALL WIN
# -------------------------
async def share_win_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Text", callback_data="win_text"), InlineKeyboardButton("Image", callback_data="win_image"), InlineKeyboardButton("Video", callback_data="win_video")]])
    await update.message.reply_text("Choose type of win to share:", reply_markup=kb)
    return SHARE_WIN_TYPE

async def share_win_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "win_text":
        context.user_data["win_type"] = "text"
        await q.message.reply_text("Send your win text:")
    elif data == "win_image":
        context.user_data["win_type"] = "image"
        await q.message.reply_text("Send your image now:")
    else:
        context.user_data["win_type"] = "video"
        await q.message.reply_text("Send your video now:")
    return SHARE_WIN_UPLOAD

async def share_win_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = get_display_name(user)
    tid = user.id
    wtype = context.user_data.get("win_type", "text")
    content = None
    if wtype == "text":
        content = update.message.text.strip()
        if not content:
            await update.message.reply_text("Please send non-empty text.")
            return SHARE_WIN_UPLOAD
    elif wtype == "image" and update.message.photo:
        content = update.message.photo[-1].file_id
    elif wtype == "video" and update.message.video:
        content = update.message.video.file_id
    else:
        await update.message.reply_text("Please send valid media for the chosen type.")
        return SHARE_WIN_UPLOAD
    db_add_win(username, tid, wtype, str(content))
    if SUPPORT_GROUP_ID:
        try:
            if wtype == "text":
                await context.bot.send_message(SUPPORT_GROUP_ID, f"Win from {username}:\n{content}")
            elif wtype == "image":
                await context.bot.send_photo(SUPPORT_GROUP_ID, content, caption=f"Win from {username}")
            else:
                await context.bot.send_video(SUPPORT_GROUP_ID, content, caption=f"Win from {username}")
        except Exception:
            logger.exception("Failed to forward win to support group")
    await update.message.reply_text("Awesome win shared!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 8) ASK A QUESTION
# -------------------------
async def ask_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    await update.message.reply_text("What's your question? (text only)")
    return ASK_QUESTION_TEXT

async def ask_question_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    qtext = update.message.text.strip()
    if not qtext:
        await update.message.reply_text("Please send a non-empty question.")
        return ASK_QUESTION_TEXT
    q_uuid = db_add_question(get_display_name(user), user.id, qtext)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{q_uuid}")]])
    if QUESTIONS_GROUP_ID:
        try:
            await context.bot.send_message(QUESTIONS_GROUP_ID, f"Question from {get_display_name(user)} (id:{q_uuid}):\n{qtext}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward question to questions group")
    await update.message.reply_text("Question sent! We'll get back to you.", reply_markup=STUDENT_MENU)
    return ConversationHandler.END

# Admin answers question
async def answer_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    caller = q.from_user
    # admin check
    allowed = False
    if ADMIN_ID and caller.id == ADMIN_ID:
        allowed = True
    else:
        try:
            member = await context.bot.get_chat_member(q.message.chat.id, caller.id)
            if member.status in ("administrator", "creator"):
                allowed = True
        except Exception:
            logger.exception("Failed to validate admin for answer_question")
    if not allowed:
        await q.message.reply_text("Only admins can answer questions.")
        return ConversationHandler.END
    q_uuid = q.data.replace("answer_", "")
    context.user_data["answer_uuid"] = q_uuid
    await q.message.reply_text("Send your answer (text/audio/video).")
    return ANSWER_QUESTION_CONTENT

async def answer_question_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acontent = None
    if update.message.text:
        acontent = update.message.text.strip()
    elif update.message.audio:
        acontent = update.message.audio.file_id
    elif update.message.video:
        acontent = update.message.video.file_id
    else:
        await update.message.reply_text("Please send text/audio/video as answer.")
        return ANSWER_QUESTION_CONTENT
    q_uuid = context.user_data.get("answer_uuid")
    # update DB and sheet
    try:
        c.execute("UPDATE questions SET answer = ? WHERE question_uuid = ?", (str(acontent), q_uuid))
        conn.commit()
        if sheets_ok and faq_ws:
            try:
                faq_ws.append_row(["Answer", q_uuid, str(acontent), datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append answer to sheet")
    except Exception:
        logger.exception("Failed to update question with answer")
    # find asker id from DB to forward
    c.execute("SELECT * FROM questions WHERE question_uuid = ? LIMIT 1", (q_uuid,))
    row = c.fetchone()
    if row:
        asker_id = row["telegram_id"]
        try:
            if update.message.text:
                await context.bot.send_message(asker_id, f"Answer to your question:\n{acontent}")
            elif update.message.audio:
                await context.bot.send_audio(asker_id, acontent, caption="Answer to your question")
            elif update.message.video:
                await context.bot.send_video(asker_id, acontent, caption="Answer to your question")
        except Exception:
            logger.exception("Failed to deliver answer to asker")
    await update.message.reply_text("Answer sent to student.", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 9) CHECK STATUS
# -------------------------
ACHIEVER_MODULES = int(_env("ACHIEVER_MODULES", default="6"))
ACHIEVER_WINS = int(_env("ACHIEVER_WINS", default="3"))

async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if not db_get_verified_by_tid(uid):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return
    # gather submissions
    try:
        c.execute("SELECT module, status, score FROM submissions WHERE telegram_id = ?", (uid,))
        rows = c.fetchall()
        modules = []
        scores = []
        graded_count = 0
        for r in rows:
            modules.append(str(r["module"]))
            scores.append(str(r["score"]) if r["score"] is not None else "N/A")
            if r["status"] == "Graded":
                graded_count += 1
        # wins
        c.execute("SELECT COUNT(*) as cnt FROM wins WHERE telegram_id = ?", (uid,))
        wins_count = c.fetchone()["cnt"]
        msg = f"Completed modules: {', '.join(modules) if modules else 'None'}\nScores: {', '.join(scores) if scores else 'None'}\nWins: {wins_count}\nGraded submissions: {graded_count}"
        await update.message.reply_text(msg, reply_markup=STUDENT_MENU)
        # Achiever badge
        if graded_count >= ACHIEVER_MODULES and wins_count >= ACHIEVER_WINS:
            await update.message.reply_text("🎉 AVAP Achiever Badge earned! Congratulations! 🎉", reply_markup=STUDENT_MENU)
    except Exception:
        logger.exception("Failed to compute status")
        await update.message.reply_text("Failed to fetch status. Try again later.", reply_markup=STUDENT_MENU)

# -------------------------
# 10) JOIN REQUEST HANDLING
# -------------------------
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles chat_join_request updates. Approves if verified, else declines and instructs to verify.
    """
    # update.chat_join_request is ChatJoinRequest
    try:
        req: ChatJoinRequest = update.chat_join_request
        user = req.from_user
        chat = req.chat
        # only handle for specific groups if configured
        if SUPPORT_GROUP_ID and chat.id != SUPPORT_GROUP_ID:
            # ignore others
            return
        if db_get_verified_by_tid(user.id):
            try:
                await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                await context.bot.send_message(user.id, f"Welcome to {chat.title}! You were auto-approved.", reply_markup=STUDENT_MENU)
            except Exception:
                logger.exception("Failed to approve chat join request")
        else:
            try:
                await context.bot.decline_chat_join_request(chat_id=chat.id, user_id=user.id)
            except Exception:
                logger.exception("Failed to decline chat join request")
            # inform user
            try:
                await context.bot.send_message(user.id, "You need to verify first to join. Please verify with /verify or click verify button.", reply_markup=VERIFY_INLINE)
            except Exception:
                pass
    except Exception:
        logger.exception("Error in chat_join_request_handler")

# -------------------------
# 11) SUNDAY REMINDER - scheduled via job_queue
# -------------------------
async def sunday_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running Sunday reminder job")
    try:
        c.execute("SELECT * FROM verified_users")
        rows = c.fetchall()
        for r in rows:
            tid = r["telegram_id"]
            try:
                await context.bot.send_message(tid, "🌞 Sunday Reminder: Check your progress with /status and share a win with /sharewin!", reply_markup=STUDENT_MENU)
            except Exception:
                logger.exception("Failed to send Sunday reminder to user %s", tid)
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.send_message(SUPPORT_GROUP_ID, "🌞 Sunday Reminder: Encourage students to submit and share wins!")
            except Exception:
                logger.exception("Failed to send Sunday reminder to support group")
    except Exception:
        logger.exception("Failed in sunday_reminder_job")

# -------------------------
# Error handler
# -------------------------
async def on_error(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error: %s", context.error)
    # notify admin if configured
    if ADMIN_ID:
        try:
            await context.bot.send_message(ADMIN_ID, f"⚠️ Bot error: {context.error}")
        except Exception:
            logger.exception("Failed to notify admin about error")

# -------------------------
# Application setup
# -------------------------
def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in env - cannot start bot")
    app = Application.builder().token(BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start_handler))
    # add student (admin flow) - conversation
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(add_student_conv)

    # self verify conv
    verify_conv = ConversationHandler(
        entry_points=[CommandHandler("verify", verify_start_cmd), CallbackQueryHandler(lambda u, c: verify_now_callback(u, c), pattern="^verify_now$")],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(verify_conv)

    # manual verify
    app.add_handler(CommandHandler("verify_student", verify_student_manual))

    # remove student
    app.add_handler(CommandHandler("remove_student", remove_student_handler))

    # Submission conv
    submit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📤 Submit Assignment$"), submit_start_handler)],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module_handler)],
            SUBMIT_MEDIA_TYPE: [CallbackQueryHandler(submit_media_type_cb, pattern="^media_")],
            SUBMIT_MEDIA_UPLOAD: [MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, submit_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(submit_conv)

    # grading conv (inline and manual)
    app.add_handler(CallbackQueryHandler(grade_inline_start, pattern="^grade_"))
    grade_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grade_inline_start, pattern="^grade_")],
        states={
            GRADE_SCORE: [CallbackQueryHandler(grade_score_cb, pattern="^score_")],
            GRADE_COMMENT_TYPE: [CallbackQueryHandler(grade_comment_type_cb, pattern="^comment_")],
            GRADE_COMMENT_CONTENT: [MessageHandler((filters.TEXT | filters.AUDIO | filters.VIDEO) & ~filters.COMMAND, grade_comment_content_handler)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(grade_conv)
    manual_grade_conv = ConversationHandler(
        entry_points=[CommandHandler("grade", grade_manual_start)],
        states={
            MANUAL_GRADE_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_username)],
            MANUAL_GRADE_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_module)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(manual_grade_conv)

    # share win conv
    app.add_handler(MessageHandler(filters.Regex(r"^🎉 Share Small Win$|^🎉 Share Win$|^Share Win$"), share_win_start))
    app.add_handler(CallbackQueryHandler(share_win_type_cb, pattern="^win_"))
    share_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🎉 Share Small Win$|^Share Win$"), share_win_start)],
        states={
            SHARE_WIN_TYPE: [CallbackQueryHandler(share_win_type_cb, pattern="^win_")],
            SHARE_WIN_UPLOAD: [MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, share_win_upload_handler)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(share_conv)

    # ask question conv
    ask_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^❓ Ask a Question$|^Ask Question$"), ask_question_start)],
        states={ASK_QUESTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_text_handler)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(ask_conv)

    # answer conv for admins
    app.add_handler(CallbackQueryHandler(answer_question_start, pattern="^answer_"))
    answer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(answer_question_start, pattern="^answer_")],
        states={ANSWER_QUESTION_CONTENT: [MessageHandler((filters.TEXT | filters.AUDIO | filters.VIDEO) & ~filters.COMMAND, answer_question_content_handler)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(answer_conv)

    # status
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Check Status$|^Check Status$|^/status$"), check_status_handler))

    # chat join request handler
    try:
        app.add_handler(ChatJoinRequestHandler(chat_join_request_handler))
    except Exception:
        # ChatJoinRequestHandler may not be available in some PTB versions; ignore if not supported
        logger.info("ChatJoinRequestHandler not available or failed to register; join-request flow may not work")

    # default menu text fallback to start flows
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: menu_text_fallback(u, c)))

    # error handler
    app.add_error_handler(on_error)

    # schedule Sunday reminder: use job_queue.run_daily - schedule at 18:00 in TZ on Sunday (weekday=6)
    try:
        # job_queue expects datetime.time
        job_time = datetime.time(hour=18, minute=0)
        app.job_queue.run_daily(sunday_reminder_job, time=job_time, days=(6,), name="sunday_reminder")
        logger.info("Scheduled Sunday reminder job at 18:00 weekly (WAT tz dependent on Render env)")
    except Exception:
        logger.exception("Failed to schedule Sunday reminder")

    # add handlers for specific callbacks used earlier
    app.add_handler(CallbackQueryHandler(verify_now_callback, pattern="^verify_now$"))
    app.add_handler(CallbackQueryHandler(submit_media_type_cb, pattern="^media_"))
    app.add_handler(CallbackQueryHandler(grade_comment_type_cb, pattern="^comment_"))
    # grading score handled in grade_conv via pattern ^score_

    return app

# helper menu fallback (if user uses the reply keyboard)
async def menu_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ("📤 Submit Assignment", "Submit Assignment"):
        return await submit_start_handler(update, context)
    if text in ("🎉 Share Small Win", "Share Win"):
        return await share_win_start(update, context)
    if text in ("📊 Check Status", "Check Status"):
        return await check_status_handler(update, context)
    if text in ("❓ Ask a Question", "Ask Question"):
        return await ask_question_start(update, context)
    # default
    await update.message.reply_text("Use the menu buttons.", reply_markup=STUDENT_MENU)

# -------------------------
# Build and run application with FastAPI lifespan to share asyncio loop
# -------------------------
telegram_app = build_application()  # may raise if BOT_TOKEN missing

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize and start Telegram app in same loop
    logger.info("Lifespan starting: initializing Telegram Application")
    try:
        await telegram_app.initialize()
        await telegram_app.start()
        # start polling using updater
        await telegram_app.updater.start_polling()
        logger.info("Telegram polling started")
    except Exception:
        logger.exception("Failed to start Telegram bot in lifespan")
        raise
    try:
        yield
    finally:
        logger.info("Lifespan ending: stopping Telegram Application")
        try:
            await telegram_app.updater.stop()
        except Exception:
            logger.exception("Failed to stop updater")
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception:
            logger.exception("Failed to stop/shutdown Telegram Application")

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.get("/healthz")
async def healthz():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}

@fastapi_app.get("/")
async def root():
    return {"ok": True, "time": datetime.datetime.utcnow().isoformat()}

# -------------------------
# Entrypoint
# -------------------------
if __name__ == "__main__":
    logger.info("Starting AVAP Support Bot app (uvicorn). PORT=%s", PORT)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)
