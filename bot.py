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
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # optional: full JSON in env
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")  # e.g. https://your-app.onrender.com
PORT = int(os.getenv("PORT", "8080"))
TZ = pytz.timezone(os.getenv("TZ", "Africa/Lagos"))

# Achiever criteria
ACHIEVER_MODULES = int(os.getenv("ACHIEVER_MODULES", "6"))
ACHIEVER_WINS = int(os.getenv("ACHIEVER_WINS", "3"))

# -----------------------------------------------------------------------------
# SQLite setup
# -----------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "avap_bot.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

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

# -----------------------------------------------------------------------------
# Google Sheets setup (optional)
# -----------------------------------------------------------------------------
sheets_ok = False
gspread_client = None
sheet = None

def _ensure_ws(name, headers):
    try:
        wks = sheet.worksheet(name)
    except Exception:
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
        # ensure basic sheets
        ver_ws = _ensure_ws("Verifications", ["name", "email", "phone", "telegram_id", "status", "hash"])
        assignments_ws = _ensure_ws("Assignments", ["username", "telegram_id", "module", "status", "file_id", "file_type", "submission_uuid", "created_at", "score", "comment_type", "comment_content"])
        wins_ws = _ensure_ws("Wins", ["username", "telegram_id", "content_type", "content", "created_at"])
        faq_ws = _ensure_ws("Questions", ["username", "telegram_id", "question", "answer", "question_uuid", "answer_type", "created_at"])
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

def find_pending_by_hash(h):
    cursor.execute("SELECT id,name,email,phone,telegram_id,status FROM pending_verifications WHERE hash=?", (h,))
    return cursor.fetchone()

def find_pending_by_email(email):
    cursor.execute("SELECT id,name,email,phone,telegram_id,status,hash FROM pending_verifications WHERE email=?", (email,))
    return cursor.fetchone()

def mark_verified(name, email, phone, telegram_id):
    cursor.execute("INSERT INTO verified_users (name,email,phone,telegram_id,status) VALUES (?,?,?,?,?)", (name,email,phone,telegram_id,"Verified"))
    conn.commit()
    # update pending_verifications
    cursor.execute("UPDATE pending_verifications SET telegram_id=?, status=? WHERE email=?", (telegram_id, "Verified", email))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Verifications")
            # find row to update
            all_vals = ws.get_all_records()
            for i, row in enumerate(all_vals, start=2):
                if row.get("email") == email:
                    ws.update(f"E{i}", "Verified")  # status
                    ws.update(f"D{i}", telegram_id)  # telegram_id
                    break
        except Exception:
            logger.exception("Failed to update verification in Sheets")

