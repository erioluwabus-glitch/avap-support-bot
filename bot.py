import os
import json
import logging
import datetime
import pytz
import random
import sqlite3
import hashlib
import sys
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputTextMessageContent, InlineQueryResultArticle, ChatJoinRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChatJoinRequestHandler
)
from fastapi import FastAPI, Request
import uvicorn
from dotenv import load_dotenv
import gspread
from google.oauth2 import service_account

# States for conversation handlers
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = 50, 51, 52
MODULE, MEDIA_TYPE, MEDIA_UPLOAD = 10, 11, 12
USERNAME, MODULE_GRADE, GRADE_SCORE, GRADE_COMMENT_TYPE, GRADE_COMMENT, GRADE_COMMENT_CONTENT = 20, 21, 80, 81, 82, 83
USERNAME_GET, MODULE_GET = 30, 31
QUESTION = 40
ANSWER_TEXT = 70
ADD_STUDENT_NAME, ADD_STUDENT_PHONE, ADD_STUDENT_EMAIL = 60, 61, 62
VIEW_COMMENTS = 90

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", mode='a', encoding='utf-8'), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Parse integer environment variables
def parse_int_env(name: str, default=None) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v else default
    except (ValueError, TypeError):
        logger.warning(f"Invalid {name} ({v}) - using default {default}.")
        return default

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN is not set. Exiting.")
    sys.exit(1)
ADMIN_ID = parse_int_env("ADMIN_ID", None)
ASSIGNMENTS_GROUP_ID = parse_int_env("ASSIGNMENTS_GROUP_ID", None)
QUESTIONS_GROUP_ID = parse_int_env("QUESTIONS_GROUP_ID", None)
VERIFICATION_GROUP_ID = parse_int_env("VERIFICATION_GROUP_ID", None)
SUPPORT_GROUP_ID = parse_int_env("SUPPORT_GROUP_ID", None)
SUPPORT_GROUP_TITLE = os.getenv("SUPPORT_GROUP_TITLE", "AVAP Support Community")
GOOGLE_CREDENTIALS_STR = os.getenv("GOOGLE_CREDENTIALS")
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_STUDENT_TAG_ID = parse_int_env("SYSTEME_VERIFIED_STUDENT_TAG_ID", 1647470)
LANDING_PAGE_LINK = os.getenv("LANDING_PAGE_LINK", "https://your-landing.com/walkthrough")
PORT = int(os.getenv("PORT", 8000))  # Use Render's PORT or default to 8000

# FastAPI app for webhook and health check
webhook_app = FastAPI()

# SQLite database setup (in-memory)
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

# Google Sheets initialization
verifications_sheet = assignments_sheet = wins_sheet = faq_sheet = None
try:
    if GOOGLE_CREDENTIALS_STR:
        google_credentials_dict = json.loads(GOOGLE_CREDENTIALS_STR)
        credentials = service_account.Credentials.from_service_account_info(
            google_credentials_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]
        )
        client = gspread.authorize(credentials)
        sheet = client.open("AVAPSupport")
        for title, headers in [
            ("Verifications", ["Name", "Email", "Phone", "Telegram ID", "Verified"]),
            ("Assignments", ["Username", "Telegram ID", "Module", "Status", "Content", "Feedback", "Timestamp", "Score", "Comment Type", "Comment Content"]),
            ("Wins", ["Username", "Telegram ID", "Type", "Content", "Timestamp"]),
            ("FAQ", ["Question", "Answer", "Answer Type", "File ID", "Username", "Timestamp", "Question ID"])
        ]:
            try:
                worksheet = sheet.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sheet.add_worksheet(title=title, rows=1000, cols=len(headers))
                worksheet.append_row(headers)
            globals()[f"{title.lower()}_sheet"] = worksheet
        logger.info("Google Sheets connected successfully.")
except Exception as e:
    logger.error(f"Error connecting to Google Sheets: {e}")
    verifications_sheet = assignments_sheet = wins_sheet = faq_sheet = None

