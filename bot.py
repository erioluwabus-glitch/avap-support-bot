import os
import json
import logging
import datetime
import pytz
import random
import re
import asyncio
import sqlite3
import hashlib
import sys
import time
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from functools import wraps
from typing import Optional, Tuple

import httpx
import telegram
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChatJoinRequest,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    ChatJoinRequestHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    JobQueue,
)
from telegram.error import TimedOut, InvalidToken, NetworkError, BadRequest, Forbidden
from fastapi import FastAPI, Request
import uvicorn
from dotenv import load_dotenv

# States for conversation handlers
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = 50, 51, 52
MODULE, MEDIA_TYPE, MEDIA_UPLOAD = 10, 11, 12
USERNAME, MODULE_GRADE, FEEDBACK = 20, 21, 22
USERNAME_GET, MODULE_GET = 30, 31
QUESTION = 40
ANSWER_TEXT = 70
ADD_STUDENT_NAME, ADD_STUDENT_PHONE, ADD_STUDENT_EMAIL = 60, 61, 62
GRADE_SCORE, GRADE_COMMENT_TYPE, GRADE_COMMENT, GRADE_COMMENT_CONTENT = 80, 81, 82, 83
VIEW_COMMENTS = 90

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Parse integer environment variables
def parse_int_env(name: str, default=None) -> Optional[int]:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        logger.warning(f"Invalid {name} ({v}) - expected integer. Using default {default}.")
        return default

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN is not set. Exiting.")
    sys.exit(1)

ADMIN_ID = parse_int_env("ADMIN_ID", default=None)
ASSIGNMENTS_GROUP_ID = parse_int_env("ASSIGNMENTS_GROUP_ID", default=None)
QUESTIONS_GROUP_ID = parse_int_env("QUESTIONS_GROUP_ID", default=None)
VERIFICATION_GROUP_ID = parse_int_env("VERIFICATION_GROUP_ID", default=None)
SUPPORT_GROUP_ID = parse_int_env("SUPPORT_GROUP_ID", default=None)
SUPPORT_GROUP_TITLE = os.getenv("SUPPORT_GROUP_TITLE", "AVAP Support Community")
GOOGLE_CREDENTIALS_STR = os.getenv("GOOGLE_CREDENTIALS")
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_STUDENT_TAG_ID = os.getenv("SYSTEME_VERIFIED_STUDENT_TAG_ID", "1647470")
LANDING_PAGE_LINK = os.getenv("LANDING_PAGE_LINK", "https://your-landing.com/walkthrough")

# Global Google Sheets variables
verifications_sheet = assignments_sheet = wins_sheet = faq_sheet = None

# Google Sheets initialization
try:
    if GOOGLE_CREDENTIALS_STR:
        google_credentials_dict = json.loads(GOOGLE_CREDENTIALS_STR)
        from google.oauth2 import service_account
        import gspread
        credentials = service_account.Credentials.from_service_account_info(
            google_credentials_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly"
            ],
        )
        client = gspread.authorize(credentials)
        sheet = client.open("AVAPSupport")
        try:
            verifications_sheet = sheet.worksheet("Verifications")
        except gspread.exceptions.WorksheetNotFound:
            verifications_sheet = sheet.add_worksheet(title="Verifications", rows=1000, cols=5)
            verifications_sheet.append_row(["Name", "Email", "Phone", "Telegram ID", "Verified"])
        try:
            assignments_sheet = sheet.worksheet("Assignments")
        except gspread.exceptions.WorksheetNotFound:
            assignments_sheet = sheet.add_worksheet(title="Assignments", rows=1000, cols=10)
            assignments_sheet.append_row(["Username", "Telegram ID", "Module", "Status", "Content", "Feedback", "Timestamp", "Score", "Comment Type", "Comment Content"])
        try:
            wins_sheet = sheet.worksheet("Wins")
        except gspread.exceptions.WorksheetNotFound:
            wins_sheet = sheet.add_worksheet(title="Wins", rows=1000, cols=5)
            wins_sheet.append_row(["Username", "Telegram ID", "Type", "Content", "Timestamp"])
        try:
            faq_sheet = sheet.worksheet("FAQ")
        except gspread.exceptions.WorksheetNotFound:
            faq_sheet = sheet.add_worksheet(title="FAQ", rows=1000, cols=7)
            faq_sheet.append_row(["Question", "Answer", "Answer Type", "File ID", "Username", "Timestamp", "Question ID"])
        logger.info("Google Sheets connected successfully.")
except Exception as e:
    logger.error(f"Error connecting to Google Sheets: {e}")
    verifications_sheet = assignments_sheet = wins_sheet = faq_sheet = None

# SQLite database setup (in-memory for Render free tier)
conn = sqlite3.connect(":memory:", check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """CREATE TABLE verifications
       (hash TEXT PRIMARY KEY, telegram_id INTEGER, claimed BOOLEAN DEFAULT FALSE, name TEXT, email TEXT, phone TEXT)"""
)
cursor.execute(
    """CREATE TABLE questions
       (code INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, username TEXT, question TEXT, chat_id INTEGER, status TEXT, timestamp TEXT)"""
)
conn.commit()

# Sync verifications from Google Sheets to in-memory SQLite at startup
def sync_verifications_from_sheets():
    if not verifications_sheet:
        logger.warning("sync_verifications_from_sheets: No verifications_sheet available")
        return
    try:
        verifications = verifications_sheet.get_all_values()
        for row in verifications[1:]:
            name, email, phone, telegram_id, status = row
            if status == "Pending":
                hash_value = hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()
                cursor.execute(
                    "INSERT OR IGNORE INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
                    (hash_value, 0, name, email, phone, 0)
                )
            elif status == "Verified" and telegram_id.isdigit():
                hash_value = hashlib.sha256(f"{name}{email}{phone}{telegram_id}".encode()).hexdigest()
                cursor.execute(
                    "INSERT OR IGNORE INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
                    (hash_value, int(telegram_id), name, email, phone, 1)
                )
        conn.commit()
        logger.info("Synced verifications from Google Sheets to in-memory SQLite")
    except Exception as e:
        logger.error(f"Error syncing verifications: {e}")