def sync_to_systeme(name, email, phone):
    if not SYSTEME_API_KEY:
        return None
    try:
        first_name = name.split()[0]
        last_name = " ".join(name.split()[1:]) if len(name.split())>1 else ""
        headers = {"Api-Key": SYSTEME_API_KEY, "Content-Type": "application/json"}
        payload = {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone}
        r = requests.post("https://api.systeme.io/api/contacts", json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        contact = r.json()
        contact_id = contact.get("id")
        # add tag
        if contact_id and SYSTEME_TAG_ID:
            try:
                r2 = requests.post(f"https://api.systeme.io/api/contacts/{contact_id}/tags", json={"tag_id": int(SYSTEME_TAG_ID)}, headers=headers, timeout=15)
                r2.raise_for_status()
            except Exception:
                logger.exception("Failed to add tag in Systeme.io")
        return contact_id
    except Exception:
        logger.exception("Systeme.io sync failed")
        return None

# -----------------------------------------------------------------------------
# Utility filters
# -----------------------------------------------------------------------------
def _is_admin(user_id):
    return ADMIN_ID and user_id == ADMIN_ID

# -----------------------------------------------------------------------------
# Conversation states constants (subset as example)
# -----------------------------------------------------------------------------
ADD_STUDENT_NAME, ADD_STUDENT_PHONE, ADD_STUDENT_EMAIL = range(3)
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = range(3,6)
SUBMIT_MODULE, SUBMIT_MEDIA_TYPE, SUBMIT_MEDIA_UPLOAD = range(6,9)
GRADE_SCORE, GRADE_COMMENT_TYPE, GRADE_COMMENT_CONTENT = range(9,12)
SHARE_WIN_TYPE, SHARE_WIN_UPLOAD = range(12,14)
ASK_QUESTION_TEXT, ANSWER_QUESTION = range(14,16)

# -----------------------------------------------------------------------------
# Handlers (full flows)
# -----------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user_data = context.user_data
    if user_data:
        user_data.clear()
    await update.message.reply_text(
        "Action cancelled.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Start handler (DM-only)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" and not _is_admin(update.effective_user.id):
        # do nothing in groups (admin bypass allowed)
        return
    uid = update.effective_user.id
    cursor.execute("SELECT * FROM verified_users WHERE telegram_id=?", (uid,))
    if cursor.fetchone():
        keyboard = ReplyKeyboardMarkup(
            [["📤 Submit Assignment", "🎉 Share Small Win"], ["❓ Ask a Question", "📊 Check Status"]],
            resize_keyboard=True
        )
        await update.message.reply_text("✅ You're verified! Choose an action:", reply_markup=keyboard)
    else:
        keyboard = ReplyKeyboardMarkup([["Verify Now"]], resize_keyboard=True)
        await update.message.reply_text("Welcome! You need to verify to use student features. Click Verify Now or /verify", reply_markup=keyboard)

# -------------------------
# Admin: /add_student in VERIFICATION_GROUP_ID
# -------------------------
async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin only and only allowed in verification group or DM if admin
    if not _is_admin(update.effective_user.id):
        return
    if update.effective_chat.type != "private" and update.effective_chat.id != VERIFICATION_GROUP_ID and not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Enter student's full name:")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Try again:")
        return ADD_STUDENT_NAME
    context.user_data["add_name"] = name
    await update.message.reply_text("Enter student's phone number (e.g., +2341234567890):")
    return ADD_STUDENT_PHONE

PHONE_RE = re.compile(r'^\+\d{10,15}$')
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Phone invalid. Use format +2341234567890. Try again:")
        return ADD_STUDENT_PHONE
    context.user_data["add_phone"] = phone
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Email invalid. Try again:")
        return ADD_STUDENT_EMAIL
    name = context.user_data.get("add_name")
    phone = context.user_data.get("add_phone")
    h = add_pending_verification(name, email, phone, telegram_id=0)
    await update.message.reply_text(f"Student {name} added as pending. They can verify with these details. Admins can verify with /verify_student {email}")
    return ConversationHandler.END

# -------------------------
# Student verification flow (DM)
# -------------------------
async def verify_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # allow in DM only
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to verify.")
        return ConversationHandler.END
    await update.message.reply_text("Enter your full name:")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Try again:")
        return VERIFY_NAME
    context.user_data["verify_name"] = name
    await update.message.reply_text("Enter your phone number (+countrycode...):")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Phone invalid. Try again:")
        return VERIFY_PHONE
    context.user_data["verify_phone"] = phone
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Email invalid. Try again:")
        return VERIFY_EMAIL
    name = context.user_data.get("verify_name")
    phone = context.user_data.get("verify_phone")
    h = _sha_hash(name, email, phone)
    # check pending_verifications
    cursor.execute("SELECT id FROM pending_verifications WHERE hash=? AND status='Pending'", (h,))
    row = cursor.fetchone()
    if row:
        # mark verified
        mark_verified(name, email, phone, update.effective_user.id)
        # sync to Systeme.io
        sync_to_systeme(name, email, phone)
        await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=ReplyKeyboardRemove())
        # send main menu
        keyboard = ReplyKeyboardMarkup(
            [["📤 Submit Assignment", "🎉 Share Small Win"], ["❓ Ask a Question", "📊 Check Status"]],
            resize_keyboard=True
        )
        await update.message.reply_text("Choose an action:", reply_markup=keyboard)
    else:
        await update.message.reply_text("Details not found. Contact admin or try again.", reply_markup=ReplyKeyboardMarkup([["Verify Now"]], resize_keyboard=True))
    return ConversationHandler.END

# -------------------------
# Admin manual verify: /verify_student <email>
# -------------------------
async def verify_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /verify_student email@example.com")
        return
    email = context.args[0].strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email format.")
        return
    pending = find_pending_by_email(email)
    if not pending:
        await update.message.reply_text("No pending student found with that email. Use /add_student first.")
        return
    # pending: id,name,email,phone,telegram_id,status,hash
    _, name, email, phone, _, _, h = pending
    # mark verified with telegram_id=0 for testing, admin can edit
    mark_verified(name, email, phone, 0)
    sync_to_systeme(name, email, phone)
    await update.message.reply_text(f"Student with email {email} verified successfully!")

# -------------------------
# Admin remove student: /remove_student <telegram_id>
# -------------------------
async def remove_student_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_student <telegram_id>")
        return
    try:
        tid = int(context.args[0])
    except Exception:
        await update.message.reply_text("telegram_id must be an integer")
        return
    cursor.execute("SELECT id,name FROM verified_users WHERE telegram_id=?", (tid,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text(f"No verified student found with Telegram ID {tid}.")
        return
    cursor.execute("DELETE FROM verified_users WHERE telegram_id=?", (tid,))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Verifications")
            all_rows = ws.get_all_records()
            for i,row in enumerate(all_rows, start=2):
                if int(row.get("telegram_id") or 0) == tid:
                    ws.update(f"E{i}", "Removed")
                    ws.update(f"D{i}", "")
                    break
        except Exception:
            logger.exception("Failed to update Sheets when removing student")
    await update.message.reply_text(f"Student {tid} removed. They must re-verify to regain access.")

# -------------------------
# Submission flow
# -------------------------
async def submit_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # DM only
    if update.effective_chat.type != "private" and not _is_admin(update.effective_user.id):
        await update.message.reply_text("Please DM me to submit assignments.")
        return ConversationHandler.END
    # ensure verified
    cursor.execute("SELECT * FROM verified_users WHERE telegram_id=?", (update.effective_user.id,))
    if not cursor.fetchone():
        await update.message.reply_text("Please verify first using /verify.")
        return ConversationHandler.END
    await update.message.reply_text("Which module? (1-12)")
    return SUBMIT_MODULE

async def submit_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message.text.strip()
    try:
        module = int(m)
        if not (1 <= module <= 12):
            raise ValueError()
    except Exception:
        await update.message.reply_text("Invalid module. Enter a number 1-12:")
        return SUBMIT_MODULE
    context.user_data["module"] = module
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Video", callback_data="media_video"), InlineKeyboardButton("Image", callback_data="media_image")]])
    await update.message.reply_text("Video or Image?", reply_markup=keyboard)
    return SUBMIT_MEDIA_TYPE

async def submit_media_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    media = query.data  # media_video or media_image
    context.user_data["media_type"] = "video" if "video" in media else "image"
    await query.message.reply_text(f"Send your {context.user_data['media_type']}:")
    return SUBMIT_MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # validate media
    if context.user_data.get("media_type") == "image":
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return SUBMIT_MEDIA_UPLOAD
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    else:
        if not update.message.video:
            await update.message.reply_text("Please send a video.")
            return SUBMIT_MEDIA_UPLOAD
        file_id = update.message.video.file_id
        file_type = "video"
    submission_uuid = str(uuid.uuid4())
    username = update.effective_user.username or update.effective_user.first_name
    module = context.user_data.get("module")
    created_at = datetime.datetime.now(TZ).isoformat()
    cursor.execute("INSERT INTO submissions (telegram_id,username,module,file_id,file_type,submission_uuid,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (update.effective_user.id, username, module, file_id, file_type, submission_uuid, "Submitted", created_at))
    conn.commit()
    # record in sheets
    if sheets_ok:
        try:
            ws = sheet.worksheet("Assignments")
            ws.append_row([username, update.effective_user.id, module, "Submitted", file_id, file_type, submission_uuid, created_at, "", "", ""])
        except Exception:
            logger.exception("Failed to append assignment to Sheets")
    # forward to assignments group with grade button
    if ASSIGNMENTS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{submission_uuid}")]])
        try:
            await context.bot.send_message(chat_id=ASSIGNMENTS_GROUP_ID, text=f"Submission from {username} - Module {module}: {file_type} {file_id}", reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to forward submission to assignments group")
    await update.message.reply_text("Boom! Submission received!")
    return ConversationHandler.END

# -------------------------
# Grading flows (inline and manual)
# -------------------------
async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # only admins can start grading in group
    if not _is_admin(update.effective_user.id):
        await update.callback_query.answer("Admin only", show_alert=True)
        return
    query = update.callback_query
    await query.answer()

    submission_uuid = query.data.split("_",1)[1]
    cursor.execute("SELECT id,username,module,status FROM submissions WHERE submission_uuid=?", (submission_uuid,))
    sub = cursor.fetchone()

    if not sub:
        await query.edit_message_text("Submission not found.")
        return

    if sub[3] == "Graded":
        await query.edit_message_text("This submission has already been graded.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"score_{submission_uuid}_{i}") for i in range(1,6)],
        [InlineKeyboardButton(str(i), callback_data=f"score_{submission_uuid}_{i}") for i in range(6,11)]
    ])

    await query.edit_message_text("Select score (1-10):", reply_markup=keyboard)

async def grade_score_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        await query.answer("Admin only", show_alert=True)
        return

    parts = query.data.split("_")
    if len(parts) < 3: return

    submission_uuid, score = parts[1], int(parts[2])

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Comment", callback_data=f"comment_yes_{submission_uuid}_{score}"),
        InlineKeyboardButton("No Comment", callback_data=f"comment_no_{submission_uuid}_{score}")
    ]])
    await query.edit_message_text("Add a comment?", reply_markup=keyboard)

async def grade_comment_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        await query.answer("Admin only", show_alert=True)
        return

    parts = query.data.split("_")
    mode, submission_uuid, score = parts[1], parts[2], int(parts[3])

    if mode == "no":
        cursor.execute("UPDATE submissions SET status=?, score=? WHERE submission_uuid=?", ("Graded", score, submission_uuid))
        conn.commit()
        if sheets_ok:
            try:
                ws = sheet.worksheet("Assignments")
                cell = ws.find(submission_uuid, in_column=7) # find by uuid
                if cell:
                    ws.update_cell(cell.row, 4, "Graded")
                    ws.update_cell(cell.row, 9, score)
            except Exception:
                logger.exception("Failed to update Sheets after grading")
        await query.edit_message_text("✅ Graded!")
    else:
        await query.edit_message_text("Please send your comment (text, audio, or video).")
        context.user_data["grading_submission_uuid"] = submission_uuid
        context.user_data["grading_score"] = score
        context.user_data["grading_message_id"] = query.message.message_id
        context.user_data["grading_chat_id"] = query.message.chat_id

async def grade_comment_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id) or "grading_submission_uuid" not in context.user_data:
        return

    submission_uuid = context.user_data.get("grading_submission_uuid")
    score = context.user_data.get("grading_score")
    message_id = context.user_data.get("grading_message_id")
    chat_id = context.user_data.get("grading_chat_id")

    comment, ctype = (None, None)
    if update.message.text:
        comment, ctype = update.message.text, "text"
    elif update.message.audio:
        comment, ctype = update.message.audio.file_id, "audio"
    elif update.message.voice:
        comment, ctype = update.message.voice.file_id, "voice"
    elif update.message.video:
        comment, ctype = update.message.video.file_id, "video"
    else:
        return # Ignore non-content messages

    cursor.execute("UPDATE submissions SET status=?, score=?, comment_type=?, comment_content=? WHERE submission_uuid=?", ("Graded", score, ctype, comment, submission_uuid))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Assignments")
            cell = ws.find(submission_uuid, in_column=7)
            if cell:
                ws.update_cell(cell.row, 4, "Graded")
                ws.update_cell(cell.row, 9, score)
                ws.update_cell(cell.row, 10, ctype)
                ws.update_cell(cell.row, 11, comment)
        except Exception:
            logger.exception("Failed to update Sheets with grading comment")

    if chat_id and message_id:
        try:
            await context.bot.edit_message_text("✅ Graded with comment.", chat_id=chat_id, message_id=message_id)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="✅ Graded with comment.")

    try:
        await update.message.delete()
    except Exception:
        pass

    for key in ["grading_submission_uuid", "grading_score", "grading_message_id", "grading_chat_id"]:
        context.user_data.pop(key, None)