# Sync verifications from Google Sheets to SQLite
def sync_verifications_from_sheets():
    if not verifications_sheet:
        logger.warning("No verifications_sheet available")
        return
    try:
        verifications = verifications_sheet.get_all_values()
        cursor.execute("DELETE FROM verifications")
        for row in verifications[1:]:
            name, email, phone, telegram_id, status = row
            hash_value = hashlib.sha256(f"{name}{email}{phone}{telegram_id or 0}".encode()).hexdigest()
            claimed = 1 if status == "Verified" and telegram_id.isdigit() else 0
            cursor.execute(
                "INSERT OR IGNORE INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
                (hash_value, int(telegram_id) if telegram_id.isdigit() else 0, name, email, phone, claimed)
            )
        conn.commit()
        logger.info("Synced verifications from Google Sheets to in-memory SQLite")
    except Exception as e:
        logger.error(f"Error syncing verifications: {e}")

# Utility functions
def get_username(user):
    return user.username or f"User_{user.id}" if user else "Unknown"

def get_timestamp():
    return datetime.datetime.now(pytz.timezone("Africa/Lagos")).isoformat()

def db_is_verified(telegram_id):
    cursor.execute("SELECT claimed FROM verifications WHERE telegram_id = ? AND claimed = 1", (telegram_id,))
    return bool(cursor.fetchone())

async def add_to_systeme(name, email, phone):
    if not SYSTEME_API_KEY or not SYSTEME_VERIFIED_STUDENT_TAG_ID:
        logger.warning("Systeme.io not configured")
        return False
    base_url = "https://api.systeme.io/api"
    headers = {"Authorization": f"Bearer {SYSTEME_API_KEY}", "Content-Type": "application/json"}
    name_parts = name.strip().split(" ", 1)
    first_name, last_name = name_parts[0], name_parts[1] if len(name_parts) > 1 else ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(f"{base_url}/contacts", headers=headers, json={
                "email": email, "first_name": first_name, "last_name": last_name, "phone": phone
            })
            if resp.status_code in (200, 201):
                contact_id = resp.json().get("id")
                if contact_id:
                    tag_resp = await client.post(f"{base_url}/contacts/{contact_id}/tags", headers=headers, json={"tag_id": SYSTEME_VERIFIED_STUDENT_TAG_ID})
                    if tag_resp.status_code in (200, 201, 204):
                        logger.info(f"Added verified tag to {email} (ID: {contact_id})")
                        return True
                logger.error(f"No contact ID in response: {resp.text}")
                return False
            elif resp.status_code == 422 and "email: This value is already used" in resp.text:
                search_resp = await client.get(f"{base_url}/contacts", headers=headers, params={"email": email})
                if search_resp.status_code == 200:
                    contacts = search_resp.json().get("data", [])
                    contact = next((c for c in contacts if c.get("email") == email), None)
                    if contact and contact.get("id"):
                        contact_id = contact.get("id")
                        if any(tag.get("id") == SYSTEME_VERIFIED_STUDENT_TAG_ID for tag in contact.get("tags", [])):
                            logger.info(f"Contact {email} already has verified tag")
                            return True
                        tag_resp = await client.post(f"{base_url}/contacts/{contact_id}/tags", headers=headers, json={"tag_id": SYSTEME_VERIFIED_STUDENT_TAG_ID})
                        if tag_resp.status_code in (200, 201, 204):
                            logger.info(f"Added verified tag to existing {email} (ID: {contact_id})")
                            return True
                    logger.error(f"No contact found for {email}")
                    return False
                logger.error(f"Failed to fetch contact: {search_resp.text}")
                return False
            logger.error(f"Contact creation failed: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Error adding to Systeme.io for {email}: {e}")
            return False

async def forward_to_group(bot, group_id, text, photo=None, video=None, reply_markup=None):
    if not group_id:
        logger.warning("No group_id provided")
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

async def sunday_reminder(context: ContextTypes.DEFAULT_TYPE):
    if not verifications_sheet:
        logger.warning("No verifications_sheet for Sunday reminder")
        return
    try:
        verifications = verifications_sheet.get_all_values()
        for row in verifications[1:]:
            if row[4] == "Verified" and row[3].isdigit():
                try:
                    await context.bot.send_message(
                        int(row[3]),
                        "🌞 Sunday Reminder: Check your progress with /status and share a win with /sharewin!",
                        reply_markup=main_keyboard
                    )
                except Exception as e:
                    logger.error(f"Error sending DM to {row[3]}: {e}")
        await context.bot.send_message(
            SUPPORT_GROUP_ID,
            "🌞 Sunday Reminder: Keep pushing forward! Check /status or share a /sharewin!",
            reply_markup=main_keyboard
        )
    except Exception as e:
        logger.error(f"Error in Sunday reminder: {e}")