# Utility functions
def get_username(user: Optional[telegram.User]) -> str:
    if user is None:
        return "Unknown"
    return user.username or f"User_{user.id}"

def get_timestamp() -> str:
    return datetime.datetime.now(pytz.timezone("Africa/Lagos")).isoformat()

def db_is_verified(telegram_id: int) -> bool:
    cursor.execute("SELECT claimed FROM verifications WHERE telegram_id = ? AND claimed = 1", (telegram_id,))
    return bool(cursor.fetchone())

async def add_to_systeme(name: str, email: str, phone: str) -> bool:
    if not SYSTEME_API_KEY:
        logger.info("SYSTEME_API_KEY not configured; skipping Systeme.io add.")
        return False
    if not SYSTEME_VERIFIED_STUDENT_TAG_ID:
        logger.error("SYSTEME_VERIFIED_STUDENT_TAG_ID not configured; cannot assign tag.")
        return False
    base_url = "https://api.systeme.io/api"
    headers = {"X-API-Key": SYSTEME_API_KEY, "Content-Type": "application/json"}
    name_parts = name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone
        }
        try:
            logger.debug(f"Sending Systeme.io contact creation request for {email}")
            resp = await client.post(f"{base_url}/contacts", headers=headers, json=payload)
            if resp.status_code in (200, 201):
                contact_id = resp.json().get("id")
                if not contact_id:
                    logger.error(f"No contact ID in response: {resp.text}")
                    return False
                tag_payload = {"tag_id": int(SYSTEME_VERIFIED_STUDENT_TAG_ID)}
                tag_resp = await client.post(f"{base_url}/contacts/{contact_id}/tags", headers=headers, json=tag_payload)
                if tag_resp.status_code in (200, 201, 204):
                    logger.info(f"Added 'verified' tag to contact {email} (ID: {contact_id})")
                    return True
                logger.error(f"Tag assignment failed: {tag_resp.status_code} - {tag_resp.text}")
                return False
            elif resp.status_code == 422 and "email: This value is already used" in resp.text:
                query = {"email": email}
                search_resp = await client.get(f"{base_url}/contacts", headers=headers, params=query)
                if search_resp.status_code == 200:
                    contacts = search_resp.json().get("data", [])
                    contact = next((c for c in contacts if c.get("email") == email), None)
                    if not contact:
                        logger.error(f"No contact found for {email}")
                        return False
                    contact_id = contact.get("id")
                    if any(tag.get("id") == int(SYSTEME_VERIFIED_STUDENT_TAG_ID) for tag in contact.get("tags", [])):
                        logger.info(f"Contact {email} already has 'verified' tag")
                        return True
                    tag_payload = {"tag_id": int(SYSTEME_VERIFIED_STUDENT_TAG_ID)}
                    tag_resp = await client.post(f"{base_url}/contacts/{contact_id}/tags", headers=headers, json=tag_payload)
                    if tag_resp.status_code in (200, 201, 204):
                        logger.info(f"Added 'verified' tag to existing contact {email} (ID: {contact_id})")
                        return True
                    logger.error(f"Tag assignment failed for existing contact: {tag_resp.status_code} - {tag_resp.text}")
                    return False
                logger.error(f"Failed to fetch contact: {search_resp.status_code} - {search_resp.text}")
                return False
            logger.error(f"Contact creation failed: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Error adding to Systeme.io for {email}: {e}")
            return False

async def forward_to_group(
    bot: telegram.Bot,
    group_id: Optional[int],
    text: str,
    photo: Optional[str] = None,
    video: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> None:
    if not group_id:
        logger.debug("No group id provided to forward_to_group; skipping")
        return
    try:
        if photo:
            await bot.send_photo(group_id, photo, caption=text, reply_markup=reply_markup)
        elif video:
            await bot.send_video(group_id, video, caption=text, reply_markup=reply_markup)
        else:
            await bot.send_message(group_id, text, reply_markup=reply_markup)
        logger.debug(f"Forwarded to {group_id}: {text[:120]}")
    except Exception as e:
        logger.error(f"Error forwarding to group {group_id}: {e}")

def run_health_check_server():
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
    try:
        server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
        logger.info("Health check server started on port 8080")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server failed to start: {e}")

# Keyboards and message templates
verify_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Verify Now", callback_data="verify_prompt")]])
main_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📤 Submit Assignment"), KeyboardButton("🎉 Share Small Win")],
        [KeyboardButton("📊 Check Status"), KeyboardButton("❓ Ask a Question")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    selective=True,
    input_field_placeholder="Choose a feature"
)
start_messages = [
    "🌟 Welcome to AVAP! Ready to begin your exciting journey?\n\nTo access all features, please verify your account. Click '🔒 Verify Now' below!",
    "🚀 Welcome aboard AVAP! Let's get you started!\n\nVerify your account to unlock all features. Click '🔒 Verify Now' below!"
]
submit_confirm = ["Boom! Submission in!", "Great work! Submission received!"]
win_confirm = ["Victory logged!", "Epic win shared!"]
grade_confirm = ["✅ Graded!", "🎉 Submission graded successfully!"]
ask_confirm = ["Question received! We'll get back to you soon!", "Your question is in the queue!"]
answer_sent = ["Answer sent and archived!", "Response delivered!"]

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error_text = f"⚠️ Exception: {context.error}\n\nUpdate: {update}"
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Oops! Something went wrong. Please try again later."
            )
        except Exception:
            pass
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=error_text[:4000]
            )
        except Exception as e:
            logger.warning(f"Could not send error to admin: {e}")
    try:
        if verifications_sheet:
            verifications_sheet.append_row([
                str(datetime.datetime.now(pytz.timezone("Africa/Lagos"))),
                str(update),
                str(context.error)
            ])
    except Exception as e:
        logger.warning(f"Failed to log error to Google Sheets: {e}")

async def debug_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug(f"Received update: {update}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Test command received from {update.effective_user.id}")
    await update.message.reply_text("Bot is alive!")

