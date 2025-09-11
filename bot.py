from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import logging
import json
import os

# Bot token and admin ID
TOKEN = "8263692248:AAFn778zSbSu3Ct4zDY8qNMabHfIZd46NhY"  # Replace with token from @BotFather
ADMIN_ID = "5794442152"  # Replace with your Telegram ID

# Logging
logging.basicConfig(level=logging.INFO)

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
# Get the path of the credentials file from the environment variable
google_credentials_path = os.getenv("GOOGLE_CREDENTIALS")

# Check if the environment variable is set
if google_credentials_path is None:
    raise ValueError("GOOGLE_CREDENTIALS environment variable is not set or is empty.")

try:
    # Open the credentials file and load the JSON data
    with open(google_credentials_path, "r") as f:
        creds_dict = json.load(f)
except json.JSONDecodeError as e:  # Proper syntax for Python 3.13
    raise ValueError("Invalid JSON in GOOGLE_CREDENTIALS file.") from e
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
assignment_sheet = client.open("AVAPSupport").worksheet("Assignments")
wins_sheet = client.open("AVAPSupport").worksheet("Wins")
logging.info("Credentials loaded successfully")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to AVAP Support! DM me for assignments/small wins: /submit [Module] or /sharewin. Post Major Wins/Testimonials in the group with 'Major Win' or 'Testimonial'. Use /status for progress."
    )

async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        await update.message.reply_text("Please DM me privately for assignments.")
        return
    args = context.args
    if not args or not args[0].isdigit() or int(args[0]) not in range(1, 13):
        await update.message.reply_text("Use /submit [Module Number] (1-12), e.g., /submit 4")
        return
    module = args[0]
    user = update.message.from_user.username or str(update.message.from_user.id)
    context.user_data['module'] = module
    context.user_data['mode'] = 'assignment'
    await update.message.reply_text(f"Received @{user}'s Module {module} assignment. Post it now (text/video/etc.).")

async def sharewin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        await update.message.reply_text("DM me for small wins. Post Major Wins in the group!")
        return
    user = update.message.from_user.username or str(update.message.from_user.id)
    context.user_data['mode'] = 'small_win'
    await update.message.reply_text(f"Thanks @{user}! Post your small win now (text/video/etc.).")

async def handle_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or str(update.message.from_user.id)
    content_type = "Text" if update.message.text else "Video" if update.message.video else "Photo" if update.message.photo else "Link"
    content = update.message.text or "Media/Link"
    
    if update.message.chat.type == 'private':
        mode = context.user_data.get('mode', '')
        if mode == 'assignment':
            module = context.user_data.get('module', 'Unknown')
            status = "Submitted"
            grade = "Auto-Graded: 8/10 - Complete" if content_type == "Video" else "Auto-Graded: 6/10 - Submit a video for full marks"
            assignment_sheet.append_row([user, module, status, content_type, content, grade, update.message.date.isoformat()])
            logging.info("Sheet updated for command: %s", update.message.text)
            await update.message.reply_text(f"Stored @{user}'s Module {module} assignment: {content_type}. {grade}. Share a Major Win in the group!")
            del context.user_data['mode']
            del context.user_data['module']
        elif mode == 'small_win':
            wins_sheet.append_row([user, "Small " + content_type, content, update.message.date.isoformat()])
            logging.info("Sheet updated for command: %s", update.message.text)
            await update.message.reply_text(f"Stored @{user}'s small win: {content_type}. Post Major Wins in the group!")
            del context.user_data['mode']
    elif update.message.chat.type in ['group', 'supergroup']:
        if update.message.text and ("major win" in update.message.text.lower() or "testimonial" in update.message.text.lower()):
            wins_sheet.append_row([user, "Major " + content_type, content, update.message.date.isoformat()])
            logging.info("Sheet updated for command: %s", update.message.text)
            await update.message.reply_text(f"Congrats @{user} on the Major Win/Testimonial! Stored for admin review. Everyone, cheer with 👍!")

async def grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != 5794442152:
        await update.message.reply_text("Admin-only command.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /grade [Username] [Module] [Score/Feedback]")
        return
    user, module, feedback = args[0], args[1], " ".join(args[2:])
    assignment_sheet.append_row([user, module, "Graded", "", feedback, update.message.date.isoformat()])
    logging.info("Sheet updated for command: /grade")
    await update.message.reply_text(f"Graded @{user}'s Module {module}: {feedback}. Recorded for certification.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username or str(update.message.from_user.id)
    assignments = assignment_sheet.get_all_records()
    user_assignments = [row for row in assignments if row.get("Username") == user]
    wins = wins_sheet.get_all_records()
    user_wins = [row for row in wins if row.get("Username") == user]
    response = f"@{user}'s Status:\nAssignments: {len(user_assignments)} submitted\nSmall Wins: {sum(1 for w in user_wins if 'Small' in w['Type'])} shared\nMajor Wins/Testimonials: {sum(1 for w in user_wins if 'Major' in w['Type'])} shared\nCheck certification progress in admin records."
    await update.message.reply_text(response)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Error: {context.error}")
    if update:
        await update.message.reply_text("Error occurred. Try again or contact admin.")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("submit", submit))
    application.add_handler(CommandHandler("sharewin", sharewin))
    application.add_handler(CommandHandler("grade", grade))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT | filters.VIDEO | filters.PHOTO | filters.Document.ALL, handle_submission))
    application.add_error_handler(error_handler)
    application.run_polling()

if __name__ == "__main__":
    main()