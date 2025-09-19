#!/usr/bin/env python3
"""
AVAP Support Bot - Full, ready-to-deploy version.

Notes:
- Deploy as a Render Background Worker (command: python bot.py).
- All student features are DM-only except /ask which works in DM and in SUPPORT_GROUP_ID.
- Admin-only actions are gated by ADMIN_ID environment variable.
"""

import os
import re
import json
import uuid
import sqlite3
import hashlib
import logging
import datetime
from typing import Optional, Tuple

import httpx
import gspread
from google.oauth2.service_account import Credentials

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
# ENV / CONFIG (load from environment)
# -------------------------
def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key, default)
    logger.info("Loaded env %s -> %s", key, bool(v))
    return v

BOT_TOKEN = _env("BOT_TOKEN")
ADMIN_ID = int(_env("ADMIN_ID") or 0) if _env("ADMIN_ID") else None
SUPPORT_GROUP_ID = int(_env("SUPPORT_GROUP_ID") or 0) if _env("SUPPORT_GROUP_ID") else None
ASSIGNMENTS_GROUP_ID = int(_env("ASSIGNMENTS_GROUP_ID") or 0) if _env("ASSIGNMENTS_GROUP_ID") else None
QUESTIONS_GROUP_ID = int(_env("QUESTIONS_GROUP_ID") or 0) if _env("QUESTIONS_GROUP_ID") else None
VERIFICATION_GROUP_ID = int(_env("VERIFICATION_GROUP_ID") or 0) if _env("VERIFICATION_GROUP_ID") else None

GOOGLE_CREDENTIALS = _env("GOOGLE_CREDENTIALS")
GOOGLE_SHEET_ID = _env("GOOGLE_SHEET_ID")

SYSTEME_API_KEY = _env("SYSTEME_API_KEY")
SYSTEME_VERIFIED_TAG_ID = _env("SYSTEME_VERIFIED_TAG_ID")

LANDING_PAGE_LINK = _env("LANDING_PAGE_LINK", default="https://example.com")
ACHIEVER_MODULES = int(_env("ACHIEVER_MODULES", default="6"))
ACHIEVER_WINS = int(_env("ACHIEVER_WINS", default="3"))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set. Exiting.")
    raise SystemExit("BOT_TOKEN is required in environment")

# -------------------------
# Validations
# -------------------------
RE_PHONE = re.compile(r"^\+\d{10,15}$")
RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# -------------------------
# Keyboards
# -------------------------
STUDENT_MENU = ReplyKeyboardMarkup(
    [["📤 Submit Assignment", "🎉 Share Small Win"], ["📊 Check Status", "❓ Ask a Question"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

VERIFY_INLINE = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Verify Now", callback_data="verify_now")]])
ASK_INLINE = InlineKeyboardMarkup([[InlineKeyboardButton("❓ Ask a Question", callback_data="ask_dm")]])

# -------------------------
# Conversation states
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
# SQLite DB
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
    answer_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""
)
conn.commit()

# -------------------------
# Google Sheets init (optional)
# -------------------------
sheets_ok = False
gclient = None
sheet = None
verif_ws = assignments_ws = wins_ws = faq_ws = None

if GOOGLE_CREDENTIALS and GOOGLE_SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDENTIALS),
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
        )
        gclient = gspread.authorize(creds)
        sheet = gclient.open_by_key(GOOGLE_SHEET_ID)

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
        faq_ws = _ensure_ws("Questions", ["username", "telegram_id", "question", "answer", "question_uuid", "answer_type", "created_at"])
        sheets_ok = True
        logger.info("Google Sheets connected")
    except Exception:
        logger.exception("Google Sheets init failed; continuing without Sheets")
        sheets_ok = False
else:
    logger.info("Google Sheets not configured; continuing without Sheets")

