import os
import io
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import gspread
from google.oauth2.service_account import Credentials
from telegram.error import BadRequest
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8263692248:AAFn778zSbSu3Ct4zDY8qNMabHfIZd46NhY')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')
ADMIN_ID = int(os.getenv('ADMIN_ID', '5794442152'))  # Replace with actual admin ID, e.g., 123456789

# Google Sheets setup
def get_sheet():
    try:
        if GOOGLE_CREDENTIALS:
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
        else:
            # Fallback for local: Read from credentials.json
            with open('credentials.json', 'r') as f:
                creds_dict = json.load(f)
        
        creds = Credentials.from_service_account_info(creds_dict)
        client = gspread.authorize(creds)
        sheet = client.open("AVAPSupport")
        return sheet.worksheet("Assignments"), sheet.worksheet("Wins")
    except Exception as e:
        logger.error(f"Error accessing Google Sheet: {e}")
        return None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message with instructions."""
    welcome_text = """
Welcome to AVAP Support Bot! 📚

Private DM Commands:
/submit [Module 1-12] [your content] - Submit assignment (text or video).
/sharewin [your small win] - Share a small win (text or video).
/status - Check your progress.

In the group: Post "Major Win: [details]" or "Testimonial: [details]" to log it.

Admins: /grade [Username] [Module] [Feedback]
    """
    if update.message.chat.type == 'private':
        await update.message.reply_text(welcome_text)
    else:
        # Pin welcome in group if bot is admin
        try:
            await update.message.reply_text(welcome_text, disable_notification=True)
            # Note: Actual pinning requires bot to unpin first, etc. Handle manually or extend.
        except BadRequest:
            pass

async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /submit in private chats only."""
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /submit in private DMs only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /submit [Module 1-12] [content]")
        return

    try:
        module = context.args[0]
        if not module.isdigit() or not 1 <= int(module) <= 12:
            await update.message.reply_text("Module must be a number between 1-12.")
            return

        content = ' '.join(context.args[1:]) if len(context.args) > 1 else None
        if not content and not update.message.video and not update.message.text:
            await update.message.reply_text("Please provide content (text after command or attach video).")
            return

        # Handle video or text
        media_url = None
        if update.message.video:
            file = await context.bot.get_file(update.message.video.file_id)
            media_url = file.file_path  # Or download to temp; for Render, store URL
        elif content:
            media_url = content  # Text as string

        timestamp = datetime.now().isoformat()
        row = [update.effective_user.username or update.effective_user.first_name, module, 'Submitted', media_url or content, '', timestamp]
        assignments_ws.append_row(row)
        await update.message.reply_text(f"Assignment for Module {module} submitted! ✅")
    except Exception as e:
        logger.error(f"Submit error: {e}")
        await update.message.reply_text("Error submitting. Check logs.")

async def sharewin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sharewin in private chats only."""
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /sharewin in private DMs only.")
        return

    content = ' '.join(context.args) if context.args else None
    if not content and not update.message.video and not update.message.text:
        await update.message.reply_text("Usage: /sharewin [your small win] (text or attach video).")
        return

    media_url = None
    if update.message.video:
        file = await context.bot.get_file(update.message.video.file_id)
        media_url = file.file_path
    elif content:
        media_url = content

    timestamp = datetime.now().isoformat()
    row = [update.effective_user.username or update.effective_user.first_name, 'Small Win', media_url or content, timestamp]
    wins_ws.append_row(row)
    await update.message.reply_text("Small win shared! 🎉")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle group messages for Major Win or Testimonial."""
    if update.message.chat.type != 'supergroup' and update.message.chat.type != 'group':
        return

    text = update.message.text or update.message.caption or ''
    username = update.effective_user.username or update.effective_user.first_name
    timestamp = datetime.now().isoformat()

    if 'Major Win' in text.upper():
        row = [username, 'Major Win', text, timestamp]
        wins_ws.append_row(row)
        await update.message.reply_text("Major win logged! 🚀")
    elif 'Testimonial' in text.upper():
        row = [username, 'Testimonial', text, timestamp]
        wins_ws.append_row(row)
        await update.message.reply_text("Testimonial logged! 💬")

async def grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only /grade command."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Admin only.")
        return

    if len(context.args) < 3:
        await update.message.reply_text("Usage: /grade [Username] [Module] [Feedback]")
        return

    username = context.args[0]
    module = context.args[1]
    feedback = ' '.join(context.args[2:])

    # Find row in Assignments and update
    records = assignments_ws.get_all_records()
    for row_idx, record in enumerate(records, start=2):  # Skip header
        if record.get('Username') == username and record.get('Module') == module:
            assignments_ws.update_cell(row_idx, 5, feedback)  # Grade/Feedback column
            assignments_ws.update_cell(row_idx, 3, 'Graded')  # Status
            await update.message.reply_text(f"Graded {username} Module {module}: {feedback}")
            return
    await update.message.reply_text(f"No submission found for {username} Module {module}.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user progress."""
    username = update.effective_user.username or update.effective_user.first_name
    records = assignments_ws.get_all_records()
    wins_records = wins_ws.get_all_records()

    completed_modules = [r['Module'] for r in records if r['Username'] == username and r['Status'] == 'Graded']
    wins_count = len([w for w in wins_records if w['Username'] == username])

    text = f"Your Progress, {username}:\nCompleted Modules: {', '.join(completed_modules) or 'None'}\nWins: {wins_count}"
    await update.message.reply_text(text)

def main():
    """Start the bot."""
    if TELEGRAM_TOKEN == '8263692248:AAFn778zSbSu3Ct4zDY8qNMabHfIZd46NhY':
        logger.error("Set TELEGRAM_TOKEN env var.")
        return

    global assignments_ws, wins_ws
    assignments_ws, wins_ws = get_sheet()
    if not assignments_ws or not wins_ws:
        logger.error("Failed to access sheets.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("submit", submit))
    application.add_handler(CommandHandler("sharewin", sharewin))
    application.add_handler(CommandHandler("grade", grade))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_group_message))
    application.add_handler(MessageHandler(filters.VIDEO, handle_group_message))  # For video in group; extend for DM if needed

    # For media in commands, it's handled inline; add if separate handler needed

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()