async def sunday_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("sunday_reminder: Sending reminders")
    if not SUPPORT_GROUP_ID or not verifications_sheet:
        logger.warning("sunday_reminder: SUPPORT_GROUP_ID or verifications_sheet not configured")
        return
    try:
        verifications = verifications_sheet.get_all_values()
        verified_users = [row[3] for row in verifications[1:] if row[4] == "Verified" and row[3].isdigit()]
        for telegram_id in verified_users:
            try:
                await context.bot.send_message(
                    int(telegram_id),
                    "📢 Reminder: Check your progress with /status to see your assignments, wins, and scores!",
                    reply_markup=main_keyboard
                )
            except Exception as e:
                logger.warning(f"sunday_reminder: Failed to send to {telegram_id}: {e}")
        await context.bot.send_message(
            SUPPORT_GROUP_ID,
            "📢 Sunday reminder sent to all verified students to check their status!"
        )
        logger.info("sunday_reminder: Sent reminders successfully")
    except Exception as e:
        logger.error(f"sunday_reminder: Error sending reminders: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug(f"start_command: Received /start from user {update.effective_user.id}")
    user = update.effective_user
    if not user:
        logger.warning("start_command: No user in update")
        return
    telegram_id = user.id
    is_private = update.message.chat.type == "private"
    if db_is_verified(telegram_id):
        logger.debug(f"start_command: User {telegram_id} is verified")
        await update.message.reply_text(
            "You're a verified AVAP champ! Use the buttons below:",
            reply_markup=main_keyboard if is_private else ReplyKeyboardRemove()
        )
        return
    welcome_msg = random.choice(start_messages)
    logger.debug(f"start_command: Sending welcome message to user {telegram_id}")
    await update.message.reply_text(
        welcome_msg,
        reply_markup=verify_keyboard if is_private else ReplyKeyboardRemove()
    )

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query.query.lower().strip()
    user = update.effective_user
    if not user:
        logger.warning("inline_query: No user in update")
        return
    results = []
    telegram_id = user.id
    is_verified = db_is_verified(telegram_id)
    logger.debug(f"inline_query: Query '{query}' from user {telegram_id}, verified={is_verified}")
    if not query:
        results.append(
            InlineQueryResultArticle(
                id="welcome",
                title="AVAP Bot",
                description="Verify to unlock features!",
                input_message_content=InputTextMessageContent("Use /start to begin or verify with @BotName verify"),
                reply_markup=verify_keyboard
            )
        )
    elif query == "verify" and not is_verified:
        results.append(
            InlineQueryResultArticle(
                id="verify",
                title="Verify Account",
                description="Start verification to unlock AVAP features",
                input_message_content=InputTextMessageContent("Click below to verify your account"),
                reply_markup=verify_keyboard
            )
        )
    await update.inline_query.answer(results, cache_time=0)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug(f"status: Received status request from user {update.effective_user.id}")
    if not db_is_verified(update.effective_user.id):
        logger.debug(f"status: User {update.effective_user.id} not verified")
        await update.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return
    username = get_username(update.effective_user)
    completed_modules = []
    total_score = 0
    assignment_count = 0
    if assignments_sheet:
        assignments = assignments_sheet.get_all_values()
        for row in assignments[1:]:
            try:
                if row[0] == username and row[3] == "Graded":
                    module = row[2]
                    score = int(row[7]) if row[7].isdigit() else 0
                    completed_modules.append((module, score))
                    total_score += score
                    assignment_count += 1
            except IndexError:
                continue
    if wins_sheet:
        wins = wins_sheet.get_all_values()
        total_wins = len([row for row in wins[1:] if row[0] == username])
    else:
        total_wins = 0
    modules_str = ", ".join([f"Module {m} (Score: {s}/10)" for m, s in sorted(completed_modules, key=lambda x: int(x[0]))]) if completed_modules else "None"
    message = (
        f"📈 Your Progress:\n"
        f"Assignments Submitted: {assignment_count}\n"
        f"Modules Completed: {modules_str}\n"
        f"Total Score: {total_score}/10\n"
        f"Wins Shared: {total_wins}"
    )
    is_private = update.message.chat.type == "private"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📋 View Comments", callback_data="view_comments")]])
    await update.message.reply_text(
        message,
        reply_markup=reply_markup if completed_modules else (main_keyboard if is_private else ReplyKeyboardRemove())
    )

async def view_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    username = get_username(update.effective_user)
    logger.debug(f"view_comments: User {update.effective_user.id} requested comments")
    if not assignments_sheet:
        await query.message.reply_text("Google Sheets not configured.")
        return
    assignments = assignments_sheet.get_all_values()
    comments = []
    for row in assignments[1:]:
        try:
            if row[0] == username and row[3] == "Graded" and row[8] and row[9]:
                module = row[2]
                comment_type = row[8]
                comment_content = row[9]
                comments.append((module, comment_type, comment_content))
        except IndexError:
            continue
    if not comments:
        await query.message.reply_text("No comments on your assignments.", reply_markup=main_keyboard)
        return
    for module, comment_type, comment_content in sorted(comments, key=lambda x: int(x[0])):
        message = f"Comment on Module {module}:"
        if comment_type == "Text":
            await query.message.reply_text(f"{message}\n{comment_content}", reply_markup=main_keyboard)
        elif comment_type == "Audio":
            await query.message.reply_audio(comment_content, caption=message, reply_markup=main_keyboard)
        elif comment_type == "Video":
            await query.message.reply_video(comment_content, caption=message, reply_markup=main_keyboard)

async def verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"verify_start: Initiating verification for user {update.effective_user.id}")
    query = update.callback_query
    await query.answer()
    if db_is_verified(update.effective_user.id):
        logger.debug(f"verify_start: User {update.effective_user.id} already verified")
        await query.message.reply_text(
            "You're already verified! Use the buttons below:",
            reply_markup=main_keyboard
        )
        return ConversationHandler.END
    await query.message.reply_text("Enter your full name:")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"verify_name: Received name from user {update.effective_user.id}")
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Enter your phone number:")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"verify_phone: Received phone from user {update.effective_user.id}")
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    name = context.user_data.get("name", "")
    phone = context.user_data.get("phone", "")
    telegram_id = update.effective_user.id
    username = get_username(update.effective_user)
    logger.debug(f"verify_email: Processing for user {telegram_id}, name={name}, email={email}, phone={phone}")
    hash_value = hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()
    cursor.execute(
        "SELECT hash FROM verifications WHERE LOWER(name) = LOWER(?) AND LOWER(email) = LOWER(?) AND phone = ? AND claimed = 0",
        (name, email, phone)
    )
    result = cursor.fetchone()
    if not result and verifications_sheet:
        # Check Google Sheets as fallback
        verifications = verifications_sheet.get_all_values()
        for row in verifications[1:]:
            if (row[0].lower() == name.lower() and 
                row[1].lower() == email.lower() and 
                row[2] == phone and 
                row[4] == "Pending"):
                hash_value = hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()
                cursor.execute(
                    "INSERT INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
                    (hash_value, 0, name, email, phone, 0)
                )
                conn.commit()
                result = (hash_value,)
                break
    if not result:
        logger.warning(f"verify_email: No matching pending entry for user {telegram_id}, name={name}, email={email}, phone={phone}")
        await update.message.reply_text("Details not found. Contact admin to add you.")
        return ConversationHandler.END
    hash_value = result[0]
    logger.debug(f"verify_email: Found matching pending entry for user {telegram_id}, hash={hash_value}")
    try:
        cursor.execute(
            "UPDATE verifications SET claimed = 1, telegram_id = ? WHERE hash = ?",
            (telegram_id, hash_value)
        )
        conn.commit()
        logger.debug(f"verify_email: Marked as verified in SQLite for user {telegram_id}")
        if verifications_sheet:
            verifications = verifications_sheet.get_all_values()
            for i, row in enumerate(verifications[1:], start=2):
                if (row[0].lower() == name.lower() and 
                    row[1].lower() == email.lower() and 
                    row[2] == phone and 
                    row[4] == "Pending"):
                    verifications_sheet.update_cell(i, 4, str(telegram_id))
                    verifications_sheet.update_cell(i, 5, "Verified")
                    logger.debug(f"verify_email: Updated Google Sheets for user {telegram_id}")
                    break
        success = await add_to_systeme(name, email, phone)
        await update.message.reply_text(
            "✅ Verified! Welcome to AVAP!\n\nUse the buttons below to access features:",
            reply_markup=main_keyboard
        )
        await update.message.reply_text(f"Check out our walkthrough: {LANDING_PAGE_LINK}")
        if success:
            logger.info(f"Systeme.io integration successful for {email}")
    except Exception as e:
        logger.error(f"Error in verify_email for user {telegram_id}: {e}", exc_info=True)
        await update.message.reply_text("Verification failed. Try again.")
    return ConversationHandler.END