# Keyboards and messages
verify_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Verify Now", callback_data="verify_prompt")]])
main_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📤 Submit Assignment", callback_data="submit"), InlineKeyboardButton("🎉 Share Small Win", callback_data="share_win")],
    [InlineKeyboardButton("📊 Check Status", callback_data="status"), InlineKeyboardButton("❓ Ask a Question", callback_data="ask")]
])
start_messages = [
    "🌟 Welcome to AVAP! Verify your account to unlock features. Click '🔒 Verify Now' below!",
    "🚀 Welcome to AVAP! Verify to get started. Click '🔒 Verify Now' below!"
]
submit_confirm = ["Boom! Submission received!", "Great work! Submission in!"]
win_confirm = ["Victory logged!", "Epic win shared!"]
grade_confirm = ["✅ Graded!", "🎉 Submission graded!"]
ask_confirm = ["Question received!", "Your question is queued!"]

# Handlers
async def error_handler(update, context):
    logger.error(f"Exception: {context.error}\nUpdate: {update}", exc_info=True)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Something went wrong. Try again later.")
        except Exception:
            pass
    if ADMIN_ID and isinstance(context.error, Exception):
        try:
            await context.bot.send_message(ADMIN_ID, f"⚠️ Error: {context.error}\nUpdate: {update}"[:4000])
        except Exception as e:
            logger.warning(f"Could not send error to admin: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    logger.debug(f"start_command: /start from {telegram_id}")
    if db_is_verified(telegram_id):
        await update.message.reply_text("You're verified! Choose an action:", reply_markup=main_keyboard)
    else:
        await update.message.reply_text(random.choice(start_messages), reply_markup=verify_keyboard)

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.lower().strip()
    user = update.effective_user
    if not user:
        return
    results = []
    telegram_id = user.id
    is_verified = db_is_verified(telegram_id)
    logger.debug(f"inline_query: Query '{query}' from {telegram_id}, verified={is_verified}")
    if not query:
        results.append(InlineQueryResultArticle(
            id="welcome", title="AVAP Bot", description="Verify to unlock features!",
            input_message_content=InputTextMessageContent("Use /start to begin"), reply_markup=verify_keyboard
        ))
    elif query == "verify" and not is_verified:
        results.append(InlineQueryResultArticle(
            id="verify", title="Verify Account", description="Start verification",
            input_message_content=InputTextMessageContent("Click to verify"), reply_markup=verify_keyboard
        ))
    await update.inline_query.answer(results, cache_time=0)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    if not db_is_verified(telegram_id):
        await query.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return
    username = get_username(update.effective_user)
    completed_modules = []
    total_score = 0
    assignment_count = 0
    if assignments_sheet:
        assignments = assignments_sheet.get_all_values()
        for row in assignments[1:]:
            if len(row) < 8 or row[0] != username or row[3] != "Graded":
                continue
            module, score = row[2], int(row[7]) if row[7].isdigit() else 0
            completed_modules.append((module, score))
            total_score += score
            assignment_count += 1
    total_wins = len([row for row in wins_sheet.get_all_values()[1:] if wins_sheet and row[0] == username]) if wins_sheet else 0
    modules_str = ", ".join([f"Module {m} (Score: {s}/10)" for m, s in sorted(completed_modules, key=lambda x: int(x[0]))]) or "None"
    message = f"📈 Progress:\nAssignments: {assignment_count}\nModules: {modules_str}\nTotal Score: {total_score}/10\nWins: {total_wins}"
    await query.message.reply_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 View Comments", callback_data="view_comments")]]))

async def view_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = get_username(update.effective_user)
    if not assignments_sheet:
        await query.message.reply_text("Google Sheets not configured.")
        return
    assignments = assignments_sheet.get_all_values()
    comments = [(row[2], row[8], row[9]) for row in assignments[1:] if len(row) > 9 and row[0] == username and row[3] == "Graded" and row[8] and row[9]]
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

async def verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    if db_is_verified(telegram_id):
        await query.message.reply_text("You're verified! Choose an action:", reply_markup=main_keyboard)
        return ConversationHandler.END
    await query.message.reply_text("Enter your full name:")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Enter your phone number:")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    name = context.user_data.get("name", "")
    phone = context.user_data.get("phone", "")
    telegram_id = update.effective_user.id
    username = get_username(update.effective_user)
    hash_value = hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()
    cursor.execute(
        "SELECT hash FROM verifications WHERE LOWER(name) = LOWER(?) AND LOWER(email) = LOWER(?) AND phone = ? AND claimed = 0",
        (name, email, phone)
    )
    result = cursor.fetchone()
    if not result and verifications_sheet:
        verifications = verifications_sheet.get_all_values()
        for row in verifications[1:]:
            if row[0].lower() == name.lower() and row[1].lower() == email.lower() and row[2] == phone and row[4] == "Pending":
                hash_value = hashlib.sha256(f"{name}{email}{phone}0".encode()).hexdigest()
                cursor.execute(
                    "INSERT INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
                    (hash_value, 0, name, email, phone, 0)
                )
                conn.commit()
                result = (hash_value,)
                break
    if not result:
        await update.message.reply_text("Details not found. Contact admin to add you.")
        return ConversationHandler.END
    hash_value = result[0]
    cursor.execute("UPDATE verifications SET claimed = 1, telegram_id = ? WHERE hash = ?", (telegram_id, hash_value))
    conn.commit()
    if verifications_sheet:
        for i, row in enumerate(verifications_sheet.get_all_values()[1:], start=2):
            if row[0].lower() == name.lower() and row[1].lower() == email.lower() and row[2] == phone and row[4] == "Pending":
                verifications_sheet.update_cell(i, 4, str(telegram_id))
                verifications_sheet.update_cell(i, 5, "Verified")
                break
    await add_to_systeme(name, email, phone)
    await update.message.reply_text("✅ Verified! Welcome to AVAP!", reply_markup=main_keyboard)
    await update.message.reply_text(f"Check out our walkthrough: {LANDING_PAGE_LINK}")
    return ConversationHandler.END

async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or update.effective_chat.id != VERIFICATION_GROUP_ID:
        await update.message.reply_text("Only admins can add students in the verification group.")
        return ConversationHandler.END
    await update.message.reply_text("Enter student's full name:")
    return ADD_STUDENT_NAME

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Enter student's phone number:")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Enter student's email:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    name, phone = context.user_data.get("name", ""), context.user_data.get("phone", "")
    telegram_id = 0
    hash_value = hashlib.sha256(f"{name}{email}{phone}{telegram_id}".encode()).hexdigest()
    cursor.execute(
        "INSERT INTO verifications (hash, telegram_id, name, email, phone, claimed) VALUES (?, ?, ?, ?, ?, ?)",
        (hash_value, telegram_id, name, email, phone, 0)
    )
    conn.commit()
    if verifications_sheet:
        verifications_sheet.append_row([name, email, phone, "0", "Pending"])
    await update.message.reply_text(f"Student {name} added. They can verify with these details.")
    context.user_data.clear()
    return ConversationHandler.END

async def submit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not db_is_verified(update.effective_user.id):
        await query.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    await query.message.reply_text("Which module? (1-12)")
    return MODULE

async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        module = int(update.message.text.strip())
        if not 1 <= module <= 12:
            await update.message.reply_text("Enter a number between 1-12.")
            return MODULE
        context.user_data["module"] = module
        await update.message.reply_text("Video or Image?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Video", callback_data="media_video"), InlineKeyboardButton("Image", callback_data="media_image")]
        ]))
        return MEDIA_TYPE
    except ValueError:
        await update.message.reply_text("Enter a valid number (1-12).")
        return MODULE

