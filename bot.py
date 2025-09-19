#!/usr/bin/env python3
"""
AVAP Support Bot - full bot.py (patched to restrict student features to DM only,
except /ask which is allowed in DMs and SUPPORT_GROUP_ID). Uses:
- python-telegram-bot 22.4
- FastAPI + uvicorn for Render
- SQLite embedded
- Google Sheets optional
- Systeme.io optional

Environment variables required:
 - BOT_TOKEN (or TELEGRAM_TOKEN)
 - ADMIN_ID (admin Telegram ID)
 - SUPPORT_GROUP_ID (group ID where /ask is allowed)
 - GOOGLE_CREDENTIALS (JSON content) - optional
 - GOOGLE_SHEET_ID - optional
 - SYSTEME_API_KEY - optional
 - SYSTEME_VERIFIED_TAG_ID - optional
 - ... (see README in prior messages)
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
SUPPORT_GROUP_ID = int(_env("SUPPORT_GROUP_ID") or 0) if _env("SUPPORT_GROUP_ID") else None
VERIFICATION_GROUP_ID = int(_env("VERIFICATION_GROUP_ID") or 0) if _env("VERIFICATION_GROUP_ID") else None
ASSIGNMENTS_GROUP_ID = int(_env("ASSIGNMENTS_GROUP_ID") or 0) if _env("ASSIGNMENTS_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(_env("QUESTIONS_GROUP_ID") or 0) if _env("QUESTIONS_GROUP_ID") else None
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
ASK_INLINE = InlineKeyboardMarkup([[InlineKeyboardButton("❓ Ask a Question", callback_data="ask_dm")]])

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
    except Exception:
        logger.exception("Failed to initialize Google Sheets: %s", exc_info=True)
        sheets_ok = False
else:
    logger.info("Google Sheets not configured or missing credentials/sheet ID.")

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
                logger.exception("Failed to append pending verification to sheet", exc_info=True)
        return True, h
    except sqlite3.IntegrityError:
        logger.warning("Pending or existing entry for email already exists: %s", email)
        return False, None
    except Exception:
        logger.exception("Failed to add pending verification to DB", exc_info=True)
        return False, None

def db_find_pending_by_hash(h: str):
    c.execute("SELECT * FROM pending_verifications WHERE hash = ? LIMIT 1", (h,))
    return c.fetchone()

def db_find_pending_by_details(name: str, phone: str, email: str):
    c.execute("SELECT * FROM pending_verifications WHERE name = ? AND phone = ? AND email = ? LIMIT 1", (name, phone, email))
    return c.fetchone()

def db_verify_user_by_pending(pending_row, telegram_id: int) -> bool:
    try:
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
                verif_ws.append_row([None, name, phone, email, telegram_id, "Verified", pending_row["hash"], datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to update Verifications sheet on verify", exc_info=True)
        return True
    except Exception:
        logger.exception("Failed to verify user in DB", exc_info=True)
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
        c.execute("DELETE FROM verified_users WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        if sheets_ok and verif_ws:
            try:
                verif_ws.append_row([None, r["name"], r["phone"], r["email"], 0, "Removed", "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to mark removed in sheet", exc_info=True)
        return True
    except Exception:
        logger.exception("Failed to remove verified user", exc_info=True)
        return False

def db_add_submission(username: str, telegram_id: int, module: int, media_type: str, file_id: str) -> str:
    sub_uuid = str(uuid.uuid4())
    try:
        c.execute(
            "INSERT INTO submissions (username, telegram_id, module, media_type, file_id, submission_uuid) VALUES (?, ?, ?, ?, ?, ?)",
            (username, telegram_id, int(module), media_type, file_id, sub_uuid),
        )
        conn.commit()
        if sheets_ok and assignments_ws:
            try:
                assignments_ws.append_row([username, telegram_id, module, media_type, file_id, "Submitted", sub_uuid, datetime.datetime.utcnow().isoformat(), "", "", ""])
            except Exception:
                logger.exception("Failed to append assignment to sheet", exc_info=True)
        return sub_uuid
    except Exception:
        logger.exception("Failed to add submission to DB", exc_info=True)
        return sub_uuid

def db_set_submission_graded(sub_uuid: str, score: int, comment_type: Optional[str], comment_content: Optional[str]):
    try:
        c.execute("UPDATE submissions SET status='Graded', score=?, comment_type=?, comment_content=? WHERE submission_uuid = ?", (score, comment_type, comment_content, sub_uuid))
        conn.commit()
        if sheets_ok and assignments_ws:
            try:
                assignments_ws.append_row(["Graded", sub_uuid, score, comment_type or "", comment_content or "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append grading to sheet", exc_info=True)
        return True
    except Exception:
        logger.exception("Failed to mark submission graded", exc_info=True)
        return False

def db_add_win(username: str, telegram_id: int, content_type: str, content: str):
    try:
        c.execute("INSERT INTO wins (username, telegram_id, content_type, content) VALUES (?, ?, ?, ?)", (username, telegram_id, content_type, content))
        conn.commit()
        if sheets_ok and wins_ws:
            try:
                wins_ws.append_row([username, telegram_id, content_type, content, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append win to sheet", exc_info=True)
        return True
    except Exception:
        logger.exception("Failed to add win to DB", exc_info=True)
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
                logger.exception("Failed to append question to sheet", exc_info=True)
        return q_uuid
    except Exception:
        logger.exception("Failed to add question to DB", exc_info=True)
        return q_uuid

def db_get_verified_by_tid(telegram_id: int):
    c.execute("SELECT * FROM verified_users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
    return c.fetchone()

# -------------------------
# Systeme.io integration (async)
# -------------------------
async def systeme_create_contact_and_tag(email: str, first_name: str, phone: Optional[str] = None) -> bool:
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
                if SYSTEME_VERIFIED_TAG_ID and contact_id:
                    try:
                        await client.post(f"https://api.systeme.io/api/contacts/{contact_id}/tags", headers=headers, json={"tag_id": SYSTEME_VERIFIED_TAG_ID})
                    except Exception:
                        logger.exception("Failed to tag contact in Systeme.io", exc_info=True)
                return True
            elif resp.status_code in (409, 422):
                logger.info("Systeme contact likely exists, status %s", resp.status_code)
                return True
            else:
                logger.warning("Unexpected Systeme response %s: %s", resp.status_code, resp.text[:200])
                return False
        except Exception:
            logger.exception("Systeme.io request failed", exc_info=True)
            return False

# -------------------------
# Utilities & access control helpers
# -------------------------
def get_display_name(user: User) -> str:
    if not user:
        return "Unknown"
    return user.full_name if getattr(user, "full_name", None) else (user.username or f"{user.first_name}")

def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    return chat.type == "private"

def is_admin_user(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if ADMIN_ID and user.id == ADMIN_ID:
        return True
    return False

# -------------------------
# Handlers: verification & admin flows (with DM restrictions)
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
    caller = update.effective_user
    chat = update.effective_chat
    # Admin-only
    if not is_admin_user(update):
        await update.message.reply_text("Only the admin can add students.")
        return ConversationHandler.END
    # If VERIFICATION_GROUP_ID configured, recommend to use there but allow admin anywhere
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
    # This flow should be used in private chat only for students; admin may use anywhere
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Verification is DM-only. Please message me privately to verify.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    user = update.effective_user
    if db_get_verified_by_tid(user.id):
        await update.message.reply_text("✅ You are already verified.", reply_markup=STUDENT_MENU)
        return ConversationHandler.END
    await update.message.reply_text("Enter your full name (min 3 characters):")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ This step must be done in private chat. Please DM the bot.")
        return ConversationHandler.END
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("Name too short. Enter at least 3 characters.")
        return VERIFY_NAME
    context.user_data["v_name"] = name
    await update.message.reply_text("Enter your phone number (e.g., +2341234567890):")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ This step must be done in private chat. Please DM the bot.")
        return ConversationHandler.END
    phone = update.message.text.strip()
    if not RE_PHONE.match(phone):
        await update.message.reply_text("Invalid phone. Use format +countrycode and digits.")
        return VERIFY_PHONE
    context.user_data["v_phone"] = phone
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ This step must be done in private chat. Please DM the bot.")
        return ConversationHandler.END
    email = update.message.text.strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email. Try again.")
        return VERIFY_EMAIL
    name = context.user_data.get("v_name")
    phone = context.user_data.get("v_phone")
    pending = db_find_pending_by_details(name, phone, email)
    if not pending and sheets_ok:
        try:
            rows = verif_ws.get_all_records()
            match_row = None
            for r in rows:
                if (r.get("email") or "").strip().lower() == email.strip().lower():
                    match_row = r
                    break
            if match_row:
                pending = {"id": None, "name": match_row.get("name"), "phone": match_row.get("phone"), "email": match_row.get("email"), "hash": match_row.get("hash") or _sha_hash(name, email, phone)}
        except Exception:
            logger.exception("Failed to query verifications sheet", exc_info=True)
    if not pending:
        await update.message.reply_text("Details not found. Contact admin or try again.", reply_markup=VERIFY_INLINE)
        context.user_data.clear()
        return ConversationHandler.END
    if hasattr(pending, "keys"):
        success = db_verify_user_by_pending(pending, update.effective_user.id)
    else:
        try:
            c.execute("INSERT OR REPLACE INTO verified_users (name, phone, email, telegram_id) VALUES (?, ?, ?, ?)", (name, phone, email, update.effective_user.id))
            conn.commit()
            if sheets_ok and verif_ws:
                try:
                    verif_ws.append_row([None, name, phone, email, update.effective_user.id, "Verified", _sha_hash(name, email, phone), datetime.datetime.utcnow().isoformat()])
                except Exception:
                    logger.exception("Failed to append verified row to sheet", exc_info=True)
            success = True
        except Exception:
            logger.exception("Failed to add verified user from sheet match", exc_info=True)
            success = False
    if success:
        try:
            await systeme_create_contact_and_tag(email, name, phone)
        except Exception:
            logger.exception("Systeme.io sync failed", exc_info=True)
        await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=STUDENT_MENU)
        await update.message.reply_text(f"Please visit: {LANDING_PAGE_LINK}")
    else:
        await update.message.reply_text("Verification failed. Contact admin.")
    context.user_data.clear()
    return ConversationHandler.END

async def verify_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    # If in group and not admin -> instruct DM
    if not is_admin_user(update) and not is_private_chat(update):
        await query.message.reply_text("❌ Please DM the bot and click Verify there (verification works only in private chat).")
        return
    if db_get_verified_by_tid(user.id):
        await query.message.reply_text("✅ You are already verified.", reply_markup=STUDENT_MENU)
        return
    c.execute("SELECT * FROM pending_verifications WHERE telegram_id = ? LIMIT 1", (user.id,))
    pending = c.fetchone()
    if pending:
        ok = db_verify_user_by_pending(pending, user.id)
        if ok:
            await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
            await query.message.reply_text("✅ Verified! Welcome.", reply_markup=STUDENT_MENU)
            return
    await query.message.reply_text("Please run /verify in DM to complete verification (we'll ask name/phone/email).")

# 3) MANUAL VERIFICATION BY ADMIN: /verify_student [email]
async def verify_student_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can manually verify.")
        return
    txt = (update.message.text or "").strip()
    parts = txt.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /verify_student user@example.com")
        return
    email = parts[1].strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email format.")
        return
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
                ok_new, h = db_add_pending(pending_row.get("name"), pending_row.get("phone"), pending_row.get("email"))
                if ok_new:
                    c.execute("SELECT * FROM pending_verifications WHERE email = ? LIMIT 1", (email,))
                    pending = c.fetchone()
        except Exception:
            logger.exception("Failed to find pending in sheet for manual verify", exc_info=True)
    if not pending:
        await update.message.reply_text(f"No pending student found with email {email}. Add with /add_student first.")
        return
    telegram_id = 0
    ok = db_verify_user_by_pending(pending, telegram_id)
    if ok:
        try:
            await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
        except Exception:
            logger.exception("Systeme.io sync failed for manual verify", exc_info=True)
        await update.message.reply_text(f"Student with email {email} verified successfully!")
    else:
        await update.message.reply_text("Failed to verify student. Check logs.")

# 4) REMOVE VERIFIED STUDENT: /remove_student [telegram_id]
async def remove_student_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can remove students.")
        return
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
    ok = db_remove_verified(target_tid)
    if ok:
        await update.message.reply_text(f"Student {target_tid} removed. They must re-verify to regain access.")
    else:
        await update.message.reply_text(f"No verified student found with Telegram ID {target_tid}.")

# -------------------------
# 5) ASSIGNMENT SUBMISSION flow (DM-only for students)
# -------------------------
async def submit_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Allow admin anywhere; students only in private chat
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Submitting assignments only works in private chat. Please DM me.")
        return ConversationHandler.END
    user = update.effective_user
    if not is_admin_user(update) and not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    await update.message.reply_text("Which module is this for? (1-12)")
    return SUBMIT_MODULE

async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ This step must be done in private chat.")
        return ConversationHandler.END
    try:
        val = int(update.message.text.strip())
        if not (1 <= val <= 12):
            raise ValueError
        context.user_data["submit_module"] = val
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Image", callback_data="media_image"), InlineKeyboardButton("Video", callback_data="media_video")]])
        await update.message.reply_text("Select media type:", reply_markup=kb)
        return SUBMIT_MEDIA_TYPE
    except Exception:
        await update.message.reply_text("Please enter a valid module number (1-12).")
        return SUBMIT_MODULE

async def submit_media_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # If in group and not admin -> ask to DM
    if not is_admin_user(update) and not is_private_chat(update):
        await q.message.reply_text("❌ Please DM the bot to submit assignments.")
        return ConversationHandler.END
    data = q.data
    if data == "media_image":
        context.user_data["submit_media_type"] = "image"
    else:
        context.user_data["submit_media_type"] = "video"
    await q.message.reply_text(f"Please send your {context.user_data['submit_media_type']} now.")
    return SUBMIT_MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Please DM the bot to upload your assignment.")
        return ConversationHandler.END
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
    if ASSIGNMENTS_GROUP_ID:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{sub_uuid}")]])
        try:
            if m_type == "image":
                await context.bot.send_photo(ASSIGNMENTS_GROUP_ID, file_id, caption=f"Submission: {username} - Module {module}: id={sub_uuid}", reply_markup=kb)
            else:
                await context.bot.send_video(ASSIGNMENTS_GROUP_ID, file_id, caption=f"Submission: {username} - Module {module}: id={sub_uuid}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward submission to assignments group", exc_info=True)
    await update.message.reply_text("Boom! Submission received!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 6) GRADING (admin-only)
# -------------------------
async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    caller = q.from_user
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return ConversationHandler.END
    payload = q.data.replace("grade_", "")
    sub_uuid = payload
    context.user_data["grade_uuid"] = sub_uuid
    buttons = [[InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
               [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]]
    await q.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup(buttons))
    return GRADE_SCORE

async def grade_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return ConversationHandler.END
    score = int(q.data.replace("score_", ""))
    context.user_data["grade_score"] = score
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Add Comment", callback_data="comment_yes"), InlineKeyboardButton("No Comment", callback_data="comment_no")]])
    await q.message.reply_text("Add a comment?", reply_markup=kb)
    return GRADE_COMMENT_TYPE

async def grade_comment_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return ConversationHandler.END
    if q.data == "comment_no":
        uuidv = context.user_data.get("grade_uuid")
        score = context.user_data.get("grade_score")
        db_set_submission_graded(uuidv, score, None, None)
        await q.message.reply_text("✅ Graded (no comment).")
        context.user_data.clear()
        return ConversationHandler.END
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Text", callback_data="comment_text"), InlineKeyboardButton("Audio", callback_data="comment_audio"), InlineKeyboardButton("Video", callback_data="comment_video")]])
        await q.message.reply_text("Choose comment type:", reply_markup=kb)
        return GRADE_COMMENT_CONTENT

async def grade_comment_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can grade.")
        return ConversationHandler.END
    ctype = context.user_data.get("grade_comment_type", "text")
    comment_content = None
    if update.message.text:
        comment_content = update.message.text.strip()
    elif update.message.audio:
        comment_content = update.message.audio.file_id
    elif update.message.video:
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

# Manual grading via /grade (admin only)
async def grade_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can use /grade.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username to grade:")
    return MANUAL_GRADE_USERNAME

async def grade_manual_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can use /grade.")
        return ConversationHandler.END
    username = update.message.text.strip()
    context.user_data["manual_grade_username"] = username
    await update.message.reply_text("Enter module number (1-12):")
    return MANUAL_GRADE_MODULE

async def grade_manual_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can use /grade.")
        return ConversationHandler.END
    try:
        mod = int(update.message.text.strip())
        if not (1 <= mod <= 12):
            raise ValueError
        username = context.user_data.get("manual_grade_username")
        c.execute("SELECT * FROM submissions WHERE username = ? AND module = ? AND status = 'Submitted' ORDER BY created_at ASC LIMIT 1", (username, mod))
        row = c.fetchone()
        if not row:
            await update.message.reply_text("No submitted assignment found for that user & module.")
            context.user_data.clear()
            return ConversationHandler.END
        context.user_data["grade_uuid"] = row["submission_uuid"]
        buttons = [[InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
                   [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]]
        await update.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup(buttons))
        return GRADE_SCORE
    except Exception:
        await update.message.reply_text("Invalid module number. Operation cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

# -------------------------
# 7) SHARE SMALL WIN (DM-only for students)
# -------------------------
async def share_win_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Sharing wins only works in private chat. Please DM me.")
        return ConversationHandler.END
    user = update.effective_user
    if not is_admin_user(update) and not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Text", callback_data="win_text"), InlineKeyboardButton("Image", callback_data="win_image"), InlineKeyboardButton("Video", callback_data="win_video")]])
    await update.message.reply_text("Choose type of win to share:", reply_markup=kb)
    return SHARE_WIN_TYPE

async def share_win_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update) and not is_private_chat(update):
        await q.message.reply_text("❌ Please DM the bot to share your win.")
        return ConversationHandler.END
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
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Please DM the bot to share your win.")
        return ConversationHandler.END
    user = update.effective_user
    username = get_display_name(user)
    tid = user.id
    wtype = context.user_data.get("win_type", "text")
    content = None
    if wtype == "text" and update.message.text:
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
            logger.exception("Failed to forward win to support group", exc_info=True)
    await update.message.reply_text("Awesome win shared!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 8) ASK A QUESTION
#    - /ask allowed in DM and SUPPORT_GROUP_ID (group)
#    - Ask inline button in group prompts DM
# -------------------------
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Allow admin anywhere
    if not is_admin_user(update):
        # Allow if private chat OR in SUPPORT_GROUP_ID group
        chat = update.effective_chat
        if not chat:
            await update.message.reply_text("Invalid chat.")
            return ConversationHandler.END
        if not (chat.type == "private" or (SUPPORT_GROUP_ID and chat.id == SUPPORT_GROUP_ID)):
            await update.message.reply_text("❌ You can only ask questions in DM or in the support group. Please DM me to ask.")
            return ConversationHandler.END
    await update.message.reply_text("What's your question? (text only)")
    return ASK_QUESTION_TEXT

async def ask_button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # If invoked in group, require DM
    if not is_admin_user(update) and not is_private_chat(update):
        await q.message.reply_text("❌ Please DM me and type /ask to submit your question.")
        return ConversationHandler.END
    await q.message.reply_text("What's your question? (text only)")
    return ASK_QUESTION_TEXT

async def ask_question_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This handler invoked after /ask or inline in DM
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Please DM me to ask a question.")
        return ConversationHandler.END
    qtext = update.message.text.strip()
    if not qtext:
        await update.message.reply_text("Please send a non-empty question.")
        return ASK_QUESTION_TEXT
    q_uuid = db_add_question(get_display_name(update.effective_user), update.effective_user.id, qtext)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{q_uuid}")]])
    if QUESTIONS_GROUP_ID:
        try:
            await context.bot.send_message(QUESTIONS_GROUP_ID, f"Question from {get_display_name(update.effective_user)} (id:{q_uuid}):\n{qtext}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward question to questions group", exc_info=True)
    await update.message.reply_text("Question sent! We'll get back to you.", reply_markup=STUDENT_MENU)
    return ConversationHandler.END

async def answer_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can answer questions.")
        return ConversationHandler.END
    q_uuid = q.data.replace("answer_", "")
    context.user_data["answer_uuid"] = q_uuid
    await q.message.reply_text("Send your answer (text/audio/video).")
    return ANSWER_QUESTION_CONTENT

async def answer_question_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can answer questions.")
        return ConversationHandler.END
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
    try:
        c.execute("UPDATE questions SET answer = ? WHERE question_uuid = ?", (str(acontent), q_uuid))
        conn.commit()
        if sheets_ok and faq_ws:
            try:
                faq_ws.append_row(["Answer", q_uuid, str(acontent), datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append answer to sheet", exc_info=True)
    except Exception:
        logger.exception("Failed to update question with answer", exc_info=True)
    c.execute("SELECT * FROM questions WHERE question_uuid = ? LIMIT 1", (q_uuid,))
    row = c.fetchone()
    if row:
        asker_id = row["telegram_id"]
        try:
            if isinstance(acontent, str):
                await context.bot.send_message(asker_id, f"Answer to your question:\n{acontent}")
            else:
                # media file_id
                # best-effort: try video then audio
                try:
                    await context.bot.send_video(asker_id, acontent, caption="Answer to your question")
                except Exception:
                    await context.bot.send_audio(asker_id, acontent, caption="Answer to your question")
        except Exception:
            logger.exception("Failed to deliver answer to asker", exc_info=True)
    await update.message.reply_text("Answer sent to student.", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# 9) CHECK STATUS (DM-only for students)
# -------------------------
ACHIEVER_MODULES = int(_env("ACHIEVER_MODULES", default="6"))
ACHIEVER_WINS = int(_env("ACHIEVER_WINS", default="3"))

async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update) and not is_private_chat(update):
        await update.message.reply_text("❌ Checking status only works in private chat. Please DM me.")
        return
    user = update.effective_user
    uid = user.id
    if not is_admin_user(update) and not db_get_verified_by_tid(uid):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return
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
        c.execute("SELECT COUNT(*) as cnt FROM wins WHERE telegram_id = ?", (uid,))
        wins_count = c.fetchone()["cnt"]
        msg = f"Completed modules: {', '.join(modules) if modules else 'None'}\nScores: {', '.join(scores) if scores else 'None'}\nWins: {wins_count}\nGraded submissions: {graded_count}"
        await update.message.reply_text(msg, reply_markup=STUDENT_MENU)
        if graded_count >= ACHIEVER_MODULES and wins_count >= ACHIEVER_WINS:
            await update.message.reply_text("🎉 AVAP Achiever Badge earned! Congratulations! 🎉", reply_markup=STUDENT_MENU)
    except Exception:
        logger.exception("Failed to compute status", exc_info=True)
        await update.message.reply_text("Failed to fetch status. Try again later.", reply_markup=STUDENT_MENU)

# -------------------------
# 10) JOIN REQUEST HANDLING
# -------------------------
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        req: ChatJoinRequest = update.chat_join_request
        user = req.from_user
        chat = req.chat
        # only handle if SUPPORT_GROUP_ID configured and matching
        if SUPPORT_GROUP_ID and chat.id != SUPPORT_GROUP_ID:
            return
        if db_get_verified_by_tid(user.id):
            try:
                await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                await context.bot.send_message(user.id, f"Welcome to {chat.title}! You were auto-approved.", reply_markup=STUDENT_MENU)
            except Exception:
                logger.exception("Failed to approve chat join request", exc_info=True)
        else:
            try:
                await context.bot.decline_chat_join_request(chat_id=chat.id, user_id=user.id)
            except Exception:
                logger.exception("Failed to decline chat join request", exc_info=True)
            try:
                await context.bot.send_message(user.id, "You need to verify first to join. Please verify with /verify or click verify button.", reply_markup=VERIFY_INLINE)
            except Exception:
                pass
    except Exception:
        logger.exception("Error in chat_join_request_handler", exc_info=True)

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
                logger.exception("Failed to send Sunday reminder to user %s", exc_info=True)
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.send_message(SUPPORT_GROUP_ID, "🌞 Sunday Reminder: Encourage students to submit and share wins!")
            except Exception:
                logger.exception("Failed to send Sunday reminder to support group", exc_info=True)
    except Exception:
        logger.exception("Failed in sunday_reminder_job", exc_info=True)

# -------------------------
# Error handler
# -------------------------
async def on_error(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error: %s", exc_info=True)
    if ADMIN_ID:
        try:
            await context.bot.send_message(ADMIN_ID, f"⚠️ Bot error: {context.error}")
        except Exception:
            logger.exception("Failed to notify admin about error", exc_info=True)

# -------------------------
# Application setup
# -------------------------
def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in env - cannot start bot")
    app = Application.builder().token(BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start_handler))

    # add student (admin flow)
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

    # verify conv (DM only enforced in handler)
    verify_conv = ConversationHandler(
        entry_points=[CommandHandler("verify", verify_start_cmd), CallbackQueryHandler(verify_now_callback, pattern="^verify_now$")],
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

    # grading handlers
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
    app.add_handler(MessageHandler(filters.Regex(r"^🎉 Share Small Win$|^Share Win$"), share_win_start))
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

    # ask conv (command & inline)
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CallbackQueryHandler(ask_button_cb, pattern="^ask_dm$"))
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", ask_command), CallbackQueryHandler(ask_button_cb, pattern="^ask_dm$")],
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

    # chat join request handler (optional)
    try:
        app.add_handler(ChatJoinRequestHandler(chat_join_request_handler))
    except Exception:
        logger.info("ChatJoinRequestHandler registration failed or unavailable; join-request flow may not work")

    # default menu fallback to start flows with DM enforcement
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: menu_text_fallback(u, c)))

    # error handler
    app.add_error_handler(on_error)

    # schedule Sunday reminder
    try:
        job_time = datetime.time(hour=18, minute=0)
        app.job_queue.run_daily(sunday_reminder_job, time=job_time, days=(6,), name="sunday_reminder")
        logger.info("Scheduled Sunday reminder job at 18:00 weekly (WAT)")
    except Exception:
        logger.exception("Failed to schedule Sunday reminder", exc_info=True)

    # callback registrations for verify and other callbacks
    app.add_handler(CallbackQueryHandler(verify_now_callback, pattern="^verify_now$"))
    app.add_handler(CallbackQueryHandler(submit_media_type_cb, pattern="^media_"))
    app.add_handler(CallbackQueryHandler(grade_comment_type_cb, pattern="^comment_"))
    app.add_handler(CallbackQueryHandler(share_win_type_cb, pattern="^win_"))
    app.add_handler(CallbackQueryHandler(answer_question_start, pattern="^answer_"))

    return app

# menu fallback mapping - enforces DM-only for features
async def menu_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    # Submit Assignment
    if text in ("📤 Submit Assignment", "Submit Assignment"):
        return await submit_start_handler(update, context)
    # Share Win
    if text in ("🎉 Share Small Win", "Share Win"):
        return await share_win_start(update, context)
    # Check Status
    if text in ("📊 Check Status", "Check Status"):
        return await check_status_handler(update, context)
    # Ask - button fallback
    if text in ("❓ Ask a Question", "Ask Question"):
        # If in group, instruct to type /ask (unless admin)
        if not is_admin_user(update) and not is_private_chat(update):
            await update.message.reply_text("❌ Please DM me and type /ask to submit your question.")
            return
        return await ask_command(update, context)
    # default
    await update.message.reply_text("Use the menu buttons in DM.", reply_markup=STUDENT_MENU)

# -------------------------
# Build and run application with FastAPI lifespan to share asyncio loop
# -------------------------
telegram_app = build_application()  # may raise if BOT_TOKEN missing

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Lifespan starting: initializing Telegram Application")
    try:
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("Telegram polling started")
    except Exception:
        logger.exception("Failed to start Telegram bot in lifespan", exc_info=True)
        raise
    try:
        yield
    finally:
        logger.info("Lifespan ending: stopping Telegram Application")
        try:
            await telegram_app.updater.stop()
        except Exception:
            logger.exception("Failed to stop updater", exc_info=True)
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception:
            logger.exception("Failed to stop/shutdown Telegram Application", exc_info=True)

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