async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"add_student_start: Received /add_student from user {update.effective_user.id} in chat {update.effective_chat.id}")
    if update.effective_user.id != ADMIN_ID:
        logger.debug(f"add_student_start: User {update.effective_user.id} is not admin")
        await update.message.reply_text("Only admins can add students.")
        return ConversationHandler.END
    if update.effective_chat.id != VERIFICATION_GROUP_ID:
        logger.debug(f"add_student_start: Chat {update.effective_chat.id} is not VERIFICATION_GROUP_ID")
        await update.message.reply_text("This command can only be used in the verification group.")
        return ConversationHandler.END
    await update.message.reply_text("Enter student's full name:")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"add_student_name: Received name from user {update.effective_user.id}")
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Enter student's phone number:")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"add_student_phone: Received phone from user {update.effective_user.id}")
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    name = context.user_data.get("name", "")
    phone = context.user_data.get("phone", "")
    telegram_id = 0  # Placeholder for pre-added student
    hash_value = hashlib.sha256(f"{name}{email}{phone}{telegram_id}".encode()).hexdigest()
    logger.debug(f"add_student_email: Adding student name={name}, email={email}, phone={phone}, hash={hash_value}")
    try:
        cursor.execute(
            "INSERT INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
            (hash_value, telegram_id, name, email, phone, 0)
        )
        conn.commit()
        logger.debug(f"add_student_email: Added to SQLite for student {name}")
        if verifications_sheet:
            verifications_sheet.append_row([name, email, phone, "0", "Pending"])
            logger.debug(f"add_student_email: Appended to Google Sheets for student {name}")
        await update.message.reply_text(
            f"Student {name} added successfully! They can now verify in DMs with these details.",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
    except Exception as e:
        logger.error(f"Error in add_student_email: {e}", exc_info=True)
        await update.message.reply_text("Failed to add student. Try again.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"cancel: Received /cancel from user {update.effective_user.id}")
    context.user_data.clear()
    await update.message.reply_text(
        "Canceled. Choose an action:",
        reply_markup=main_keyboard if update.message.chat.type == "private" else ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"submit_start: Received /submit from user {update.effective_user.id}")
    if not db_is_verified(update.effective_user.id):
        logger.debug(f"submit_start: User {update.effective_user.id} not verified")
        await update.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    await update.message.reply_text("Which module? (1-12)", reply_markup=ReplyKeyboardRemove())
    return MODULE

async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    logger.debug(f"submit_module: Entered handler for user {user_id}, input='{text}'")
    if not text:
        logger.warning(f"submit_module: Empty input from user {user_id}")
        await update.message.reply_text("Please enter a module number (1-12).")
        return MODULE
    try:
        module = int(text)
        if not 1 <= module <= 12:
            logger.warning(f"submit_module: Invalid module number {module} from user {user_id}")
            await update.message.reply_text("Please enter a number between 1-12.")
            return MODULE
        context.user_data["module"] = module
        logger.debug(f"submit_module: Stored module {module} in user_data for user {user_id}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Video", callback_data="media_video"),
             InlineKeyboardButton("Image", callback_data="media_image")]
        ])
        logger.debug(f"submit_module: Attempting to send media type prompt to user {user_id}")
        await update.message.reply_text("Video or Image?", reply_markup=keyboard)
        logger.info(f"submit_module: Successfully sent media type prompt to user {user_id}")
        return MEDIA_TYPE
    except ValueError:
        logger.warning(f"submit_module: Invalid input '{text}' from user {user_id}")
        await update.message.reply_text("Please enter a valid number between 1-12.")
        return MODULE
    except Exception as e:
        logger.error(f"submit_module: Unexpected error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "An error occurred. Please try again or contact support.",
            reply_markup=main_keyboard if update.message.chat.type == "private" else ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def submit_media_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    logger.debug(f"submit_media_type: Received callback '{query.data}' from user {user_id}")
    try:
        await query.answer()
        media_type = query.data.replace("media_", "")
        if media_type not in ("video", "image"):
            logger.warning(f"submit_media_type: Invalid media type '{media_type}' from user {user_id}")
            await query.message.reply_text("Choose Video or Image!")
            return MEDIA_TYPE
        context.user_data["media_type"] = media_type
        await query.message.reply_text(f"Send your {media_type.upper()} now:")
        logger.debug(f"submit_media_type: Sent upload prompt for {media_type} to user {user_id}")
        return MEDIA_UPLOAD
    except Exception as e:
        logger.error(f"submit_media_type: Error for user {user_id}: {e}", exc_info=True)
        await query.message.reply_text("An error occurred. Please try again or contact support.")
        return ConversationHandler.END

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username = get_username(update.effective_user)
    user_id = update.effective_user.id
    module = context.user_data.get("module")
    media_type = context.user_data.get("media_type")
    logger.debug(f"submit_media_upload: Processing for user {user_id}, module {module}, media_type {media_type}")
    photo = video = content = ""
    if media_type == "image" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        photo = file_id
        content = f"(Photo file_id: {file_id})"
    elif media_type == "video" and update.message.video:
        file_id = update.message.video.file_id
        video = file_id
        content = f"(Video file_id: {file_id})"
    else:
        logger.warning(f"submit_media_upload: Invalid media upload for {media_type} from user {user_id}")
        await update.message.reply_text(f"Please send a {media_type.upper()}.")
        return MEDIA_UPLOAD
    timestamp = get_timestamp()
    try:
        if assignments_sheet:
            row_index = len(assignments_sheet.get_all_values()) + 1
            assignments_sheet.append_row([username, user_id, str(module), "Submitted", content, "", timestamp, "", "", ""])
            context.user_data["submission_row"] = row_index
            logger.debug(f"submit_media_upload: Logged submission to Google Sheets for user {user_id}, module {module}, row {row_index}")
        is_private = update.message.chat.type == "private"
        await update.message.reply_text(
            random.choice(submit_confirm),
            reply_markup=main_keyboard if is_private else ReplyKeyboardRemove()
        )
        grade_button = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{row_index}")]])
        forward_text = f"Submission from {username} - Module {module}: {content}"
        await forward_to_group(context.bot, ASSIGNMENTS_GROUP_ID, forward_text, photo=photo, video=video, reply_markup=grade_button)
        logger.info(f"submit_media_upload: Submission completed for user {user_id}, module {module}")
    except Exception as e:
        logger.error(f"submit_media_upload: Error for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Submission failed. Try again!")
    return ConversationHandler.END

async def sharewin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"sharewin_start: Received /sharewin from user {update.effective_user.id}")
    if not db_is_verified(update.effective_user.id):
        logger.debug(f"sharewin_start: User {update.effective_user.id} not verified")
        await update.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data="win_text"),
         InlineKeyboardButton("Video", callback_data="win_video"),
         InlineKeyboardButton("Image", callback_data="win_image")]
        ])
    await update.message.reply_text("Share your win as Text, Video, or Image?", reply_markup=keyboard)
    return MEDIA_TYPE