# Manual grading command
async def grade_manual_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Enter username to grade:")
    return GRADE_SCORE

async def grade_manual_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # user text -> store username then ask for module
    context.user_data["grade_username"] = update.message.text.strip()
    await update.message.reply_text("Which module? (1-12)")
    return GRADE_COMMENT_TYPE

async def grade_manual_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        module = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Invalid module. Enter 1-12.")
        return GRADE_COMMENT_TYPE
    uname = context.user_data.get("grade_username")
    cursor.execute("SELECT submission_uuid, id FROM submissions WHERE username=? AND module=? AND status='Submitted' ORDER BY created_at DESC", (uname,module))
    r = cursor.fetchone()
    if not r:
        await update.message.reply_text("No submitted assignment found.")
        return ConversationHandler.END
    submission_uuid = r[0]
    context.user_data["grading_submission_uuid"] = submission_uuid
    await update.message.reply_text("Enter score (1-10):")
    return GRADE_COMMENT_CONTENT

async def grade_manual_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        score = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Invalid score.")
        return GRADE_COMMENT_CONTENT
    context.user_data["grading_score"] = score
    await update.message.reply_text("Add comment? Send it now or type /nocmt to skip")
    return GRADE_COMMENT_CONTENT

async def grade_manual_comment_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    score = context.user_data.get("grading_score")
    submission_uuid = context.user_data.get("grading_submission_uuid")
    comment = update.message.text.strip() if update.message.text else ""
    cursor.execute("UPDATE submissions SET status=?, score=?, comment_type=?, comment_content=? WHERE submission_uuid=?", ("Graded", score, "text", comment, submission_uuid))
    conn.commit()
    await update.message.reply_text("Grading saved.")
    return ConversationHandler.END