async def submit_media_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    media_type = query.data.replace("media_", "")
    if media_type not in ("video", "image"):
        await query.message.reply_text("Choose Video or Image!")
        return MEDIA_TYPE
    context.user_data["media_type"] = media_type
    await query.message.reply_text(f"Send your {media_type.upper()}:")
    return MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = get_username(update.effective_user)
    user_id = update.effective_user.id
    module = context.user_data.get("module")
    media_type = context.user_data.get("media_type")
    photo = video = content = ""
    if media_type == "image" and update.message.photo:
        file_id = update.message.photo[-1].file_id
        photo, content = file_id, f"(Photo file_id: {file_id})"
    elif media_type == "video" and update.message.video:
        file_id = update.message.video.file_id
        video, content = file_id, f"(Video file_id: {file_id})"
    else:
        await update.message.reply_text(f"Please send a {media_type.upper()}.")
        return MEDIA_UPLOAD
    timestamp = get_timestamp()
    if assignments_sheet:
        row_index = len(assignments_sheet.get_all_values()) + 1
        assignments_sheet.append_row([username, user_id, str(module), "Submitted", content, "", timestamp, "", "", ""])
        context.user_data["submission_row"] = row_index
    await update.message.reply_text(random.choice(submit_confirm), reply_markup=main_keyboard)
    await forward_to_group(
        context.bot, ASSIGNMENTS_GROUP_ID,
        f"Submission from {username} - Module {module}: {content}",
        photo=photo, video=video,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade", callback_data=f"grade_{row_index}")]])
    )
    return ConversationHandler.END