async def sharewin_media_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    media_type = query.data.replace("win_", "")
    logger.debug(f"sharewin_media_type: Received media type {media_type} from user {update.effective_user.id}")
    if media_type not in ("text", "video", "image"):
        await query.message.reply_text("Choose Text, Video, or Image!")
        return MEDIA_TYPE
    context.user_data["media_type"] = media_type
    await query.message.reply_text(f"Send your {media_type.upper()} win:")
    return MEDIA_UPLOAD

async def sharewin_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username = get_username(update.effective_user)
    user_id = update.effective_user.id
    media_type = context.user_data.get("media_type")
    logger.debug(f"sharewin_media_upload: Processing for user {user_id}, media_type {media_type}")
    content = ""
    if media_type == "text":
        content = update.message.text or ""
    elif media_type == "image" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        content = f"(Photo file_id: {file_id})"
    elif media_type == "video" and update.message.video:
        file_id = update.message.video.file_id
        content = f"(Video file_id: {file_id})"
    else:
        logger.warning(f"sharewin_media_upload: Invalid media upload for {media_type} from user {user_id}")
        await update.message.reply_text(f"Please send a {media_type.upper()}.")
        return MEDIA_UPLOAD
    if not content:
        await update.message.reply_text("Win cannot be empty!")
        return MEDIA_UPLOAD
    timestamp = get_timestamp()
    try:
        if wins_sheet:
            wins_sheet.append_row([username, user_id, "Small Win", content, timestamp])
        is_private = update.message.chat.type == "private"
        await update.message.reply_text(
            random.choice(win_confirm),
            reply_markup=main_keyboard if is_private else ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in sharewin_media_upload: {e}", exc_info=True)
        await update.message.reply_text("Win share failed. Try again!")
    return ConversationHandler.END

async def grade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"grade_start: Received /grade from user {update.effective_user.id}")
    if update.effective_user.id != ADMIN_ID:
        logger.debug(f"grade_start: User {update.effective_user.id} is not admin")
        await update.message.reply_text("Only admins can grade submissions.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username to grade:", reply_markup=ReplyKeyboardRemove())
    return USERNAME

async def grade_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"grade_username: Received username from user {update.effective_user.id}")
    context.user_data["username"] = update.message.text.strip()
    await update.message.reply_text("Which module? (1-12)")
    return MODULE_GRADE

async def grade_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"grade_module: Received module from user {update.effective_user.id}")
    try:
        module = int(update.message.text.strip())
        if not 1 <= module <= 12:
            raise ValueError
        context.user_data["module"] = module
        score_buttons = [
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]
        ]
        await update.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup(score_buttons))
        return GRADE_SCORE
    except ValueError:
        await update.message.reply_text("Enter a number between 1-12.")
        return MODULE_GRADE