# -------------------------
# Share small win
# -------------------------
async def share_win_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" and not _is_admin(update.effective_user.id):
        await update.message.reply_text("Please DM me to share a win.")
        return ConversationHandler.END
    # ensure verified
    cursor.execute("SELECT * FROM verified_users WHERE telegram_id=?", (update.effective_user.id,))
    if not cursor.fetchone():
        await update.message.reply_text("Please verify first using /verify.")
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Text", callback_data="win_text"), InlineKeyboardButton("Image", callback_data="win_image"), InlineKeyboardButton("Video", callback_data="win_video")]])
    await update.message.reply_text("Text, Image, or Video?", reply_markup=keyboard)
    return SHARE_WIN_TYPE

async def share_win_type_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kind = query.data.split("_",1)[1]
    context.user_data["share_kind"] = kind
    await query.message.reply_text(f"Send your {kind}:")
    return SHARE_WIN_UPLOAD

async def share_win_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = context.user_data.get("share_kind")
    username = update.effective_user.username or update.effective_user.first_name
    created_at = datetime.datetime.now(TZ).isoformat()
    content = None
    ctype = None
    if kind == "text" and update.message.text:
        content = update.message.text
        ctype = "text"
    elif kind == "image" and update.message.photo:
        content = update.message.photo[-1].file_id
        ctype = "photo"
    elif kind == "video" and update.message.video:
        content = update.message.video.file_id
        ctype = "video"
    else:
        # This case should now be handled by share_win_invalid_upload, but as a fallback:
        await update.message.reply_text("Invalid content type. Please try again or /cancel.")
        return SHARE_WIN_UPLOAD
    cursor.execute("INSERT INTO wins (telegram_id,username,content_type,content,created_at) VALUES (?,?,?,?,?)", (update.effective_user.id, username, ctype, content, created_at))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Wins")
            ws.append_row([username, update.effective_user.id, ctype, content, created_at])
        except Exception:
            logger.exception("Failed to log win to Sheets")
    # forward to support group
    if SUPPORT_GROUP_ID:
        try:
            await context.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=f"Win from {username}: {ctype} {content}")
        except Exception:
            logger.exception("Failed to forward win to support group")
    await update.message.reply_text("Awesome win shared!")
    context.user_data.clear()
    return ConversationHandler.END

