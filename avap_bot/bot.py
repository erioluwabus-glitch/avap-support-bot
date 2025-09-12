import os
import json
import logging
import datetime
import pytz
import random
import pkg_resources
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Bot

# Get installed packages
installed_packages = pkg_resources.working_set
installed_packages_list = sorted([f"{pkg.key}=={pkg.version}" for pkg in installed_packages])

# Print the list of installed packages
print(installed_packages_list)

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler

import gspread
from google.oauth2 import service_account

# States for conversations
MODULE, MEDIA_TYPE, MEDIA_UPLOAD = range(3)
USERNAME, MODULE_GRADE, FEEDBACK = range(3)
USERNAME_GET, MODULE_GET = range(2)
QUESTION = range(1)

# Setup logging first
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables after logging
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or '8263692248:AAFn778zSbSu3Ct4zDY8qNMabHfIZd46NhY'
ADMIN_ID = int(os.getenv('ADMIN_ID') or '5794442152')
ASSIGNMENTS_GROUP_ID = os.getenv('ASSIGNMENTS_GROUP_ID') or '-1003052010757'
if ASSIGNMENTS_GROUP_ID:
    try:
        ASSIGNMENTS_GROUP_ID = int(ASSIGNMENTS_GROUP_ID)
    except ValueError:
        logger.error("Invalid ASSIGNMENTS_GROUP_ID - must be integer. Forwarding disabled.")
        ASSIGNMENTS_GROUP_ID = None
else:
    logger.warning("ASSIGNMENTS_GROUP_ID not set - forwarding to assignments group disabled.")
    ASSIGNMENTS_GROUP_ID = None

QUESTIONS_GROUP_ID = os.getenv('QUESTIONS_GROUP_ID') or '-1002910055936'
if QUESTIONS_GROUP_ID:
    try:
        QUESTIONS_GROUP_ID = int(QUESTIONS_GROUP_ID)
    except ValueError:
        logger.error("Invalid QUESTIONS_GROUP_ID - must be integer. Questions forwarding disabled.")
        QUESTIONS_GROUP_ID = None
else:
    logger.warning("QUESTIONS_GROUP_ID not set - questions forwarding disabled.")
    QUESTIONS_GROUP_ID = None

SUPPORT_GROUP_TITLE = "AVAP Support Community"  # For major wins/testimonials

GOOGLE_CREDENTIALS_STR = os.getenv('GOOGLE_CREDENTIALS')

# Load Google credentials
try:
    google_credentials_dict = json.loads(GOOGLE_CREDENTIALS_STR)
    credentials = service_account.Credentials.from_service_account_info(
        google_credentials_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.readonly']
    )
    client = gspread.authorize(credentials)
    sheet = client.open("AVAPSupport")
    assignments_sheet = sheet.worksheet("Assignments")
    wins_sheet = sheet.worksheet("Wins")
    faq_sheet = sheet.worksheet("FAQ")
    logger.info("Google Sheets connected successfully.")
except Exception as e:
    logger.error(f"Error connecting to Google Sheets: {e}")
    raise

# Helper functions
def get_username(user):
    return user.username if user.username else f"User_{user.id}"

def get_timestamp():
    return datetime.datetime.now(pytz.timezone('Africa/Lagos')).isoformat()

async def forward_to_group(bot, group_id: int, text: str, photo=None, video=None, voice=None):
    if group_id is None:
        logger.warning("Group ID not set - skipping forward.")
        return
    try:
        if photo:
            await bot.send_photo(group_id, photo, caption=text)
        elif video:
            await bot.send_video(group_id, video, caption=text)
        elif voice:
            await bot.send_voice(group_id, voice, caption=text)
        else:
            await bot.send_message(group_id, text)
        logger.info(f"Forwarded to group {group_id} successfully.")
    except Exception as e:
        logger.error(f"Error forwarding to group {group_id}: {e}")

# Response variants - more captivating, energetic, motivational
start_messages = ["Buckle up, AVAP champion! 🚀 Dive into your epic journey with these game-changing tools:", 
                  "Ignite your AVAP potential! 🌟 Unleash your power with these exciting features to dominate your goals:"]