async def sharewin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not db_is_verified(update.effective_user.id):
        await query.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    await query.message.reply_text("Share your win as Text, Video, or Image?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data="win_text"), InlineKeyboardButton("Video", callback_data="win_video"), InlineKeyboardButton("Image", callback_data="win_image")]
    ]))
    return MEDIA_TYPE

async def sharewin_media_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    media_type = query.data.replace("win_", "")
    if media_type not in ("text", "video", "image"):
        await query.message.reply_text("Choose Text, Video, or Image!")
        return MEDIA_TYPE
    context.user_data["media_type"] = media_type
    await query.message.reply_text(f"Send your {media_type.upper()} win:")
    return MEDIA_UPLOAD

async def sharewin_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = get_username(update.effective_user)
    user_id = update.effective_user.id
    media_type = context.user_data.get("media_type")
    content = ""
    if media_type == "text":
        content = update.message.text or ""
    elif media_type == "image" and update.message.photo:
        content = f"(Photo file_id: {update.message.photo[-1].file_id})"
    elif media_type == "video" and update.message.video:
        content = f"(Video file_id: {update.message.video.file_id})"
    else:
        await update.message.reply_text(f"Please send a {media_type.upper()}.")
        return MEDIA_UPLOAD
    if not content:
        await update.message.reply_text("Win cannot be empty!")
        return MEDIA_UPLOAD
    timestamp = get_timestamp()
    if wins_sheet:
        wins_sheet.append_row([username, user_id, "Small Win", content, timestamp])
    await update.message.reply_text(random.choice(win_confirm), reply_markup=main_keyboard)
    await forward_to_group(context.bot, SUPPORT_GROUP_ID, f"Win from {username}: {content}")
    completed_modules = len({row[2] for row in assignments_sheet.get_all_values()[1:] if assignments_sheet and row[0] == username and row[3] == "Graded"}) if assignments_sheet else 0
    win_count = len([row for row in wins_sheet.get_all_values()[1:] if wins_sheet and row[0] == username]) if wins_sheet else 0
    if completed_modules >= 3 and win_count >= 3:
        await context.bot.send_message(user_id, "🎉 AVAP Achiever Badge earned!", reply_markup=main_keyboard)
    return ConversationHandler.END

async def grade_inline_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.message.reply_text("Only admins can grade submissions.")
        return ConversationHandler.END
    row_index = int(query.data.replace("grade_", ""))
    context.user_data["submission_row"] = row_index
    context.user_data["message_id"] = query.message.message_id
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
        score_buttons = [[InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)], [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]]
        await query.message.reply_text(f"Grading submission from {row[0]} (Module {row[2]}). Select score (1-10):", reply_markup=InlineKeyboardMarkup(score_buttons))
        return GRADE_SCORE
    except (IndexError, ValueError):
        await query.message.reply_text("Invalid submission.")
        return ConversationHandler.END

async def grade_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Only admins can grade submissions.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username to grade:")
    return USERNAME

async def grade_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text.strip()
    await update.message.reply_text("Which module? (1-12)")
    return MODULE_GRADE