async def grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    score = int(query.data.replace("score_", ""))
    logger.debug(f"grade_score: Received score {score} from user {update.effective_user.id}")
    context.user_data["score"] = score
    context.user_data["message_id"] = query.message.message_id  # Store message ID for editing
    comment_buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Comment", callback_data="comment_yes"),
         InlineKeyboardButton("✅ No Comment", callback_data="comment_no")]
    ])
    try:
        await query.message.edit_reply_markup(reply_markup=comment_buttons)
        await query.message.reply_text(f"Score {score}/10 selected. Add a comment?", reply_markup=None)
    except Exception as e:
        logger.error(f"grade_score: Error editing message: {e}")
        await query.message.reply_text(f"Score {score}/10 selected. Add a comment?", reply_markup=comment_buttons)
    return GRADE_COMMENT_TYPE

async def grade_comment_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data
    logger.debug(f"grade_comment_type: Received choice {choice} from user {update.effective_user.id}")
    context.user_data["message_id"] = query.message.message_id  # Store message ID for editing
    if choice == "comment_no":
        await complete_grading(update, context, "", "")
        return ConversationHandler.END
    type_buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data="comment_text"),
         InlineKeyboardButton("Audio", callback_data="comment_audio"),
         InlineKeyboardButton("Video", callback_data="comment_video")]
    ])
    try:
        await query.message.edit_reply_markup(reply_markup=type_buttons)
        await query.message.reply_text("Choose comment type:", reply_markup=None)
    except Exception as e:
        logger.error(f"grade_comment_type: Error editing message: {e}")
        await query.message.reply_text("Choose comment type:", reply_markup=type_buttons)
    return GRADE_COMMENT

async def grade_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    comment_type = query.data.replace("comment_", "").capitalize()
    logger.debug(f"grade_comment: Received comment type {comment_type} from user {update.effective_user.id}")
    context.user_data["comment_type"] = comment_type
    try:
        await query.message.edit_reply_markup(reply_markup=None)  # Remove comment type buttons
        await query.message.reply_text(f"Send your {comment_type} comment:")
    except Exception as e:
        logger.error(f"grade_comment: Error editing message: {e}")
        await query.message.reply_text(f"Send your {comment_type} comment:")
    return GRADE_COMMENT_CONTENT

async def grade_comment_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"grade_comment_content: Received comment from user {update.effective_user.id}")
    comment_type = context.user_data.get("comment_type")
    comment_content = ""
    if comment_type == "Text" and update.message.text:
        comment_content = update.message.text
    elif comment_type == "Audio" and update.message.audio:
        comment_content = update.message.audio.file_id
    elif comment_type == "Video" and update.message.video:
        comment_content = update.message.video.file_id
    else:
        await update.message.reply_text(f"Please send a {comment_type} comment.")
        return GRADE_COMMENT_CONTENT
    await complete_grading(update, context, comment_type, comment_content)
    return ConversationHandler.END

async def complete_grading(update: Update, context: ContextTypes.DEFAULT_TYPE, comment_type: str, comment_content: str) -> None:
    username = context.user_data.get("username")
    module = context.user_data.get("module")
    score = context.user_data.get("score")
    message_id = context.user_data.get("message_id")
    logger.debug(f"complete_grading: Grading for user {username}, module {module}, score {score}, comment_type {comment_type}")
    try:
        if not assignments_sheet:
            await update.effective_message.reply_text("Google Sheets not configured.")
            return
        assignments = assignments_sheet.get_all_values()
        found = False
        user_id = None
        for i, row in enumerate(assignments[1:], start=2):
            try:
                row_module = int(row[2])
            except (ValueError, IndexError):
                continue
            if row[0] == username and row_module == module and row[3] == "Submitted":
                user_id = int(row[1])
                assignments_sheet.update_cell(i, 4, "Graded")
                assignments_sheet.update_cell(i, 6, f"Score: {score}/10")
                assignments_sheet.update_cell(i, 7, get_timestamp())
                assignments_sheet.update_cell(i, 8, str(score))
                assignments_sheet.update_cell(i, 9, comment_type)
                assignments_sheet.update_cell(i, 10, comment_content)
                found = True
                break
        if found:
            try:
                if message_id:
                    await context.bot.edit_message_reply_markup(
                        chat_id=ASSIGNMENTS_GROUP_ID,
                        message_id=message_id,
                        reply_markup=None
                    )
                await context.bot.send_message(
                    chat_id=ASSIGNMENTS_GROUP_ID,
                    text=random.choice(grade_confirm),
                    reply_to_message_id=message_id
                )
            except Exception as e:
                logger.error(f"complete_grading: Error editing message: {e}")
                await update.effective_message.reply_text(
                    random.choice(grade_confirm),
                    reply_markup=ReplyKeyboardRemove()
                )
            completed_modules = set(row[2] for row in assignments[1:] if row[0] == username and row[3] == "Graded")
            graded_count = len(completed_modules)
            if wins_sheet:
                wins = wins_sheet.get_all_values()
                win_count = len([row for row in wins[1:] if row[0] == username])
            else:
                win_count = 0
            if graded_count >= 3 and win_count >= 3 and user_id:
                await context.bot.send_message(
                    user_id,
                    "🎉 AVAP Achiever Badge earned! Keep shining!",
                    reply_markup=main_keyboard if user_id == update.effective_user.id else ReplyKeyboardRemove()
                )
        else:
            await update.effective_message.reply_text("No submission found.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
    except Exception as e:
        logger.error(f"Error grading: {e}", exc_info=True)
        await update.effective_message.reply_text("Grading failed. Try again.", reply_markup=ReplyKeyboardRemove())

async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        logger.debug(f"grade_inline_start: User {update.effective_user.id} is not admin")
        await query.message.reply_text("Only admins can grade submissions.")
        return ConversationHandler.END
    row_index = int(query.data.replace("grade_", ""))
    context.user_data["submission_row"] = row_index
    context.user_data["message_id"] = query.message.message_id  # Store message ID for editing
    logger.debug(f"grade_inline_start: Grading submission at row {row_index} for user {update.effective_user.id}")
    if not assignments_sheet:
        await query.message.reply_text("Google Sheets not configured.")
        return ConversationHandler.END
    assignments = assignments_sheet.get_all_values()
    try:
        row = assignments[row_index - 1]
        if row[3] != "Submitted":
            await query.message.reply_text("This submission is already graded or invalid.")
            return ConversationHandler.END
        context.user_data["username"] = row[0]
        context.user_data["module"] = int(row[2])
        score_buttons = [
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]
        ]
        try:
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(score_buttons))
            await query.message.reply_text(f"Grading submission from {row[0]} (Module {row[2]}). Select a score (1-10):", reply_markup=None)
        except Exception as e:
            logger.error(f"grade_inline_start: Error editing message: {e}")
            await query.message.reply_text(f"Grading submission from {row[0]} (Module {row[2]}). Select a score (1-10):", reply_markup=InlineKeyboardMarkup(score_buttons))
        return GRADE_SCORE
    except (IndexError, ValueError) as e:
        logger.error(f"grade_inline_start: Invalid row {row_index}: {e}")
        await query.message.reply_text("Invalid submission. Try again.")
        return ConversationHandler.END

