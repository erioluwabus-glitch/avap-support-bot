import os
import json
import logging
import datetime
import pytz
import random
import difflib
import hashlib
import sqlite3
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
import gspread
from google.oauth2 import service_account
from fastapi import FastAPI, Request, Response
import uvicorn
import requests

# States for conversations
MODULE, MEDIA_TYPE, MEDIA_UPLOAD = range(3)
USERNAME, MODULE_GRADE, FEEDBACK = range(3)
USERNAME_GET, MODULE_GET = range(2)
QUESTION = range(1)
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = range(3)

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
SYSTEME_API_KEY = os.getenv('SYSTEME_API_KEY')
LANDING_PAGE_LINK = os.getenv('LANDING_PAGE_LINK', 'https://your-landing.com/walkthrough')

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

# Database setup for verification
DB_PATH = os.getenv('DB_PATH', 'student_data.db')
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS verifications
                  (hash TEXT PRIMARY KEY, telegram_id INTEGER, claimed BOOLEAN DEFAULT FALSE)''')
conn.commit()

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

async def add_to_systeme(name, email, phone):
    api_key = SYSTEME_API_KEY
    if not api_key:
        logger.error("Systeme.io API key missing.")
        return
    url = "https://api.systeme.io/v1/contacts"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "email": email,
        "name": name,
        "phone": phone,
        "tags": ["verified_student"]
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info("Added to Systeme.io.")
        else:
            logger.error(f"Systeme.io error: {response.text}")
    except Exception as e:
        logger.error(f"Systeme.io request error: {e}")

# Response variants - more captivating, energetic, motivational
start_messages = ["Buckle up, AVAP champion! 🚀 Dive into your epic journey with these game-changing tools:", 
                  "Ignite your AVAP potential! 🌟 Unleash your power with these exciting features to dominate your goals:"]
submit_confirm = ["Boom! Your submission is in—watch your skills skyrocket! 🌟 You're unstoppable!", "Incredible work! Submission locked and loaded. Get ready for feedback that fuels your fire! 🔥"]
win_confirm = ["Victory unlocked! Your win is celebrated—keep slaying those goals! 🎉 Legend in the making!", "Epic win alert! You've just leveled up the community vibe. More triumphs ahead! 🏆"]
grade_confirm = ["Feedback fired off! Empowering them to reach new heights—you're the hero behind the scenes! 📈", "Graded like a boss! Your insights are sparking growth and greatness! 👍"]
logged_confirm = ["Moment of triumph captured! You're radiating inspiration—keep shining bright! 🚀", "Logged with flair! Your story is motivating the tribe—pure gold! 🌟"]
ask_confirm = ["Question launched! Our genius squad is brewing the perfect response—excitement incoming! 😊", "Bold question spotted! Diving deep for answers that'll blow your mind! 🔍"]
answer_sent = ["Wisdom dispatched and archived! Fueling future quests with your insight! 📌", "Answer shared—community leveled up! You're building a powerhouse of knowledge! 🌱"]

# Keyboard for commands - fixed buttons after /start (DM only)
main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("/submit"), KeyboardButton("/sharewin")],
    [KeyboardButton("/status"), KeyboardButton("/ask")]
], resize_keyboard=True, one_time_keyboard=False)

inline_start_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("📚 Submit Assignment", callback_data="submit")],
    [InlineKeyboardButton("🎉 Share Win", callback_data="sharewin")],
    [InlineKeyboardButton("📊 My Status", callback_data="status")],
    [InlineKeyboardButton("❓ Ask Question", callback_data="ask")]
])

# /start command
async def start_command(update: Update, context: CallbackContext) -> None:
    if update.message.chat.type == 'private':
        await update.message.reply_text(random.choice(start_messages), reply_markup=main_keyboard)
    else:
        await update.message.reply_text(random.choice(start_messages))

# Added simple help_command (was referenced but missing; customize as needed)
async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = """
AVAP Bot Commands:
- /start: Welcome and menu
- /submit: Submit assignment (Module 1-12, media)
- /sharewin: Share small win (text/video/image)
- /status: View progress
- /ask or #question: Ask a question (DM or support group)
- /grade (admin): Grade submission
- /get_submission (admin): Retrieve submission

Group: Post "Major Win" or "Testimonial" to log.
    """
    if update.message.chat.type == 'private':
        await update.message.reply_text(help_text, reply_markup=main_keyboard)
    else:
        await update.message.reply_text(help_text)

# /submit conversation - sequence flow, auto-forward, record, engaging prompts (DM only)
async def submit_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /submit in private DMs only. 🚀")
        return ConversationHandler.END
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
    await update.message.reply_text("No worries—action paused. Dive back in anytime!", reply_markup=main_keyboard if update.message.chat.type == 'private' else ReplyKeyboardRemove())
    return ConversationHandler.END

# /sharewin conversation - sequence, media options, engaging (DM only)
async def sharewin_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /sharewin in private DMs only. 🎉")
        return ConversationHandler.END
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

# /status - engaging progress report (updated to count all assignments)
async def status(update: Update, context: CallbackContext) -> None:
    username = get_username(update.message.from_user)
    try:
        assignments = assignments_sheet.get_all_values()
        attempted = len([row for row in assignments[1:] if row[0] == username])  # All submitted
        completed = len([row for row in assignments[1:] if row[0] == username and row[2] == "Graded"])
        wins = wins_sheet.get_all_values()
        total_wins = len([row for row in wins[1:] if row[0] == username])
        message = "Behold Your Conquest Map 📈:\n"
        message += f"Assignments Attempted: {attempted} | Completed: {completed}\n"
        message += f"Win Streak: {total_wins} 🏅 - You're forging a legacy!"
        await update.message.reply_text(message, reply_markup=main_keyboard if update.message.chat.type == 'private' else ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"Error in status: {e}")
        await update.message.reply_text("Progress scan jammed—reload soon!")

# /grade conversation - sequence, admin only, captivating (DM only)
async def grade_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /grade in private DMs only. 📈")
        return ConversationHandler.END
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

# /get_submission conversation - sequence, admin only (DM only)
async def get_submission_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type != 'private':
        await update.message.reply_text("Use /get_submission in private DMs only. 📂")
        return ConversationHandler.END
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

# Group handler for major wins/testimonials - expanded triggers (group only)
async def group_handler(update: Update, context: CallbackContext) -> None:
    if update.message.chat.type != 'group' or update.message.chat.title != SUPPORT_GROUP_TITLE:
        return

    text = update.message.text.lower() if update.message.text else ""
    content = update.message.text or ""
    type_ = None
    photo = update.message.photo[-1].file_id if update.message.photo else None
    video = update.message.video.file_id if update.message.video else None

    # Expanded win triggers
    major_keywords = ["major win", "big win", "huge achievement", "major success", "congrats to me", "i did it", "achievement unlocked", "proud moment", "celebration time"]
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

# /ask or #question - works in DM and support group, forwards properly (group: /ask only)
async def ask_start(update: Update, context: CallbackContext) -> int:
    if update.message.chat.type == 'group' and update.message.chat.title != SUPPORT_GROUP_TITLE:
        return ConversationHandler.END
    if update.message.chat.type == 'group':
        await update.message.reply_text("Fire away with your quest for knowledge! What's the question? (Group mode active)", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Fire away with your quest for knowledge! What's the question?", reply_markup=ReplyKeyboardRemove())
    return QUESTION

async def ask_question(update: Update, context: CallbackContext) -> int:
    question = update.message.text
    username = get_username(update.message.from_user)
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    try:
        faqs = faq_sheet.get_all_values()
        for row in faqs[1:]:
            similarity = difflib.SequenceMatcher(None, question.lower(), row[0].lower()).ratio()
            if similarity > 0.8:
                answer = row[1]
                await update.message.reply_text(f"Unveiling from the archives: {answer}")
                if row[2] == 'video':
                    await context.bot.send_video(chat_id, row[3])
                elif row[2] == 'voice':
                    await context.bot.send_voice(chat_id, row[3])
                return ConversationHandler.END

        # Forward to questions group if set
        forward_text = f"New quest from {username} (ID: {user_id}) in {chat_id}: {question}"
        await forward_to_group(context.bot, QUESTIONS_GROUP_ID, forward_text)
        await update.message.reply_text(random.choice(ask_confirm), reply_markup=main_keyboard if update.message.chat.type == 'private' else ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"Error in ask: {e}")
        await update.message.reply_text("Question quest hit a snag—retry!")
    return ConversationHandler.END

# Questions group handler for admin replies - supports media (forward back to user)
async def questions_group_handler(update: Update, context: CallbackContext) -> None:
    if update.message.chat.id != QUESTIONS_GROUP_ID or update.message.from_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        return

    reply_text = update.message.reply_to_message.text
    if "New quest from" not in reply_text:
        return

    user_id_str = reply_text.split("(ID: ")[1].split(")")[0]
    user_id = int(user_id_str)
    chat_id_str = reply_text.split("in ")[1].split(":")[0]
    chat_id = int(chat_id_str)
    question = reply_text.split(": ")[1]

    answer = update.message.text if update.message.text else ""
    video = update.message.video.file_id if update.message.video else None
    voice = update.message.voice.file_id if update.message.voice else None
    answer_type = 'video' if video else 'voice' if voice else 'text'
    file_id = video or voice

    @flask_app.route('/whatsapp_webhook', methods=['POST'])
def whatsapp_webhook():
    data = request.json
    details_hash = data.get('hash')
    if details_hash:
        cursor.execute("INSERT OR IGNORE INTO verifications (hash) VALUES (?)", (details_hash,))
        conn.commit()
        logger.info("Student data added from WhatsApp.")
    return 'OK', 200
    
    try:
        await context.bot.send_message(chat_id, f"Behold the answer to your quest: {answer}")
        if file_id:
            if answer_type == 'video':
                await context.bot.send_video(chat_id, file_id)
            elif answer_type == 'voice':
                await context.bot.send_voice(chat_id, file_id)

        timestamp = get_timestamp()
        faq_sheet.append_row([question, answer, answer_type, file_id or '', "", timestamp])
        await update.message.reply_text(random.choice(answer_sent))
    except Exception as e:
        logger.error(f"Error replying to question: {e}")

# /verify conversation (new from PDF)
async def verify_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Welcome! To verify your payment, what's your full name?")
    return VERIFY_NAME

async def verify_name(update: Update, context: CallbackContext) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Great! Your phone number?")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: CallbackContext) -> int:
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("Almost there! Your email?")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: CallbackContext) -> int:
    email = update.message.text
    name = context.user_data['name']
    phone = context.user_data['phone']
    telegram_id = update.message.from_user.id
    details_str = f"{name.lower()}|{phone.lower()}|{email.lower()}"
    details_hash = hashlib.sha256(details_str.encode()).hexdigest()

    cursor.execute("SELECT claimed FROM verifications WHERE hash = ?", (details_hash,))
    result = cursor.fetchone()
    if result and not result[0]:
        cursor.execute("UPDATE verifications SET telegram_id = ?, claimed = TRUE WHERE hash = ?", (telegram_id, details_hash))
        conn.commit()
        await update.message.reply_text("Verified! 🎉 Here's the group link: t.me/your_group")
        await update.message.reply_text(f"Walkthrough: {LANDING_PAGE_LINK}")
        await add_to_systeme(name, email, phone)
    else:
        await update.message.reply_text("Verification failed or already claimed. Contact support.")
    return ConversationHandler.END

# Handle chat join requests (new from PDF)
async def handle_join_request(update: Update, context: CallbackContext) -> None:
    request = update.chat_join_request
    user_id = request.from_user.id
    cursor.execute("SELECT claimed FROM verifications WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        await context.bot.approve_chat_join_request(request.chat.id, user_id)
        await context.bot.send_message(user_id, "Approved! Welcome. 🚀")
    else:
        await context.bot.decline_chat_join_request(request.chat.id, user_id)
        await context.bot.send_message(user_id, "Join denied—verify first.")

# Flask for WhatsApp webhook (new from PDF)
app = Flask(__name__)

@app.route('/whatsapp_webhook', methods=['POST'])
def whatsapp_webhook():
    data = request.form
    message = data.get('Body')
    try:
        parts = message.split(',')
        name = parts[0].split(':')[1].strip()
        phone = parts[1].split(':')[1].strip()
        email = parts[2].split(':')[1].strip()
        details_str = f"{name.lower()}|{phone.lower()}|{email.lower()}"
        details_hash = hashlib.sha256(details_str.encode()).hexdigest()
        cursor.execute("INSERT OR IGNORE INTO verifications (hash) VALUES (?)", (details_hash,))
        conn.commit()
        logger.info("Student data added from WhatsApp.")
    except Exception as e:
        logger.error(f"WhatsApp parse error: {e}")
    return 'OK', 200

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # /start
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

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

    # /ask conversation (group: /ask only)
    ask_conv = ConversationHandler(
        entry_points=[CommandHandler('ask', ask_start), MessageHandler(filters.Regex(r'(?i)^#question'), ask_start)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(ask_conv)

    # /verify conversation (new)
    verify_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^start=verify$"), verify_start)],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(verify_conv)

    # Group handlers (group only)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_handler))  # Wins
    application.add_handler(MessageHandler(filters.ALL, questions_group_handler))  # Questions replies
    application.add_handler(MessageHandler(filters.CHAT_JOIN_REQUEST, handle_join_request))  # Join requests

    # FastAPI setup (fixes 404)
    fastapi_app = FastAPI()

    @fastapi_app.get("/")
    async def root():
        return {"message": "AVAP Support Bot is active! 🚀 Interact via Telegram @avaps_bot."}

    @fastapi_app.get("/health")
    async def health():
        return "OK"  # For pinger to prevent sleeping

    WEBHOOK_PATH = "/webhook"
    @fastapi_app.post(WEBHOOK_PATH)
    async def telegram_webhook(request: Request):
        update_json = await request.json()
        if update_json:
            update = Update.de_json(update_json, application.bot)
            await application.process_update(update)
        return Response(status_code=200)

    # Run logic: Polling locally, webhook on Render
    is_render = os.getenv('RENDER') == 'true'
    port = int(os.environ.get('PORT', 10000))
    base_url = os.getenv('WEBHOOK_BASE_URL', f'http://localhost:{port}')
    webhook_url = f"{base_url}{WEBHOOK_PATH}"

    if is_render:
        logger.info("Running in webhook mode on Render.")
        import asyncio
        async def set_webhook():
            await application.initialize()
            await application.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook set to {webhook_url}")
        asyncio.run(set_webhook())
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info")
        app.run(host='0.0.0.0', port=port + 1)  # Flask on separate port
    else:
        logger.info("Running in polling mode locally.")
        application.run_polling()

if __name__ == '__main__':
    main()