async def grade_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        module = int(update.message.text.strip())
        if not 1 <= module <= 12:
            await update.message.reply_text("Enter a number between 1-12.")
            return MODULE_GRADE
        context.user_data["module"] = module
        username = context.user_data.get("username")
        if not assignments_sheet:
            await update.message.reply_text("Google Sheets not configured.")
            return ConversationHandler.END
        assignments = assignments_sheet.get_all_values()
        for i, row in enumerate(assignments[1:], start=2):
            if row[0] == username and row[2] == str(module) and row[3] == "Submitted":
                context.user_data["submission_row"] = i
                break
        else:
            await update.message.reply_text("No submitted assignment found for this user and module.")
            return ConversationHandler.END
        await update.message.reply_text("Select a score (1-10):", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]
        ]))
        return GRADE_SCORE
    except ValueError:
        await update.message.reply_text("Enter a valid number (1-12).")
        return MODULE_GRADE

async def grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    score = int(query.data.replace("score_", ""))
    context.user_data["score"] = score
    await query.message.reply_text("Add a comment?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Comment", callback_data="comment_yes"), InlineKeyboardButton("✅ No Comment", callback_data="comment_no")]
    ]))
    return GRADE_COMMENT_TYPE

async def grade_comment_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "comment_no":
        await complete_grading(update, context, "", "")
        return ConversationHandler.END
    await query.message.reply_text("Choose comment type:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Text", callback_data="comment_text"), InlineKeyboardButton("Audio", callback_data="comment_audio"), InlineKeyboardButton("Video", callback_data="comment_video")]
    ]))
    return GRADE_COMMENT

async def grade_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["comment_type"] = query.data.replace("comment_", "").capitalize()
    await query.message.reply_text(f"Send your {context.user_data['comment_type']} comment:")
    return GRADE_COMMENT_CONTENT

async def grade_comment_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def complete_grading(update: Update, context: ContextTypes.DEFAULT_TYPE, comment_type: str, comment_content: str):
    username = context.user_data.get("username")
    module = context.user_data.get("module")
    score = context.user_data.get("score")
    row_index = context.user_data.get("submission_row")
    message_id = context.user_data.get("message_id")
    if assignments_sheet:
        assignments_sheet.update_cell(row_index, 4, "Graded")
        assignments_sheet.update_cell(row_index, 6, f"Score: {score}/10")
        assignments_sheet.update_cell(row_index, 7, get_timestamp())
        assignments_sheet.update_cell(row_index, 8, str(score))
        assignments_sheet.update_cell(row_index, 9, comment_type)
        assignments_sheet.update_cell(row_index, 10, comment_content)
    if message_id:
        try:
            await context.bot.edit_message_reply_markup(chat_id=ASSIGNMENTS_GROUP_ID, message_id=message_id, reply_markup=None)
            await context.bot.send_message(ASSIGNMENTS_GROUP_ID, random.choice(grade_confirm), reply_to_message_id=message_id)
        except Exception as e:
            logger.error(f"Error editing message: {e}")
    await update.effective_message.reply_text(random.choice(grade_confirm))
    completed_modules = len({row[2] for row in assignments_sheet.get_all_values()[1:] if assignments_sheet and row[0] == username and row[3] == "Graded"}) if assignments_sheet else 0
    win_count = len([row for row in wins_sheet.get_all_values()[1:] if wins_sheet and row[0] == username]) if wins_sheet else 0
    if completed_modules >= 3 and win_count >= 3:
        await context.bot.send_message(int(assignments_sheet.get_all_values()[row_index-1][1]), "🎉 AVAP Achiever Badge earned!", reply_markup=main_keyboard)
    context.user_data.clear()

async def get_submission_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Only admins can view submissions.")
        return ConversationHandler.END
    await update.message.reply_text("Enter username:")
    return USERNAME_GET

async def get_submission_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["username"] = update.message.text.strip()
    await update.message.reply_text("Which module? (1-12)")
    return MODULE_GET

