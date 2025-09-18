import os
import json
import logging
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

from fastapi import FastAPI
import uvicorn

from telegram import (
    Update, 
    ReplyKeyboardMarkup, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ConversationHandler, 
    ContextTypes, 
    filters
)

# ========= Logging ========= #
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========= States ========= #
(
    SHARE_MEDIA_TYPE, 
    SHARE_MEDIA_CONTENT, 
    ANSWER_QUESTION
) = range(3)

# ========= Keyboards ========= #
STUDENT_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Submit Assignment", "Share Win"],
        ["Check Status", "Ask Question"]
    ],
    resize_keyboard=True
)

VERIFY_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Verify Me", callback_data="verify_now")]
])

# ========= Env / Config ========= #
BOT_TOKEN = os.getenv("BOT_TOKEN")
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_BASE_URL = os.getenv("SYSTEME_BASE_URL", "https://api.systeme.io")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")  # JSON stored in Render env

WELCOME_MESSAGE = """
🎉 Welcome {name}!

✅ You are now verified and have full access.
👉 Here’s your welcome page: https://your-landing-page-link.com
"""

# ========= Google Sheets ========= #
if not GOOGLE_CREDENTIALS:
    raise RuntimeError("GOOGLE_CREDENTIALS not set in environment")

creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_CREDENTIALS),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

def is_verified_in_sheets(uid: int) -> bool:
    rows = sheet.get_all_records()
    return any(str(uid) == str(row.get("uid")) for row in rows)

def mark_verified_in_sheets(uid: int, username: str, email: str):
    sheet.append_row([str(uid), username, email, "verified", str(datetime.datetime.utcnow())])

# ========= Verification Workflow ========= #
async def complete_verification(user, context):
    """Full verification workflow for a student"""
    uid = user.id
    username = user.username or user.full_name
    email = f"{username}@example.com"  # TODO: replace with real email if collected

    # 1. Google Sheets
    if not is_verified_in_sheets(uid):
        mark_verified_in_sheets(uid, username, email)

    # 2. Systeme.io
    headers = {"accept": "application/json", "X-API-Key": SYSTEME_API_KEY}
    contact_payload = {"email": email, "first_name": username, "tags": ["verified"]}
    try:
        resp = requests.post(f"{SYSTEME_BASE_URL}/contacts", headers=headers, json=contact_payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Systeme.io error: {e}")

    # 3. Welcome Message
    await context.bot.send_message(
        chat_id=uid,
        text=WELCOME_MESSAGE.format(name=username),
        reply_markup=STUDENT_MENU_KEYBOARD
    )

# ========= Handlers ========= #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_verified_in_sheets(uid):
        await update.message.reply_text(
            "🎉 You are verified. Choose an action:",
            reply_markup=STUDENT_MENU_KEYBOARD
        )
    else:
        await update.message.reply_text(
            "👋 Welcome! Please verify first.",
            reply_markup=VERIFY_KEYBOARD
        )

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_verified_in_sheets(uid):
        await update.message.reply_text(
            "✅ You are already verified.",
            reply_markup=STUDENT_MENU_KEYBOARD
        )
    else:
        await update.message.reply_text(
            "Click the button below to verify:",
            reply_markup=VERIFY_KEYBOARD
        )

async def verify_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await complete_verification(query.from_user, context)
    await query.message.reply_text(f"✅ {query.from_user.full_name}, you are now verified!")

# ========= Share Win (placeholder for now) ========= #
async def share_win_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎉 Share Win coming soon!")

# ========= Build Application ========= #
def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set in environment")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CallbackQueryHandler(verify_now, pattern="^verify_now$"))

    # Example Share Win (expand later)
    app.add_handler(MessageHandler(filters.Regex("^Share Win$"), share_win_start))

    return app

# ========= FastAPI (health check) ========= #
fastapi_app = FastAPI()

@fastapi_app.get("/healthz")
async def healthz():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}

# ========= Main ========= #
if __name__ == "__main__":
    telegram_app = build_application()

    # Run bot in background thread
    import threading
    def run_bot():
        telegram_app.run_polling()

    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    # Start FastAPI server (for Render Web Service)
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