submit_confirm = ["Boom! Your submission is in—watch your skills skyrocket! 🌟 You're unstoppable!", "Incredible work! Submission locked and loaded. Get ready for feedback that fuels your fire! 🔥"]
win_confirm = ["Victory unlocked! Your win is celebrated—keep slaying those goals! 🎉 Legend in the making!", "Epic win alert! You've just leveled up the community vibe. More triumphs ahead! 🏆"]
grade_confirm = ["Feedback fired off! Empowering them to reach new heights—you're the hero behind the scenes! 📈", "Graded like a boss! Your insights are sparking growth and greatness! 👍"]
logged_confirm = ["Moment of triumph captured! You're radiating inspiration—keep shining bright! 🚀", "Logged with flair! Your story is motivating the tribe—pure gold! 🌟"]
ask_confirm = ["Question launched! Our genius squad is brewing the perfect response—excitement incoming! 😊", "Bold question spotted! Diving deep for answers that'll blow your mind! 🔍"]
answer_sent = ["Wisdom dispatched and archived! Fueling future quests with your insight! 📌", "Answer shared—community leveled up! You're building a powerhouse of knowledge! 🌱"]

# Keyboard for commands - fixed buttons after /start
main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("/submit"), KeyboardButton("/sharewin")],
    [KeyboardButton("/status"), KeyboardButton("/ask")]
], resize_keyboard=True, one_time_keyboard=False)

# Health Check Handler
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            # Respond with 200 OK and a simple JSON
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')  # Simple health check response

# Run the HTTP server
def run_health_check_server(port=80):
    server_address = ('', port)  # Listen on port 80 for the health check
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Health check server running on port {port}...")
    httpd.serve_forever()

# /start command
async def start_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(random.choice(start_messages), reply_markup=main_keyboard)

# /submit conversation - sequence flow, auto-forward, record, engaging prompts
async def submit_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Let's crush this submission! Which module are you conquering? (Enter 1-12)", reply_markup=ReplyKeyboardRemove())
    return MODULE

async def submit_module(update: Update, context: CallbackContext) -> int:
    try:
        module = int(update.message.text)
        if not 1 <= module <= 12:
            raise ValueError
        context.user_data['module'] = module
        keyboard = ReplyKeyboardMarkup([[KeyboardButton("Video"), KeyboardButton("Image")]], resize_keyboard=True)
        await update.message.reply_text("Power move! Video or Image to showcase your brilliance?", reply_markup=keyboard)
        return MEDIA_TYPE
    except ValueError:
        await update.message.reply_text("Whoops! Need a number between 1-12. What's the module?")
        return MODULE

async def submit_media_type(update: Update, context: CallbackContext) -> int:
    media_type = update.message.text.lower()
    if media_type not in ['video', 'image']:
        await update.message.reply_text("Pick your weapon: Video or Image?")
        return MEDIA_TYPE
    context.user_data['media_type'] = media_type
    await update.message.reply_text(f"Unleash it! Send your {media_type.upper()} masterpiece now:", reply_markup=ReplyKeyboardRemove())
    return MEDIA_UPLOAD

async def submit_media_upload(update: Update, context: CallbackContext) -> int:
    username = get_username(update.message.from_user)
    module = context.user_data['module']
    media_type = context.user_data['media_type']
    file_id = None
    content = ""
    photo = None
    video = None

    if media_type == 'image' and update.message.photo:
        file_id = update.message.photo[-1].file_id
        photo = file_id
        content = f"(Photo file_id: {file_id})"
    elif media_type == 'video' and update.message.video:
        file_id = update.message.video.file_id
        video = file_id
        content = f"(Video file_id: {file_id})"
    else:
        await update.message.reply_text(f"Need that {media_type.upper()}! Send it over.")
        return MEDIA_UPLOAD

    timestamp = get_timestamp()
    try:
        assignments_sheet.append_row([username, module, "Submitted", content, "", timestamp])  # Set to Submitted, admin can grade
        await update.message.reply_text(random.choice(submit_confirm), reply_markup=main_keyboard)
        forward_text = f"Fresh submission alert from {username} - Module {module}: {content}"
        await forward_to_group(context.bot, ASSIGNMENTS_GROUP_ID, forward_text, photo=photo, video=video)
    except Exception as e:
        logger.error(f"Error in submit: {e}")
        await update.message.reply_text("Submission glitch—try again, champ!")
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("No worries—action paused. Dive back in anytime!", reply_markup=main_keyboard)
    return ConversationHandler.END