async def share_win_invalid_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = context.user_data.get("share_kind", "content")
    await update.message.reply_text(f"That's not a {kind}. Please send a {kind} for your win, or /cancel to stop.")
    return SHARE_WIN_UPLOAD

# -------------------------
# Ask a question
# -------------------------
async def ask_dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for asking a question in a DM. Starts a conversation."""
    await update.message.reply_text("What's your question?")
    return ASK_QUESTION_TEXT

async def ask_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /ask command in the support group."""
    if not context.args:
        await update.message.reply_text("Please provide your question after the /ask command.\nE.g., /ask How do I...?")
        return

    qtext = " ".join(context.args)
    qid = str(uuid.uuid4())
    username = update.effective_user.username or update.effective_user.first_name
    created_at = datetime.datetime.now(TZ).isoformat()

    cursor.execute("INSERT INTO questions (telegram_id,username,question,question_uuid,created_at) VALUES (?,?,?,?,?)", (update.effective_user.id, username, qtext, qid, created_at))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Questions")
            ws.append_row([username, update.effective_user.id, qtext, "", qid, "", created_at])
        except Exception:
            logger.exception("Failed to append question to Sheets")

    if QUESTIONS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{qid}")]])
        try:
            await context.bot.send_message(chat_id=QUESTIONS_GROUP_ID, text=f"Question from {username} (from group): {qtext}", reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to forward question to questions group")

    await update.message.reply_text("Question sent! Our support team will get back to you.")

async def ask_question_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the question text received in a DM conversation."""
    qtext = update.message.text.strip()
    if not qtext:
        await update.message.reply_text("Please type your question or use /cancel.")
        return ASK_QUESTION_TEXT

    qid = str(uuid.uuid4())
    username = update.effective_user.username or update.effective_user.first_name
    created_at = datetime.datetime.now(TZ).isoformat()
    cursor.execute("INSERT INTO questions (telegram_id,username,question,question_uuid,created_at) VALUES (?,?,?,?,?)", (update.effective_user.id, username, qtext, qid, created_at))
    conn.commit()
    if sheets_ok:
        try:
            ws = sheet.worksheet("Questions")
            ws.append_row([username, update.effective_user.id, qtext, "", qid, "", created_at])
        except Exception:
            logger.exception("Failed to append question to Sheets")
    # forward to QUESTIONS_GROUP_ID
    if QUESTIONS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{qid}")]])
        try:
            await context.bot.send_message(chat_id=QUESTIONS_GROUP_ID, text=f"Question from {username}: {qtext}", reply_markup=keyboard)
        except Exception:
            logger.exception("Failed to forward question to questions group")

    await update.message.reply_text("Question sent! We'll get back to you.")
    return ConversationHandler.END

async def answer_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # callback handler in questions group -> admin clicks Answer
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        await query.answer("Admin only", show_alert=True)
        return
    qid = query.data.split("_",1)[1]
    # send admin prompt (we'll handle next message from admin)
    await query.message.reply_text(f"Send your answer for question {qid} (text/audio/video) in this chat, I'll forward to student.")
    context.user_data["answer_question_uuid"] = qid

async def answer_question_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # admin responding to question
    if not _is_admin(update.effective_user.id) or "answer_question_uuid" not in context.user_data:
        return

    qid = context.user_data.get("answer_question_uuid")
    # find question author
    cursor.execute("SELECT telegram_id,username FROM questions WHERE question_uuid=?", (qid,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text("Question not found.")
        return
    student_tid, student_uname = row
    # capture answer
    ans_type = None
    ans = None
    if update.message.text:
        ans_type = "text"
        ans = update.message.text
    elif update.message.audio:
        ans_type = "audio"
        ans = update.message.audio.file_id
    elif update.message.voice:
        ans_type = "voice"
        ans = update.message.voice.file_id
    elif update.message.video:
        ans_type = "video"
        ans = update.message.video.file_id
    else:
        await update.message.reply_text("Unsupported answer type.")
        return
    # update DB
    cursor.execute("UPDATE questions SET answer_type=?, answer=? WHERE question_uuid=?", (ans_type, ans, qid))
    conn.commit()
    # forward to student
    try:
        if ans_type == "text":
            await context.bot.send_message(chat_id=student_tid, text=f"Answer to your question: {ans}")
        else:
            if ans_type in ("audio","voice"):
                await context.bot.send_audio(chat_id=student_tid, audio=ans)
            elif ans_type == "video":
                await context.bot.send_video(chat_id=student_tid, video=ans)
    except Exception:
        logger.exception("Failed to forward answer to student")
    await update.message.reply_text("Answer sent to student.")
    context.user_data.pop("answer_question_uuid", None)

# -------------------------
# Check status
# -------------------------
async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please DM me to check status.")
        return
    tid = update.effective_user.id
    # submissions
    cursor.execute("SELECT module,status,score,comment_type,comment_content FROM submissions WHERE telegram_id=?", (tid,))
    subs = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM wins WHERE telegram_id=?", (tid,))
    wins_count = cursor.fetchone()[0]
    completed_modules = [str(s[0]) for s in subs if s[1] == "Graded"]
    scores = [str(s[2]) for s in subs if s[2] is not None]
    comments = [s[4] for s in subs if s[4]]
    msg = f"Completed modules: {', '.join(completed_modules) or 'None'}\nScores: {', '.join(scores) or 'None'}\nComments: {', '.join(comments) or 'None'}\nWins: {wins_count}"
    await update.message.reply_text(msg)
    if len(completed_modules) >= ACHIEVER_MODULES and wins_count >= ACHIEVER_WINS:
        await update.message.reply_text("🎉 AVAP Achiever Badge earned!")
    # show main menu
    keyboard = ReplyKeyboardMarkup(
        [["📤 Submit Assignment", "🎉 Share Small Win"], ["❓ Ask a Question", "📊 Check Status"]],
        resize_keyboard=True
    )
    await update.message.reply_text("Main menu:", reply_markup=keyboard)

# -------------------------
# Join request handling (example simplified)
# -------------------------
async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # in webhook mode this must be handled via ChatMember or chat_join_request updates; simplified placeholder
    # Approve join requests if the user is verified
    try:
        req = update.effective_message  # placeholder
    except Exception:
        return
    # This section depends on library support and update content; left as a placeholder

# -------------------------
# Sunday reminder job
# -------------------------
scheduler = AsyncIOScheduler()

async def sunday_reminder_job():
    cursor.execute("SELECT telegram_id FROM verified_users WHERE status='Verified'")
    rows = cursor.fetchall()
    for (tid,) in rows:
        try:
            await telegram_app.bot.send_message(chat_id=tid, text="🌞 Sunday Reminder: Check your progress with /status and share a win with /sharewin!")
        except Exception:
            logger.exception("Failed to send Sunday reminder to %s", tid)

scheduler.add_job(sunday_reminder_job, "cron", day_of_week="sun", hour=18, minute=0, timezone=TZ)

# -----------------------------------------------------------------------------
# Build application and register handlers (fixed entry_points)
# -----------------------------------------------------------------------------
def build_application():
    app = Application.builder().token(BOT_TOKEN).build()

    # basic handlers
    app.add_handler(CommandHandler("start", start))

    # add_student conversation (admin)
    add_student_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_student", add_student_start),
        ],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(add_student_conv)
    app.add_handler(CommandHandler("verify_student", verify_student_cmd))
    app.add_handler(CommandHandler("remove_student", remove_student_handler))

    # submit conversation
    submit_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📤 Submit Assignment$") | filters.Regex(r"^Submit Assignment$"), submit_start_handler),
            CommandHandler("submit", submit_start_handler),
        ],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module_handler)],
            SUBMIT_MEDIA_TYPE: [CallbackQueryHandler(submit_media_type_cb, pattern="^media_")],
            SUBMIT_MEDIA_UPLOAD: [MessageHandler((filters.PHOTO | filters.VIDEO | filters.TEXT) & ~filters.COMMAND, submit_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(submit_conv)
    app.add_handler(CallbackQueryHandler(submit_media_type_cb, pattern="^media_"))

    # grading handlers
    app.add_handler(CallbackQueryHandler(grade_inline_start, pattern="^grade_"))
    app.add_handler(CallbackQueryHandler(grade_score_cb, pattern="^score_"))
    app.add_handler(CallbackQueryHandler(grade_comment_type_cb, pattern="^comment_"))

    manual_grade_conv = ConversationHandler(
        entry_points=[CommandHandler("grade", grade_manual_start)],
        states={
            GRADE_SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_username)],
            GRADE_COMMENT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_module)],
            GRADE_COMMENT_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_manual_score)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(manual_grade_conv)

    # admin comment content handler (free-form)
    if ADMIN_ID:
        app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), grade_comment_content_handler))

    # share win conversation
    share_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^🎉 Share Small Win$") | filters.Regex(r"^Share Small Win$"), share_win_start),
            CommandHandler("sharewin", share_win_start),
        ],
        states={
            SHARE_WIN_TYPE: [CallbackQueryHandler(share_win_type_cb, pattern="^win_")],
            SHARE_WIN_UPLOAD: [
                MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, share_win_upload_handler),
                MessageHandler(filters.ALL & ~filters.COMMAND, share_win_invalid_upload)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(share_conv)

    # ask conversation for DMs
    ask_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ask", ask_dm_command, filters.ChatType.PRIVATE),
            MessageHandler(filters.Regex(r"^❓ Ask a Question$") | filters.Regex(r"^Ask a Question$"), ask_dm_command),
        ],
        states={
            ASK_QUESTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_text_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(ask_conv)

    # ask command for groups
    if SUPPORT_GROUP_ID:
        app.add_handler(CommandHandler("ask", ask_group_command, filters.Chat(chat_id=SUPPORT_GROUP_ID)))

    # answer question callback in questions group
    app.add_handler(CallbackQueryHandler(answer_question_start, pattern="^answer_"))
    # admin answer messages (we'll read any admin message to answer question if in context)
    if ADMIN_ID:
        app.add_handler(MessageHandler(filters.ALL & filters.User(user_id=ADMIN_ID), answer_question_receive))

    # verification conversation
    verify_conv = ConversationHandler(
        entry_points=[
            CommandHandler("verify", verify_start_cmd),
            MessageHandler(filters.Regex(r"^Verify Now$"), verify_start_cmd),
            CallbackQueryHandler(lambda u,c: None, pattern="^verify_now$"),  # if you show a button that uses callback
        ],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(verify_conv)

    # status and simple commands
    app.add_handler(CommandHandler("status", status_handler))

    return app

# Build application globally for webhook processing
telegram_app = build_application()

# -----------------------------------------------------------------------------
# FastAPI app for webhooks
# -----------------------------------------------------------------------------
api = FastAPI()

@api.get("/")
async def root():
    return {"status": "ok"}

@api.get("/health")
async def health():
    return {"status": "healthy"}

@api.post(f"/webhook/{BOT_TOKEN}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return JSONResponse({"ok": True})

@api.post("/webhook/set")
async def set_webhook(req: Request):
    # convenience endpoint to set webhook to WEBHOOK_BASE_URL
    if not WEBHOOK_BASE_URL:
        return JSONResponse({"ok": False, "error": "WEBHOOK_BASE_URL not configured"})
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{BOT_TOKEN}"
    await telegram_app.bot.set_webhook(webhook_url)
    return JSONResponse({"ok": True, "webhook": webhook_url})

@api.post("/webhook/delete")
async def delete_webhook(req: Request):
    await telegram_app.bot.delete_webhook()
    return JSONResponse({"ok": True})

# Startup and shutdown events
@api.on_event("startup")
async def on_startup():
    logger.info("Starting AVAP bot (webhook mode)...")
    await telegram_app.initialize()

    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{BOT_TOKEN}"
        try:
            await telegram_app.bot.set_webhook(webhook_url, allowed_updates=Update.ALL_TYPES)
            logger.info(f"Webhook set to {webhook_url}")
        except Exception:
            logger.exception("Failed to set webhook")

    await telegram_app.start()

    try:
        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started.")
    except Exception:
        logger.exception("Failed to start scheduler")


@api.on_event("shutdown")
async def on_shutdown():
    logger.info("Stopping AVAP bot...")
    try:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Scheduler stopped.")
    except Exception:
        logger.exception("Failed to stop scheduler")

    await telegram_app.stop()

    try:
        await telegram_app.bot.delete_webhook()
        logger.info("Webhook deleted successfully.")
    except Exception:
        logger.exception("Failed to delete webhook")

    logger.info("AVAP bot shutdown complete.")

# -----------------------------------------------------------------------------
# Entrypoint for local run (uvicorn)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import asyncio

    if len(sys.argv) > 1 and sys.argv[1] == "poll":
        logger.info("Starting bot in polling mode...")

        async def main():
            # In polling mode, we need to initialize the app and start the scheduler manually
            # The FastAPI startup events won't run.
            await telegram_app.initialize()
            if scheduler.running:
                scheduler.shutdown()
            scheduler.start()
            logger.info("Scheduler started for polling mode.")
            await telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)

        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
    else:
        logger.info("Starting uvicorn web server for webhook mode on port %s", PORT)
        uvicorn.run("bot:api", host="0.0.0.0", port=PORT, log_level="info")