async def get_submission_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        module = int(update.message.text.strip())
        username = context.user_data.get("username")
        if not assignments_sheet:
            await update.message.reply_text("Google Sheets not configured.")
            return ConversationHandler.END
        assignments = assignments_sheet.get_all_values()
        for row in assignments[1:]:
            if len(row) < 8 or row[0] != username or int(row[2]) != module:
                continue
            content, status, feedback, timestamp, score = row[4], row[3], row[5] or "", row[6] or "", row[7] or "Not graded"
            comment_type, comment_content = row[8] if len(row) > 8 else "", row[9] if len(row) > 9 else ""
            message = f"Submission for {username}, Module {module}:\nStatus: {status}\nContent: {content}\nFeedback: {feedback}\nScore: {score}/10\nTimestamp: {timestamp}"
            await update.message.reply_text(message)
            if comment_type == "Text" and comment_content:
                await update.message.reply_text(f"Comment: {comment_content}")
            elif comment_type in ("Audio", "Video") and comment_content:
                getattr(update.message, f"reply_{comment_type.lower()}")(comment_content, caption="Comment")
            if "(Photo file_id:" in content:
                await update.message.reply_photo(content.split("file_id: ")[1].rstrip(")"))
            elif "(Video file_id:" in content:
                await update.message.reply_video(content.split("file_id: ")[1].rstrip(")"))
            context.user_data.clear()
            return ConversationHandler.END
        await update.message.reply_text("No submission found.")
    except Exception as e:
        logger.error(f"Error in get_submission_module: {e}")
        await update.message.reply_text("Failed to retrieve submission.")
    context.user_data.clear()
    return ConversationHandler.END

async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not db_is_verified(update.effective_user.id):
        await query.message.reply_text("Verify first!", reply_markup=verify_keyboard)
        return ConversationHandler.END
    await query.message.reply_text("What's your question?")
    return QUESTION

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text.strip()
    username = get_username(update.effective_user)
    telegram_id = update.effective_user.id
    timestamp = get_timestamp()
    if faq_sheet:
        row_index = len(faq_sheet.get_all_values()) + 1
        faq_sheet.append_row([question, "", "", "", username, timestamp, str(row_index)])
        await forward_to_group(
            context.bot, QUESTIONS_GROUP_ID,
            f"Question from {username} (ID: {row_index}):\n{question}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Answer", callback_data=f"answer_{row_index}")]])
        )
    await update.message.reply_text(random.choice(ask_confirm), reply_markup=main_keyboard)
    return ConversationHandler.END

async def answer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    question_id = query.data.replace("answer_", "")
    context.user_data["question_id"] = question_id
    await query.message.reply_text("Enter your answer:")
    return ANSWER_TEXT

async def answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip()
    question_id = context.user_data.get("question_id")
    if not faq_sheet:
        await update.message.reply_text("FAQ sheet not configured.")
        return ConversationHandler.END
    faq = faq_sheet.get_all_values()
    for i, row in enumerate(faq[1:], start=2):
        if row[6] == question_id and row[1] == "":
            faq_sheet.update_cell(i, 2, answer)
            faq_sheet.update_cell(i, 3, "Text")
            faq_sheet.update_cell(i, 5, get_username(update.effective_user))
            await context.bot.send_message(
                QUESTIONS_GROUP_ID,
                f"Answer to question (ID: {question_id}):\nQ: {row[0]}\nA: {answer}"
            )
            await update.message.reply_text(random.choice(ask_confirm), reply_markup=main_keyboard)
            context.user_data.clear()
            return ConversationHandler.END
    await update.message.reply_text("Question not found.", reply_markup=main_keyboard)
    return ConversationHandler.END

async def group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.startswith("/"):
        return
    if update.effective_chat.id in [ASSIGNMENTS_GROUP_ID, QUESTIONS_GROUP_ID, VERIFICATION_GROUP_ID, SUPPORT_GROUP_ID]:
        return
    if not db_is_verified(update.effective_user.id):
        await update.message.reply_text(f"Join {SUPPORT_GROUP_TITLE}:\n{LANDING_PAGE_LINK}", reply_markup=verify_keyboard)

async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    join_request = update.chat_join_request
    if join_request.chat.id != SUPPORT_GROUP_ID:
        return
    if db_is_verified(join_request.from_user.id):
        await join_request.approve()
        logger.info(f"Approved join request for {join_request.from_user.id}")
    else:
        await join_request.decline()
        await context.bot.send_message(join_request.from_user.id, "Verify to join the support group!", reply_markup=verify_keyboard)