# /sharewin conversation - sequence, media options, engaging
async def sharewin_start(update: Update, context: CallbackContext) -> int:
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("Text"), KeyboardButton("Video"), KeyboardButton("Image")]], resize_keyboard=True)
    await update.message.reply_text("Time to brag! How are you sharing your epic win—Text, Video, or Image?", reply_markup=keyboard)
    return MEDIA_TYPE

async def sharewin_media_type(update: Update, context: CallbackContext) -> int:
    media_type = update.message.text.lower()
    if media_type not in ['text', 'video', 'image']:
        await update.message.reply_text("Select your victory format: Text, Video, or Image?")
        return MEDIA_TYPE
    context.user_data['media_type'] = media_type
    if media_type == 'text':
        await update.message.reply_text("Spill the thrilling details of your win:", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"Show us the glory! Drop your {media_type.upper()} here:", reply_markup=ReplyKeyboardRemove())
    return MEDIA_UPLOAD

async def sharewin_media_upload(update: Update, context: CallbackContext) -> int:
    username = get_username(update.message.from_user)
    media_type = context.user_data['media_type']
    content = ""
    if media_type == 'text':
        content = update.message.text
    elif media_type == 'image' and update.message.photo:
        file_id = update.message.photo[-1].file_id
        content = f"(Photo file_id: {file_id})"
    elif media_type == 'video' and update.message.video:
        file_id = update.message.video.file_id
        content = f"(Video file_id: {file_id})"
    else:
        await update.message.reply_text(f"Awaiting your {media_type.upper()} win proof!")
        return MEDIA_UPLOAD

    if not content:
        await update.message.reply_text("Can't celebrate an empty win—add some flair!")
        return MEDIA_UPLOAD

    timestamp = get_timestamp()
    try:
        wins_sheet.append_row([username, "Small Win", content, timestamp])
        await update.message.reply_text(random.choice(win_confirm), reply_markup=main_keyboard)
    except Exception as e:
        logger.error(f"Error in sharewin: {e}")
        await update.message.reply_text("Win share hiccup—retry the glory!")
    return ConversationHandler.END

# /status - engaging progress report
async def status(update: Update, context: CallbackContext) -> None:
    username = get_username(update.message.from_user)
    try:
        assignments = assignments_sheet.get_all_values()
        completed = [row[1] for row in assignments[1:] if row[0] == username and row[2] == "Graded"]
        wins = wins_sheet.get_all_values()
        total_wins = len([row for row in wins[1:] if row[0] == username])
        message = "Behold Your Conquest Map 📈:\n"
        message += f"Modules Vanquished: {', '.join(completed) or 'Gear up for battle!'}\n"
        message += f"Win Streak: {total_wins} 🏅 - You're forging a legacy!"
        await update.message.reply_text(message, reply_markup=main_keyboard)
    except Exception as e:
        logger.error(f"Error in status: {e}")
        await update.message.reply_text("Progress scan jammed—reload soon!")

# /grade conversation - sequence, admin only, captivating
async def grade_start(update: Update, context: CallbackContext) -> int:
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("This power is for AVAP masters only!")
        return ConversationHandler.END
    await update.message.reply_text("Whose creation are you elevating? (Enter username)", reply_markup=ReplyKeyboardRemove())
    return USERNAME

async def grade_username(update: Update, context: CallbackContext) -> int:
    context.user_data['username'] = update.message.text
    await update.message.reply_text("Which module realm? (1-12)")
    return MODULE_GRADE

async def grade_module(update: Update, context: CallbackContext) -> int:
    try:
        module = int(update.message.text)
        if not 1 <= module <= 12:
            raise ValueError
        context.user_data['module'] = module
        await update.message.reply_text("Unleash your wisdom— what's the electrifying feedback?")
        return FEEDBACK
    except ValueError:
        await update.message.reply_text("Realm must be 1-12—choose wisely!")
        return MODULE_GRADE