async def get_submission_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"get_submission_start: Received /get_submission from user {update.effective_user.id}")
    if update.effective_user.id != ADMIN_ID:
        logger.debug(f"get_submission_start: User {update.effective_user.id} is not admin")
        await update.message.reply_text("Only admins can view submissions.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username:", reply_markup=ReplyKeyboardRemove())
    return USERNAME_GET

async def get_submission_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"get_submission_username: Received username from user {update.effective_user.id}")
    context.user_data["username"] = update.message.text.strip()
    await update.message.reply_text("Which module? (1-12)")
    return MODULE_GET

async def get_submission_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"get_submission_module: Received module from user {update.effective_user.id}")
    try:
        module = int(update.message.text.strip())
        username = context.user_data.get("username")
        if not assignments_sheet:
            await update.message.reply_text("Google Sheets not configured.")
            return ConversationHandler.END
        assignments = assignments_sheet.get_all_values()
        found = False
        for row in assignments[1:]:
            try:
                row_module = int(row[2])
            except (ValueError, IndexError):
                continue
            if row[0] == username and row_module == module:
                content = row[4]
                status = row[3]
                feedback = row[5] if len(row) > 5 else ""
                timestamp = row[6] if len(row) > 6 else ""
                score = row[7] if len(row) > 7 else "Not graded"
                comment_type = row[8] if len(row) > 8 else ""
                comment_content = row[9] if len(row) > 9 else ""
                message = (
                    f"Submission for {username}, Module {module}:\n"
                    f"Status: {status}\n"
                    f"Content: {content}\n"
                    f"Feedback: {feedback}\n"
                    f"Score: {score}/10\n"
                    f"Timestamp: {timestamp}"
                )
                await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
                if comment_type == "Text" and comment_content:
                    await update.message.reply_text(f"Comment: {comment_content}")
                elif comment_type == "Audio" and comment_content:
                    await update.message.reply_audio(comment_content, caption="Comment")
                elif comment_type == "Video" and comment_content:
                    await update.message.reply_video(comment_content, caption="Comment")
                if "(Photo file_id:" in content:
                    file_id = content.split("file_id: ")[1].rstrip(")")
                    await update.message.reply_photo(file_id)
                elif "(Video file_id:" in content:
                    file_id = content.split("file_id: ")[1].rstrip(")")
                    await update.message.reply_video(file_id)
                found = True
                break
        if not found:
            await update.message.reply_text("No submission found.", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
    except Exception as e:
        logger.error(f"Error in get_submission_module: {e}", exc_info=True)
        await update.message.reply_text("Failed to retrieve submission. Try again.")
    return ConversationHandler.END

async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"ask_start: Received /ask from user {update.effective_user.id}")
    if not db_is_verified(update.effective_user.id):
        logger.debug(f"ask_start: User {update.effective_user.id} not verified")
        await update.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    await update.message.reply_text("What's your question?", reply_markup=ReplyKeyboardRemove())
    return QUESTION

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"ask_question: Received question from user {update.effective_user.id}")
    question = update.message.text.strip()
    username = get_username(update.effective_user)
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    timestamp = get_timestamp()
    try:
        # Store in Google Sheets instead of SQLite
        if faq_sheet:
            row_index = len(faq_sheet.get_all_values()) + 1
            faq_sheet.append_row([question, "", "", "", username, timestamp, str(row_index)])
            question_id = row_index
        else:
            logger.warning("ask_question: FAQ sheet not configured")
            return ConversationHandler.END
        answer_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Answer", callback_data=f"answer_{question_id}")]
        ])
        await forward_to_group(
            context.bot,
            QUESTIONS_GROUP_ID,
            f"Question from {username} (ID: {question_id}):\n{question}",
            reply_markup=answer_button
        )
        await update.message.reply_text(
            random.choice(ask_confirm),
            reply_markup=main_keyboard if update.message.chat.type == "private" else ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error in ask_question: {e}", exc_info=True)
        await update.message.reply_text("Failed to submit question. Try again.")
    return ConversationHandler.END

async def answer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.debug(f"answer_start: Received callback {query.data} from user {update.effective_user.id}")
    if not query.data.startswith("answer_"):
        return ConversationHandler.END
    question_id = query.data.replace("answer_", "")
    context.user_data["question_id"] = question_id
    await query.message.reply_text("Enter your answer:")
    return ANSWER_TEXT

async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.debug(f"answer_text: Received answer from user {update.effective_user.id}")
    answer = update.message.text.strip()
    question_id = context.user_data.get("question_id")
    try:
        if not faq_sheet:
            await update.message.reply_text("FAQ sheet not configured.")
            return ConversationHandler.END
        faq = faq_sheet.get_all_values()
        found = False
        for i, row in enumerate(faq[1:], start=2):
            if row[6] == question_id and row[1] == "":
                telegram_id = int(row[4]) if row[4].isdigit() else None
                chat_id = None  # Chat ID not stored in FAQ sheet; rely on QUESTIONS_GROUP_ID
                question = row[0]
                faq_sheet.update_cell(i, 2, answer)
                faq_sheet.update_cell(i, 3, "Text")
                faq_sheet.update_cell(i, 5, get_username(update.effective_user))
                found = True
                break
        if not found:
            await update.message.reply_text("Question not found.")
            return ConversationHandler.END
        # Forward answer to QUESTIONS_GROUP_ID (since chat_id isn't stored)
        await context.bot.send_message(
            QUESTIONS_GROUP_ID,
            f"Answer to question (ID: {question_id}):\nQ: {question}\nA: {answer}",
            reply_markup=None
        )
        await update.message.reply_text(random.choice(answer_sent))
        context.user_data.clear()
    except Exception as e:
        logger.error(f"Error in answer_text: {e}", exc_info=True)
        await update.message.reply_text("Failed to send answer. Try again.")
    return ConversationHandler.END

async def group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text and update.message.text.startswith("/"):
        return
    if update.effective_chat.id in [ASSIGNMENTS_GROUP_ID, QUESTIONS_GROUP_ID, VERIFICATION_GROUP_ID, SUPPORT_GROUP_ID]:
        return
    if not db_is_verified(update.effective_user.id):
        logger.debug(f"group_handler: User {update.effective_user.id} not verified in chat {update.effective_chat.id}")
        await update.message.reply_text(
            f"Join our community for support: {SUPPORT_GROUP_TITLE}\n{LANDING_PAGE_LINK}",
            reply_markup=verify_keyboard
        )

async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_request = update.chat_join_request
    logger.debug(f"join_request: Received join request from user {join_request.from_user.id} for chat {join_request.chat.id}")
    if join_request.chat.id != SUPPORT_GROUP_ID:
        return
    if db_is_verified(join_request.from_user.id):
        await join_request.approve()
        logger.info(f"Approved join request for verified user {join_request.from_user.id}")
    else:
        await join_request.decline()
        await context.bot.send_message(
            join_request.from_user.id,
            "Verify your account to join the support group!",
            reply_markup=verify_keyboard
        )

def add_handlers(app: Application) -> None:
    logger.debug("add_handlers: Registering handlers")
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Check Status$"), status))
    app.add_handler(CallbackQueryHandler(view_comments, pattern="^view_comments$"))
    
    submit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("submit", submit_start),
            MessageHandler(filters.Regex(r"^📤 Submit Assignment$"), submit_start)
        ],
        states={
            MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module)],
            MEDIA_TYPE: [CallbackQueryHandler(submit_media_type, pattern="media_(video|image)")],
            MEDIA_UPLOAD: [MessageHandler(filters.PHOTO | filters.VIDEO, submit_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(submit_conv)
    
    sharewin_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sharewin", sharewin_start),
            MessageHandler(filters.Regex(r"^🎉 Share Small Win$"), sharewin_start)
        ],
        states={
            MEDIA_TYPE: [CallbackQueryHandler(sharewin_media_type, pattern="win_(text|video|image)")],
            MEDIA_UPLOAD: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, sharewin_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(sharewin_conv)
    
    grade_conv = ConversationHandler(
        entry_points=[CommandHandler("grade", grade_start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_username)],
            MODULE_GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_module)],
            GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="score_")],
            GRADE_COMMENT_TYPE: [CallbackQueryHandler(grade_comment_type, pattern="comment_(yes|no)")],
            GRADE_COMMENT: [CallbackQueryHandler(grade_comment, pattern="comment_(text|audio|video)")],
            GRADE_COMMENT_CONTENT: [MessageHandler(filters.TEXT | filters.AUDIO | filters.VIDEO, grade_comment_content)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(grade_conv)
    
    grade_inline_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grade_inline_start, pattern="grade_")],
        states={
            GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="score_")],
            GRADE_COMMENT_TYPE: [CallbackQueryHandler(grade_comment_type, pattern="comment_(yes|no)")],
            GRADE_COMMENT: [CallbackQueryHandler(grade_comment, pattern="comment_(text|audio|video)")],
            GRADE_COMMENT_CONTENT: [MessageHandler(filters.TEXT | filters.AUDIO | filters.VIDEO, grade_comment_content)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(grade_inline_conv)
    
    get_submission_conv = ConversationHandler(
        entry_points=[CommandHandler("get_submission", get_submission_start)],
        states={
            USERNAME_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_username)],
            MODULE_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_module)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(get_submission_conv)
    
    ask_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ask", ask_start),
            MessageHandler(filters.Regex(r"^❓ Ask a Question$"), ask_start)
        ],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(ask_conv)
    
    answer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(answer_start, pattern="answer_")],
        states={
            ANSWER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(answer_conv)
    
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(add_student_conv)
    
    verify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(verify_start, pattern="^verify_prompt$")],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    app.add_handler(verify_conv)
    
    app.add_handler(ChatJoinRequestHandler(join_request))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_handler))
    app.add_handler(MessageHandler(filters.ALL, debug_update))
    app.add_error_handler(error_handler)
    logger.debug("add_handlers: All handlers registered")