# Conversation handlers
# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types (CallbackQueryHandler, MessageHandler, CommandHandler) are intentional for user input flexibility.
verify_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(verify_start, pattern="^verify_prompt$")],
    states={
        VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
        VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
        VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
submit_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(submit_start, pattern="^submit$")],
    states={
        MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module)],
        MEDIA_TYPE: [CallbackQueryHandler(submit_media_type, pattern="^media_(video|image)$")],
        MEDIA_UPLOAD: [MessageHandler(filters.PHOTO | filters.VIDEO, submit_media_upload)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
grade_inline_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(grade_inline_start, pattern="^grade_")],
    states={
        GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="^score_")],
        GRADE_COMMENT_TYPE: [CallbackQueryHandler(grade_comment_type, pattern="^comment_(yes|no)$")],
        GRADE_COMMENT: [CallbackQueryHandler(grade_comment, pattern="^comment_(text|audio|video)$")],
        GRADE_COMMENT_CONTENT: [MessageHandler(filters.TEXT | filters.AUDIO | filters.VIDEO, grade_comment_content)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
grade_conv = ConversationHandler(
    entry_points=[CommandHandler("grade", grade_start)],
    states={
        USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_username)],
        MODULE_GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_module)],
        GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="^score_")],
        GRADE_COMMENT_TYPE: [CallbackQueryHandler(grade_comment_type, pattern="^comment_(yes|no)$")],
        GRADE_COMMENT: [CallbackQueryHandler(grade_comment, pattern="^comment_(text|audio|video)$")],
        GRADE_COMMENT_CONTENT: [MessageHandler(filters.TEXT | filters.AUDIO | filters.VIDEO, grade_comment_content)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
get_submission_conv = ConversationHandler(
    entry_points=[CommandHandler("get_submission", get_submission_start)],
    states={
        USERNAME_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_username)],
        MODULE_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_module)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
ask_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_start, pattern="^ask$")],
    states={QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question)]},
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
answer_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(answer_start, pattern="^answer_")],
    states={ANSWER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_text)]},
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

# Note: PTBUserWarning about 'per_message=False' is benign and can be ignored, as mixed handler types are intentional.
add_student_conv = ConversationHandler(
    entry_points=[CommandHandler("add_student", add_student_start)],
    states={
        ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_name)],
        ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_phone)],
        ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_student_email)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: cancel(u, c, main_keyboard))]
)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_markup):
    context.user_data.clear()
    await update.message.reply_text("Canceled.", reply_markup=reply_markup)
    return ConversationHandler.END

async def main():
    try:
        logger.info("Initializing Application with TELEGRAM_TOKEN")
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        logger.info("Application initialized successfully")
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(InlineQueryHandler(inline_query))
        app.add_handler(CallbackQueryHandler(status, pattern="^status$"))
        app.add_handler(CallbackQueryHandler(view_comments, pattern="^view_comments$"))
        app.add_handler(verify_conv)
        app.add_handler(submit_conv)
        app.add_handler(grade_inline_conv)
        app.add_handler(grade_conv)
        app.add_handler(get_submission_conv)
        app.add_handler(ask_conv)
        app.add_handler(answer_conv)
        app.add_handler(add_student_conv)
        app.add_handler(ChatJoinRequestHandler(join_request))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_handler))
        app.add_error_handler(error_handler)
        logger.info("Handlers registered")

        sync_verifications_from_sheets()
        app.job_queue.run_daily(
            sunday_reminder,
            time=datetime.time(hour=18, minute=0, tzinfo=pytz.timezone("Africa/Lagos")),
            days=(6,)  # Sunday
        )

        webhook_url = "https://avap-support-bot.onrender.com/webhook"
        try:
            logger.info(f"Setting webhook to {webhook_url}")
            await app.bot.set_webhook(webhook_url)
            logger.info(f"Webhook set successfully to {webhook_url}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            sys.exit(1)

        @webhook_app.post("/webhook")
        async def webhook(request: Request):
            update = Update.de_json(await request.json(), app.bot)
            await app.process_update(update)
            return {"status": "ok"}

        @webhook_app.get("/health")
        async def health():
            return {"status": "ok"}

        logger.info(f"Starting Uvicorn server on port {PORT}")
        await uvicorn.run(webhook_app, host="0.0.0.0", port=PORT, log_level="info")

    except Exception as e:
        logger.error(f"Error starting bot: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    logger.info("Starting bot with asyncio.run(main())")
    asyncio.run(main())