async def grade_feedback(update: Update, context: CallbackContext) -> int:
    feedback = update.message.text
    username = context.user_data['username']
    module = context.user_data['module']
    try:
        assignments = assignments_sheet.get_all_values()
        found = False
        for i, row in enumerate(assignments[1:], start=2):
            if row[0] == username and int(row[1]) == module and row[2] == "Submitted":
                assignments_sheet.update_cell(i, 3, "Graded")
                assignments_sheet.update_cell(i, 5, feedback)
                found = True
                break
        if found:
            await update.message.reply_text(random.choice(grade_confirm), reply_markup=main_keyboard)
        else:
            await update.message.reply_text("No realm to elevate—verify the quest!")
    except Exception as e:
        logger.error(f"Error grading: {e}")
        await update.message.reply_text("Elevation error—retry the magic.")
    return ConversationHandler.END

# /get_submission conversation - sequence, admin only
async def get_submission_start(update: Update, context: CallbackContext) -> int:
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("Secret archives for admins only!")
        return ConversationHandler.END
    await update.message.reply_text("Whose masterpiece are you summoning? (Username)", reply_markup=ReplyKeyboardRemove())
    return USERNAME_GET

async def get_submission_username(update: Update, context: CallbackContext) -> int:
    context.user_data['username'] = update.message.text
    await update.message.reply_text("From which module quest?")
    return MODULE_GET

async def get_submission_module(update: Update, context: CallbackContext) -> int:
    try:
        module = int(update.message.text)
        username = context.user_data['username']
        assignments = assignments_sheet.get_all_values()
        for row in assignments[1:]:
            if row[0] == username and int(row[1]) == module:
                content = row[3]
                await update.message.reply_text(f"Summoning {username}'s Module {module} triumph: {content}", reply_markup=main_keyboard)
                if '(Video file_id:' in content:
                    file_id = content.split('file_id: ')[1].rstrip(')')
                    await context.bot.send_video(update.message.chat.id, file_id)
                elif '(Photo file_id:' in content:
                    file_id = content.split('file_id: ')[1].rstrip(')')
                    await context.bot.send_photo(update.message.chat.id, file_id)
                return ConversationHandler.END
        await update.message.reply_text("No triumph found—search deeper!", reply_markup=main_keyboard)
    except Exception as e:
        logger.error(f"Error getting submission: {e}")
        await update.message.reply_text("Summoning failed—try again.")
    return ConversationHandler.END

# Group handler for major wins/testimonials - engaging replies
async def group_handler(update: Update, context: CallbackContext) -> None:
    if update.message.chat.title != SUPPORT_GROUP_TITLE:
        return

    text = update.message.text.lower() if update.message.text else ""
    content = update.message.text or ""
    type_ = None
    photo = update.message.photo[-1].file_id if update.message.photo else None
    video = update.message.video.file_id if update.message.video else None

    major_keywords = ["major win", "big win", "huge achievement", "major success"]
    testimonial_keywords = ["testimonial", "review", "feedback", "course review"]

    if any(kw in text for kw in major_keywords):
        type_ = "Major Win"
    elif any(kw in text for kw in testimonial_keywords):
        type_ = "Testimonial"

    if not type_:
        return

    if photo:
        content += f" (Photo file_id: {photo})"
    elif video:
        content += f" (Video file_id: {video})"

    username = get_username(update.message.from_user)
    timestamp = get_timestamp()

    try:
        wins_sheet.append_row([username, type_, content, timestamp])
        await update.message.reply_text(random.choice(logged_confirm))
    except Exception as e:
        logger.error(f"Error logging group: {e}")

# /ask or #question - works in DM and support group, forwards properly
async def ask_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type == 'group' and update.message.chat.title != SUPPORT_GROUP_TITLE:
        return ConversationHandler.END
    await update.message.reply_text("Fire away with your quest for knowledge! What's the question?", reply_markup=ReplyKeyboardRemove())
    return QUESTION