async def webhook_update(request: Request, app: Application):
    """Process webhook updates."""
    try:
        update = Update.de_json(await request.json(), app.bot)
        await app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook update error: {e}")
        return {"status": "error"}

async def main() -> None:
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        add_handlers(app)
        Thread(target=run_health_check_server, daemon=True).start()
        await app.initialize()
        await app.start()
        # Schedule Sunday reminder at 6 PM WAT
        app.job_queue.run_daily(
            sunday_reminder,
            time=datetime.time(hour=18, minute=0, tzinfo=pytz.timezone("Africa/Lagos")),
            days=(6,)  # Sunday
        )
        # Sync verifications from Google Sheets
        sync_verifications_from_sheets()
        # Set webhook
        webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        await app.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
        # Start FastAPI server
        uvicorn.run(
            "bot:webhook_app",
            host="0.0.0.0",
            port=10000,
            log_level="info",
            factory=True
        )
    except InvalidToken:
        logger.error("Invalid TELEGRAM_TOKEN. Exiting.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting bot: {e}", exc_info=True)
        sys.exit(1)

# FastAPI app for webhook
webhook_app = FastAPI()
webhook_app.post("/webhook")(lambda request: webhook_update(request, app))

if __name__ == "__main__":
    asyncio.run(main())