# -------------------------
# Helpers: DB + sheets
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
        if sheets_ok and verif_ws:
            try:
                verif_ws.append_row([None, name, phone, email, 0, "Pending", h, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append pending to sheet")
        logger.info("Pending verification added: %s", email)
        return True, h
    except sqlite3.IntegrityError:
        logger.warning("Pending verification exists already for %s", email)
        return False, None
    except Exception:
        logger.exception("Failed to add pending", exc_info=True)
        return False, None

def db_find_pending_by_details(name: str, phone: str, email: str):
    c.execute("SELECT * FROM pending_verifications WHERE name = ? AND phone = ? AND email = ? LIMIT 1", (name, phone, email))
    return c.fetchone()

def db_find_pending_by_email(email: str):
    c.execute("SELECT * FROM pending_verifications WHERE email = ? LIMIT 1", (email,))
    return c.fetchone()

def db_verify_user_by_pending(pending_row, telegram_id: int) -> bool:
    try:
        name = pending_row["name"]
        phone = pending_row["phone"]
        email = pending_row["email"]
        c.execute("INSERT OR REPLACE INTO verified_users (name, phone, email, telegram_id) VALUES (?, ?, ?, ?)", (name, phone, email, telegram_id))
        conn.commit()
        c.execute("UPDATE pending_verifications SET telegram_id = ?, status = 'Verified' WHERE id = ?", (telegram_id, pending_row["id"]))
        conn.commit()
        if sheets_ok and verif_ws:
            try:
                verif_ws.append_row([None, name, phone, email, telegram_id, "Verified", pending_row["hash"], datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append verified to sheet")
        logger.info("User verified: %s -> %s", email, telegram_id)
        return True
    except Exception:
        logger.exception("Failed to verify user", exc_info=True)
        return False

def db_manual_verify_by_email(email: str, telegram_id: Optional[int] = 0) -> bool:
    r = db_find_pending_by_email(email)
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
                logger.exception("Failed to append removal to sheet")
        logger.info("Removed verified user: %s", telegram_id)
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
                logger.exception("Failed to append submission to sheet")
        logger.info("Submission saved: %s by %s", sub_uuid, username)
        return sub_uuid
    except Exception:
        logger.exception("Failed to add submission", exc_info=True)
        return sub_uuid

def db_set_submission_graded(sub_uuid: str, score: int, comment_type: Optional[str], comment_content: Optional[str]):
    try:
        c.execute("UPDATE submissions SET status='Graded', score=?, comment_type=?, comment_content=? WHERE submission_uuid = ?", (score, comment_type, comment_content, sub_uuid))
        conn.commit()
        if sheets_ok and assignments_ws:
            try:
                assignments_ws.append_row(["Graded", sub_uuid, score, comment_type or "", comment_content or "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append graded to sheet")
        logger.info("Submission graded: %s -> %s", sub_uuid, score)
        return True
    except Exception:
        logger.exception("Failed to set submission graded", exc_info=True)
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
        logger.info("Win added: %s by %s", content_type, username)
        return True
    except Exception:
        logger.exception("Failed to add win", exc_info=True)
        return False

def db_add_question(username: str, telegram_id: int, question_text: str) -> str:
    q_uuid = str(uuid.uuid4())
    try:
        c.execute("INSERT INTO questions (username, telegram_id, question, question_uuid) VALUES (?, ?, ?, ?)", (username, telegram_id, question_text, q_uuid))
        conn.commit()
        if sheets_ok and faq_ws:
            try:
                faq_ws.append_row([username, telegram_id, question_text, "", q_uuid, "", datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append question to sheet")
        logger.info("Question added: %s by %s", q_uuid, username)
        return q_uuid
    except Exception:
        logger.exception("Failed to add question", exc_info=True)
        return q_uuid

def db_get_verified_by_tid(telegram_id: int):
    c.execute("SELECT * FROM verified_users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
    return c.fetchone()

# -------------------------
# Systeme.io integration (optional)
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
                if SYSTEME_VERIFIED_TAG_ID and contact_id:
                    try:
                        await client.post(f"https://api.systeme.io/api/contacts/{contact_id}/tags", headers=headers, json={"tag_id": SYSTEME_VERIFIED_TAG_ID})
                    except Exception:
                        logger.exception("Failed to tag contact in Systeme.io")
                logger.info("Systeme.io contact created/tagged for %s", email)
                return True
            elif resp.status_code in (409, 422):
                logger.info("Systeme.io contact may already exist: %s", resp.status_code)
                return True
            else:
                logger.warning("Unexpected Systeme.io response: %s", resp.status_code)
                return False
        except Exception:
            logger.exception("Systeme.io sync error")
            return False

# -------------------------
# Utilities & ACL
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

def require_dm_only(update: Update) -> bool:
    """Return True if allowed (DM or admin), else False."""
    if is_admin_user(update):
        return True
    if is_private_chat(update):
        return True
    return False

# -------------------------
# Handlers
# -------------------------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user = update.effective_user
    if db_get_verified_by_tid(user.id):
        await update.message.reply_text("✅ You're verified. Choose an action:", reply_markup=STUDENT_MENU)
    else:
        await update.message.reply_text("Welcome! Please verify to access features.", reply_markup=VERIFY_INLINE)

# ---- Admin: add student
async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can add students.")
        return ConversationHandler.END
    await update.message.reply_text("Enter student's full name (min 3 characters):")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if len(text) < 3:
        await update.message.reply_text("Name too short.")
        return ADD_STUDENT_NAME
    context.user_data["add_name"] = text
    await update.message.reply_text("Enter student's phone number (e.g., +2341234567890):")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = (update.message.text or "").strip()
    if not RE_PHONE.match(phone):
        await update.message.reply_text("Invalid phone format.")
        return ADD_STUDENT_PHONE
    context.user_data["add_phone"] = phone
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = (update.message.text or "").strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email.")
        return ADD_STUDENT_EMAIL
    name = context.user_data.get("add_name")
    phone = context.user_data.get("add_phone")
    ok, h = db_add_pending(name, phone, email)
    if ok:
        await update.message.reply_text(f"Student {name} added (Pending). Admins can manually verify with /verify_student [email].")
    else:
        await update.message.reply_text("Failed to add student; record may exist.")
    context.user_data.clear()
    return ConversationHandler.END

# ---- Student verification
async def verify_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow DM verification (admins can use anywhere)
    if not require_dm_only(update):
        await update.message.reply_text("❌ Verification is DM-only. Please DM me.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    user = update.effective_user
    if db_get_verified_by_tid(user.id):
        await update.message.reply_text("✅ You are already verified.", reply_markup=STUDENT_MENU)
        return ConversationHandler.END
    await update.message.reply_text("Enter your full name (min 3 characters):")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ This step must be done in private chat.")
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if len(name) < 3:
        await update.message.reply_text("Name too short.")
        return VERIFY_NAME
    context.user_data["v_name"] = name
    await update.message.reply_text("Enter your phone number (e.g., +2341234567890):")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ This step must be done in private chat.")
        return ConversationHandler.END
    phone = (update.message.text or "").strip()
    if not RE_PHONE.match(phone):
        await update.message.reply_text("Invalid phone")
        return VERIFY_PHONE
    context.user_data["v_phone"] = phone
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ This step must be done in private chat.")
        return ConversationHandler.END
    email = (update.message.text or "").strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email")
        return VERIFY_EMAIL
    name = context.user_data.get("v_name")
    phone = context.user_data.get("v_phone")
    pending = db_find_pending_by_details(name, phone, email)
    # fallback: check sheet
    if not pending and sheets_ok:
        try:
            rows = verif_ws.get_all_records()
            for r in rows:
                if (r.get("email") or "").strip().lower() == email.strip().lower():
                    pending = {"id": None, "name": r.get("name"), "phone": r.get("phone"), "email": r.get("email"), "hash": r.get("hash") or _sha_hash(name, email, phone)}
                    break
        except Exception:
            logger.exception("Sheet lookup failed in verify_email")
    if not pending:
        await update.message.reply_text("Details not found. Contact admin or try again.", reply_markup=VERIFY_INLINE)
        context.user_data.clear()
        return ConversationHandler.END
    # verify and sync
    if hasattr(pending, "keys"):
        success = db_verify_user_by_pending(pending, update.effective_user.id)
    else:
        try:
            c.execute("INSERT OR REPLACE INTO verified_users (name, phone, email, telegram_id) VALUES (?, ?, ?, ?)",
                      (name, phone, email, update.effective_user.id))
            conn.commit()
            success = True
            if sheets_ok and verif_ws:
                try:
                    verif_ws.append_row([None, name, phone, email, update.effective_user.id, "Verified", _sha_hash(name, email, phone), datetime.datetime.utcnow().isoformat()])
                except Exception:
                    logger.exception("Failed to append verified row")
        except Exception:
            logger.exception("Failed to insert verified", exc_info=True)
            success = False
    if success:
        try:
            await systeme_create_contact_and_tag(email, name, phone)
        except Exception:
            logger.exception("Systeme sync failed")
        await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=STUDENT_MENU)
        await update.message.reply_text(f"Please visit: {LANDING_PAGE_LINK}")
    else:
        await update.message.reply_text("Verification failed. Contact admin.")
    context.user_data.clear()
    return ConversationHandler.END

async def verify_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # If callback pressed in group and user not admin, require DM
    if not require_dm_only(update) and not is_admin_user(update):
        await q.message.reply_text("❌ Please DM the bot to verify.")
        return
    user = q.from_user
    if db_get_verified_by_tid(user.id):
        await q.message.reply_text("You are already verified.", reply_markup=STUDENT_MENU)
        return
    # Try to verify if admin added telegram_id to pending (rare)
    c.execute("SELECT * FROM pending_verifications WHERE telegram_id = ? LIMIT 1", (user.id,))
    pending = c.fetchone()
    if pending:
        ok = db_verify_user_by_pending(pending, user.id)
        if ok:
            await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
            await q.message.reply_text("✅ Verified! Welcome.", reply_markup=STUDENT_MENU)
            return
    await q.message.reply_text("Please run /verify in DM to complete verification.")

# ---- Manual verification by admin
async def verify_student_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can manually verify.")
        return
    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /verify_student email@example.com")
        return
    email = parts[1].strip()
    if not RE_EMAIL.match(email):
        await update.message.reply_text("Invalid email.")
        return
    pending = db_find_pending_by_email(email)
    if not pending and sheets_ok:
        try:
            rows = verif_ws.get_all_records()
            for r in rows:
                if (r.get("email") or "").strip().lower() == email.lower():
                    ok_new, h = db_add_pending(r.get("name"), r.get("phone"), r.get("email"))
                    if ok_new:
                        pending = db_find_pending_by_email(email)
                    break
        except Exception:
            logger.exception("Sheet query failed")
    if not pending:
        await update.message.reply_text(f"No pending student found with email {email}. Add with /add_student.")
        return
    ok = db_verify_user_by_pending(pending, 0)
    if ok:
        await systeme_create_contact_and_tag(pending["email"], pending["name"], pending["phone"])
        await update.message.reply_text(f"Student with email {email} verified successfully!")
    else:
        await update.message.reply_text("Failed to verify student.")

# ---- Remove verified student
async def remove_student_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can remove students.")
        return
    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /remove_student <telegram_id>")
        return
    try:
        target = int(parts[1].strip())
    except ValueError:
        await update.message.reply_text("Invalid telegram id.")
        return
    ok = db_remove_verified(target)
    if ok:
        await update.message.reply_text(f"Student {target} removed.")
    else:
        await update.message.reply_text("No verified student found with that ID.")

# -------------------------
# Submission flow (DM-only)
# -------------------------
async def submit_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ Submitting assignments only works in private chat. Please DM me.")
        return ConversationHandler.END
    user = update.effective_user
    if not is_admin_user(update) and not db_get_verified_by_tid(user.id):
        await update.message.reply_text("Please verify first.", reply_markup=VERIFY_INLINE)
        return ConversationHandler.END
    await update.message.reply_text("Which module? (1-12)")
    return SUBMIT_MODULE

async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ This step must be done in private chat.")
        return ConversationHandler.END
    try:
        module = int((update.message.text or "").strip())
        if module < 1 or module > 12:
            raise ValueError
    except Exception:
        await update.message.reply_text("Invalid module number (1-12).")
        return SUBMIT_MODULE
    context.user_data["submit_module"] = module
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Image", callback_data="media_image"), InlineKeyboardButton("Video", callback_data="media_video")]])
    await update.message.reply_text("Select media type:", reply_markup=kb)
    return SUBMIT_MEDIA_TYPE

async def submit_media_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not require_dm_only(update):
        await q.message.reply_text("❌ Please DM the bot to submit assignments.")
        return ConversationHandler.END
    data = q.data
    context.user_data["submit_media_type"] = "image" if data == "media_image" else "video"
    await q.message.reply_text(f"Please send your {context.user_data['submit_media_type']} now.")
    return SUBMIT_MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ Please DM the bot to upload your assignment.")
        return ConversationHandler.END
    user = update.effective_user
    username = get_display_name(user)
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
    sub_uuid = db_add_submission(username, user.id, module, m_type, file_id)
    # Forward to assignments group with Grade button
    if ASSIGNMENTS_GROUP_ID:
        try:
            caption = f"Submission from {username} - Module {module} - id:{sub_uuid}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{sub_uuid}")]])
            if m_type == "image":
                await context.bot.send_photo(ASSIGNMENTS_GROUP_ID, file_id, caption=caption, reply_markup=kb)
            else:
                await context.bot.send_video(ASSIGNMENTS_GROUP_ID, file_id, caption=caption, reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward submission to assignments group", exc_info=True)
    await update.message.reply_text("Submission received!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# Grading (clean flow)
# -------------------------
def make_score_kb():
    buttons = [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 11)]
    return InlineKeyboardMarkup([buttons[:5], buttons[5:]])

def make_comment_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Add Comment", callback_data="comment_yes"), InlineKeyboardButton("No Comment", callback_data="comment_no")]])

async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return
    sub_uuid = q.data.replace("grade_", "")
    context.chat_data["grade_uuid"] = sub_uuid
    # remove inline keyboard from original submission message
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        try:
            await q.message.delete()
        except Exception:
            pass
    # send score selection message in group (clean)
    try:
        sent = await context.bot.send_message(q.message.chat_id, f"Grading submission id: {sub_uuid}\nSelect score (1-10):", reply_markup=make_score_kb())
        context.chat_data["grading_msg_id"] = sent.message_id
    except Exception:
        logger.exception("Failed to send score selection", exc_info=True)

async def grade_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return
    score = int(q.data.replace("score_", ""))
    context.chat_data["grade_score"] = score
    # delete the score selection message
    try:
        await q.message.delete()
    except Exception:
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    # ask for comment or not (in group)
    try:
        sent = await context.bot.send_message(q.message.chat_id, "Add a comment?", reply_markup=make_comment_kb())
        context.chat_data["comment_prompt_msg_id"] = sent.message_id
    except Exception:
        logger.exception("Failed to send comment prompt", exc_info=True)

async def grade_comment_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can grade.")
        return
    # delete comment prompt message to keep group clean
    try:
        await q.message.delete()
    except Exception:
        try:
            await q.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    sub_uuid = context.chat_data.get("grade_uuid")
    score = context.chat_data.get("grade_score")
    if q.data == "comment_no":
        # finalize grading without comment
        db_set_submission_graded(sub_uuid, score, None, None)
        try:
            await context.bot.send_message(q.message.chat_id, f"✅ Graded: {score}/10 - id:{sub_uuid}")
        except Exception:
            pass
        # notify student
        try:
            c.execute("SELECT telegram_id FROM submissions WHERE submission_uuid = ? LIMIT 1", (sub_uuid,))
            r = c.fetchone()
            if r:
                student_tid = r["telegram_id"]
                await context.bot.send_message(student_tid, f"Your submission (id:{sub_uuid}) was graded: {score}/10. No comment.")
        except Exception:
            logger.exception("Failed to notify student", exc_info=True)
        context.chat_data.pop("grade_uuid", None)
        context.chat_data.pop("grade_score", None)
    else:
        # admin will DM a comment - instruct admin via DM
        sub_uuid = context.chat_data.get("grade_uuid")
        score = context.chat_data.get("grade_score")
        context.user_data["awaiting_grade_comment"] = True
        # send DM to admin requesting actual comment
        try:
            await context.bot.send_message(ADMIN_ID, f"Please send your comment (text/audio/video) for submission id:{sub_uuid} (score: {score}). Reply here with the content.")
            await context.bot.send_message(q.message.chat_id, "Admin will DM comment privately. Group cleaned.")
        except Exception:
            logger.exception("Failed to DM admin for comment", exc_info=True)

# admin comment input handler (DM)
async def grade_comment_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        return
    if not context.user_data.get("awaiting_grade_comment"):
        return
    sub_uuid = context.user_data.get("grade_uuid")
    score = context.user_data.get("grade_score")
    comment_type = None
    comment_content = None
    if update.message.text:
        comment_type = "text"
        comment_content = update.message.text.strip()
    elif update.message.audio:
        comment_type = "audio"
        comment_content = update.message.audio.file_id
    elif update.message.video:
        comment_type = "video"
        comment_content = update.message.video.file_id
    else:
        await update.message.reply_text("Please send text, audio, or video as comment.")
        return
    db_set_submission_graded(sub_uuid, score, comment_type, str(comment_content))
    # notify student privately
    try:
        c.execute("SELECT telegram_id FROM submissions WHERE submission_uuid = ? LIMIT 1", (sub_uuid,))
        r = c.fetchone()
        if r:
            student_tid = r["telegram_id"]
            if comment_type == "text":
                await context.bot.send_message(student_tid, f"Your submission (id:{sub_uuid}) was graded: {score}/10\nComment: {comment_content}")
            elif comment_type == "audio":
                await context.bot.send_audio(student_tid, comment_content, caption=f"Your submission (id:{sub_uuid}) graded: {score}/10")
            elif comment_type == "video":
                await context.bot.send_video(student_tid, comment_content, caption=f"Your submission (id:{sub_uuid}) graded: {score}/10")
    except Exception:
        logger.exception("Failed to send graded comment to student", exc_info=True)
    # notify assignments group with clean message
    if ASSIGNMENTS_GROUP_ID:
        try:
            await context.bot.send_message(ASSIGNMENTS_GROUP_ID, f"✅ Graded: {score}/10 - id:{sub_uuid}")
        except Exception:
            logger.exception("Failed to send final graded message to assignments group", exc_info=True)
    await update.message.reply_text("Comment saved and forwarded to student.")
    context.user_data.pop("awaiting_grade_comment", None)
    context.user_data.pop("grade_uuid", None)
    context.user_data.pop("grade_score", None)
    return ConversationHandler.END

# Manual grading conv
async def grade_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        await update.message.reply_text("Only admin can use /grade.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username to grade:")
    return MANUAL_GRADE_USERNAME

async def grade_manual_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        return ConversationHandler.END
    username = (update.message.text or "").strip()
    context.user_data["manual_grade_username"] = username
    await update.message.reply_text("Enter module number (1-12):")
    return MANUAL_GRADE_MODULE

async def grade_manual_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        return ConversationHandler.END
    try:
        module = int((update.message.text or "").strip())
        if not (1 <= module <= 12):
            raise ValueError
    except Exception:
        await update.message.reply_text("Invalid module.")
        return ConversationHandler.END
    username = context.user_data.get("manual_grade_username")
    c.execute("SELECT * FROM submissions WHERE username = ? AND module = ? AND status = 'Submitted' ORDER BY created_at ASC LIMIT 1", (username, module))
    row = c.fetchone()
    if not row:
        await update.message.reply_text("No submitted assignment found.")
        context.user_data.clear()
        return ConversationHandler.END
    sub_uuid = row["submission_uuid"]
    context.user_data["grade_uuid"] = sub_uuid
    try:
        await update.message.reply_text(f"Grading submission id:{sub_uuid}\nSelect score (1-10):", reply_markup=make_score_kb())
    except Exception:
        logger.exception("Failed to send score selection in manual grade")
    return GRADE_SCORE

# -------------------------
# Share Win (DM-only)
# -------------------------
async def share_win_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
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
    if not require_dm_only(update):
        await q.message.reply_text("❌ Please DM the bot to share your win.")
        return ConversationHandler.END
    data = q.data
    if data == "win_text":
        context.user_data["win_type"] = "text"
        await q.message.reply_text("Send your win text now:")
    elif data == "win_image":
        context.user_data["win_type"] = "image"
        await q.message.reply_text("Send your image now:")
    else:
        context.user_data["win_type"] = "video"
        await q.message.reply_text("Send your video now:")
    return SHARE_WIN_UPLOAD

async def share_win_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
        await update.message.reply_text("❌ Please DM the bot to share your win.")
        return ConversationHandler.END
    user = update.effective_user
    username = get_display_name(user)
    tid = user.id
    wtype = context.user_data.get("win_type", "text")
    content = None
    if wtype == "text":
        if not (update.message and update.message.text and update.message.text.strip()):
            await update.message.reply_text("Please send non-empty text.")
            return SHARE_WIN_UPLOAD
        content = update.message.text.strip()
    elif wtype == "image":
        if not update.message.photo:
            await update.message.reply_text("Please send an image.")
            return SHARE_WIN_UPLOAD
        content = update.message.photo[-1].file_id
    elif wtype == "video":
        if not update.message.video:
            await update.message.reply_text("Please send a video.")
            return SHARE_WIN_UPLOAD
        content = update.message.video.file_id
    else:
        await update.message.reply_text("Unknown type.")
        return ConversationHandler.END

    db_add_win(username, tid, wtype, str(content))

    # Forward to support group
    if SUPPORT_GROUP_ID:
        try:
            if wtype == "text":
                await context.bot.send_message(SUPPORT_GROUP_ID, f"Win from {username}:\n{content}")
            elif wtype == "image":
                await context.bot.send_photo(SUPPORT_GROUP_ID, content, caption=f"Win from {username}")
            elif wtype == "video":
                await context.bot.send_video(SUPPORT_GROUP_ID, content, caption=f"Win from {username}")
        except Exception:
            logger.exception("Failed to forward win to support group", exc_info=True)

    await update.message.reply_text("Awesome win shared!", reply_markup=STUDENT_MENU)
    context.user_data.clear()
    return ConversationHandler.END

# -------------------------
# Ask question (DM or SUPPORT_GROUP_ID only)
# -------------------------
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat and chat.type != "private" and (SUPPORT_GROUP_ID and chat.id != SUPPORT_GROUP_ID):
        await update.message.reply_text("❌ Ask only works in private chat or in the support group.")
        return ConversationHandler.END
    await update.message.reply_text("What's your question? (text only)")
    return ASK_QUESTION_TEXT

async def ask_button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # Only allow pressing the inline ask button in DM or support group
    if not is_private_chat(update) and not (SUPPORT_GROUP_ID and q.message.chat_id == SUPPORT_GROUP_ID):
        await q.message.reply_text("❌ Please DM me and type /ask to submit your question.")
        return ConversationHandler.END
    await q.message.reply_text("What's your question? (text only)")
    return ASK_QUESTION_TEXT

async def ask_question_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update) and not (update.effective_chat and update.effective_chat.id == SUPPORT_GROUP_ID):
        await update.message.reply_text("❌ Please DM me to ask a question or use the support group /ask.")
        return ConversationHandler.END
    qtext = (update.message.text or "").strip()
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

# ---- Answer handling (admin)
async def answer_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin_user(update):
        await q.message.reply_text("Only admin can answer questions.")
        return ConversationHandler.END
    q_uuid = q.data.replace("answer_", "")
    context.user_data["answer_uuid"] = q_uuid
    try:
        await context.bot.send_message(ADMIN_ID, f"Please send your answer (text/audio/video) for question id: {q_uuid}. Reply here and I'll forward it to the asker.")
        await q.message.reply_text("Admin will DM the answer privately.")
    except Exception:
        logger.exception("Failed to request answer DM from admin", exc_info=True)
    return ANSWER_QUESTION_CONTENT

async def answer_question_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update):
        return ConversationHandler.END
    if not context.user_data.get("answer_uuid"):
        await update.message.reply_text("No question pending to answer.")
        return ConversationHandler.END
    a_uuid = context.user_data.get("answer_uuid")
    answer_type = None
    answer_content = None
    if update.message.text:
        answer_type = "text"
        answer_content = update.message.text.strip()
    elif update.message.audio:
        answer_type = "audio"
        answer_content = update.message.audio.file_id
    elif update.message.video:
        answer_type = "video"
        answer_content = update.message.video.file_id
    else:
        await update.message.reply_text("Please send text, audio, or video as answer.")
        return ANSWER_QUESTION_CONTENT
    try:
        c.execute("UPDATE questions SET answer = ?, answer_type = ? WHERE question_uuid = ?", (str(answer_content), answer_type, a_uuid))
        conn.commit()
        if sheets_ok and faq_ws:
            try:
                faq_ws.append_row(["Answer", a_uuid, str(answer_content), answer_type, datetime.datetime.utcnow().isoformat()])
            except Exception:
                logger.exception("Failed to append answer to sheet", exc_info=True)
    except Exception:
        logger.exception("Failed to update question", exc_info=True)
    try:
        c.execute("SELECT telegram_id FROM questions WHERE question_uuid = ? LIMIT 1", (a_uuid,))
        r = c.fetchone()
        if r:
            asker_id = r["telegram_id"]
            try:
                if answer_type == "text":
                    await context.bot.send_message(asker_id, f"Answer to your question:\n{answer_content}")
                elif answer_type == "audio":
                    await context.bot.send_audio(asker_id, answer_content, caption="Answer to your question")
                elif answer_type == "video":
                    await context.bot.send_video(asker_id, answer_content, caption="Answer to your question")
                await update.message.reply_text("Answer sent to student.")
            except Exception:
                logger.exception("Failed to deliver answer to asker", exc_info=True)
        else:
            await update.message.reply_text("Asker not found; saved answer in DB.")
    except Exception:
        logger.exception("Failed to fetch question asker", exc_info=True)
    context.user_data.pop("answer_uuid", None)
    return ConversationHandler.END

# -------------------------
# Check status (DM-only)
# -------------------------
async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not require_dm_only(update):
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
            await update.message.reply_text("🎉 AVAP Achiever Badge earned! Congratulations!", reply_markup=STUDENT_MENU)
    except Exception:
        logger.exception("Failed to compute status", exc_info=True)
        await update.message.reply_text("Failed to fetch status. Try again later.", reply_markup=STUDENT_MENU)

# -------------------------
# Chat join request handling (approve verified users)
# -------------------------
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        req: ChatJoinRequest = update.chat_join_request
        user = req.from_user
        chat = req.chat
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
        logger.exception("Error in join request handler", exc_info=True)

# -------------------------
# Sunday reminder job
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
                logger.exception("Failed to send reminder to user", exc_info=True)
        if SUPPORT_GROUP_ID:
            try:
                await context.bot.send_message(SUPPORT_GROUP_ID, "🌞 Sunday Reminder: Encourage students to submit and share wins!")
            except Exception:
                logger.exception("Failed to send Sunday reminder to support group", exc_info=True)
    except Exception:
        logger.exception("Failed in sunday_reminder_job", exc_info=True)

# -------------------------
# Error handling
# -------------------------
async def on_error(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error in update", exc_info=True)
    if ADMIN_ID:
        try:
            await context.bot.send_message(ADMIN_ID, f"⚠️ Bot error: {context.error}")
        except Exception:
            logger.exception("Failed to notify admin about error", exc_info=True)

# -------------------------
# Build application and register handlers
# -------------------------
def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # core commands
    app.add_handler(CommandHandler("start", start_handler))

    # add student conv (admin only)
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

    # verify conv
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

    app.add_handler(CommandHandler("verify_student", verify_student_manual))
    app.add_handler(CommandHandler("remove_student", remove_student_handler))

    # submission conv
    submit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📤 Submit Assignment$") | filters.Regex(r"^Submit Assignment$"), submit_start_handler)],
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
    app.add_handler(CallbackQueryHandler(grade_score_cb, pattern="^score_"))
    app.add_handler(CallbackQueryHandler(grade_comment_type_cb, pattern="^comment_"))

    manual_grade_conv = ConversationHandler(
        entry_points=[CommandHandler("grade", grade_manual_start)],
        states={
            MANUAL_GRADE_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_username)],
            MANUAL_GRADE_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_module)],
            GRADE_SCORE: [CallbackQueryHandler(grade_score_cb, pattern="^score_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(manual_grade_conv)

    # capture admin grade comment DM
    if ADMIN_ID:
        app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), grade_comment_content_handler))

    # share win conv
    share_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🎉 Share Small Win$") | filters.Regex(r"^Share Win$"), share_win_start)],
        states={
            SHARE_WIN_TYPE: [CallbackQueryHandler(share_win_type_cb, pattern="^win_")],
            SHARE_WIN_UPLOAD: [MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, share_win_upload_handler)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(share_conv)
    app.add_handler(CallbackQueryHandler(share_win_type_cb, pattern="^win_"))

    # ask conv
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", ask_command), CallbackQueryHandler(ask_button_cb, pattern="^ask_dm$")],
        states={ASK_QUESTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_text_handler)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(ask_conv)

    # answer conv
    app.add_handler(CallbackQueryHandler(answer_question_start, pattern="^answer_"))
    if ADMIN_ID:
        app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), answer_question_content_handler))

    # status
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Check Status$|^Check Status$|^/status$"), check_status_handler))

    # chat join requests
    try:
        app.add_handler(ChatJoinRequestHandler(chat_join_request_handler))
    except Exception:
        logger.info("ChatJoinRequestHandler didn't register on this environment")

    # fallback menu
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: menu_text_fallback(u, c)))

    # error handler
    app.add_error_handler(on_error)

    # schedule sunday reminder (attempt; job_queue available after start)
    try:
        job_time = datetime.time(hour=18, minute=0)
        app.job_queue.run_daily(sunday_reminder_job, time=job_time, days=(6,), name="sunday_reminder")
        logger.info("Scheduled Sunday reminder job")
    except Exception:
        logger.exception("Failed to schedule Sunday reminder")

    # additional cb handlers
    app.add_handler(CallbackQueryHandler(verify_now_callback, pattern="^verify_now$"))
    app.add_handler(CallbackQueryHandler(submit_media_type_cb, pattern="^media_"))
    app.add_handler(CallbackQueryHandler(answer_question_start, pattern="^answer_"))

    return app

# fallback menu handler function (non-async wrapper used earlier)
async def menu_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text in ("📤 Submit Assignment", "Submit Assignment"):
        return await submit_start_handler(update, context)
    if text in ("🎉 Share Small Win", "Share Win"):
        return await share_win_start(update, context)
    if text in ("📊 Check Status", "Check Status"):
        return await check_status_handler(update, context)
    if text in ("❓ Ask a Question", "Ask Question"):
        if not is_private_chat(update) and not (SUPPORT_GROUP_ID and update.message.chat_id == SUPPORT_GROUP_ID):
            await update.message.reply_text("❌ Please DM me and type /ask to submit your question.")
            return
        return await ask_command(update, context)
    await update.message.reply_text("Use the menu buttons in DM.", reply_markup=STUDENT_MENU)

# -------------------------
# Entrypoint (run in main thread)
# -------------------------
def main():
    logger.info("Building Telegram Application")
    app = build_application()
    logger.info("Application built - starting polling (blocking).")
    # This is the recommended blocking call. Run this as the main process (Render background worker)
    try:
        app.run_polling(close_loop=False)
    except Exception:
        logger.exception("Application run_polling failed", exc_info=True)

if __name__ == "__main__":
    main()