async def ask_question(update: Update, context: CallbackContext) -> int:
    question = update.message.text
    username = get_username(update.message.from_user)
    user_id = update.message.from_user.id
    try:
        faqs = faq_sheet.get_all_values()
        for row in faqs[1:]:
            similarity = difflib.SequenceMatcher(None, question.lower(), row[0].lower()).ratio()
            if similarity > 0.8:
                answer = row[1]
                await update.message.reply_text(f"Unveiling from the archives: {answer}")
                if row[2] == 'video':
                    await context.bot.send_video(update.message.chat.id, row[3])
                elif row[2] == 'voice':
                    await context.bot.send_voice(update.message.chat.id, row[3])
                return ConversationHandler.END

        # Forward to questions group if set
        forward_text = f"New quest from {username} (ID: {user_id}): {question}"
        await forward_to_group(context.bot, QUESTIONS_GROUP_ID, forward_text)
        await update.message.reply_text(random.choice(ask_confirm), reply_markup=main_keyboard)
    except Exception as e:
        logger.error(f"Error in ask: {e}")
        await update.message.reply_text("Question quest hit a snag—retry!")
    return ConversationHandler.END

# Questions group handler for admin replies - supports media
async def questions_group_handler(update: Update, context: CallbackContext) -> None:
    if update.message.chat.id != QUESTIONS_GROUP_ID or update.message.from_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        return

    reply_text = update.message.reply_to_message.text
    if "New quest from" not in reply_text:
        return

    user_id_str = reply_text.split("(ID: ")[1].split("):")[0]
    user_id = int(user_id_str)
    question = reply_text.split(": ")[1]

    answer = update.message.text if update.message.text else ""
    video = update.message.video.file_id if update.message.video else None
    voice = update.message.voice.file_id if update.message.voice else None
    answer_type = 'video' if video else 'voice' if voice else 'text'
    file_id = video or voice

    try:
        await context.bot.send_message(user_id, f"Behold the answer to your quest: {answer}")
        if file_id:
            if answer_type == 'video':
                await context.bot.send_video(user_id, file_id)
            elif answer_type == 'voice':
                await context.bot.send_voice(user_id, file_id)

        timestamp = get_timestamp()
        faq_sheet.append_row([question, answer, answer_type, file_id or '', "", timestamp])
        await update.message.reply_text(random.choice(answer_sent))
    except Exception as e:
        logger.error(f"Error replying to question: {e}")

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # /start
    application.add_handler(CommandHandler("start", start_command))

    # /submit conversation
    submit_conv = ConversationHandler(
        entry_points=[CommandHandler('submit', submit_start)],
        states={
            MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module)],
            MEDIA_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_media_type)],
            MEDIA_UPLOAD: [MessageHandler(filters.PHOTO | filters.VIDEO, submit_media_upload)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(submit_conv)

    # /sharewin conversation
    sharewin_conv = ConversationHandler(
        entry_points=[CommandHandler('sharewin', sharewin_start)],
        states={
            MEDIA_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sharewin_media_type)],
            MEDIA_UPLOAD: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, sharewin_media_upload)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(sharewin_conv)

    # /status
    application.add_handler(CommandHandler("status", status))

    # /grade conversation
    grade_conv = ConversationHandler(
        entry_points=[CommandHandler('grade', grade_start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_username)],
            MODULE_GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_module)],
            FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, grade_feedback)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(grade_conv)

    # /get_submission conversation
    get_submission_conv = ConversationHandler(
        entry_points=[CommandHandler('get_submission', get_submission_start)],
        states={
            USERNAME_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_username)],
            MODULE_GET: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_submission_module)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(get_submission_conv)

    # /ask conversation
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler('ask', ask_start), MessageHandler(filters.Regex(r'(?i)^#question'), ask_start)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(ask_conv)

    # Group handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_handler))  # Support group wins
    application.add_handler(MessageHandler(filters.ALL, questions_group_handler))  # Questions group replies

    # Webhook or polling
    port = int(os.environ.get('PORT', 0))
    if port:
        # Render: Use webhook
        webhook_url = os.getenv('RENDER_EXTERNAL_URL') + '/' + TELEGRAM_TOKEN  # Set RENDER_EXTERNAL_URL in Render env if needed
        application.run_webhook(listen='0.0.0.0', port=port, url_path=TELEGRAM_TOKEN, webhook_url=webhook_url)
        logger.info("Running in webhook mode on Render.")
    else:
        # Local: Polling
        application.run_polling()
        logger.info("Running in polling mode locally.")

if __name__ == '__main__':
    main()
