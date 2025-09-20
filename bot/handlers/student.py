"""
Handlers for student-specific conversations like verification, submissions, and wins.
"""

import uuid
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..config import logger, EMAIL_RE, PHONE_RE, ASSIGNMENTS_GROUP_ID, SUPPORT_GROUP_ID, QUESTIONS_GROUP_ID
from ..database import (
    find_pending_by_hash,
    verify_user,
    get_verified_user_by_telegram_id,
    create_submission,
    create_win,
    create_question,
    make_hash,
)
from ..external import gsheets, systeme
from ..models import MAIN_MENU_MARKUP, VERIFY_PHONE, VERIFY_EMAIL, SUBMIT_MEDIA_TYPE, SUBMIT_MEDIA_UPLOAD, WIN_TYPE, ASK_QUESTION

# --- Verification Conversation Handlers ---

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user entering their name for verification."""
    name = (update.message.text or "").strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Please try again.")
        return VERIFY_NAME
    context.user_data['verify_name'] = name
    await update.message.reply_text("Thank you. Now, please enter your phone number (e.g., +1234567890).")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user entering their phone number for verification."""
    phone = (update.message.text or "").strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Invalid phone format. Please use the format `+<countrycode><number>`.")
        return VERIFY_PHONE
    context.user_data['verify_phone'] = phone
    await update.message.reply_text("Great. Lastly, please enter your email address.")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the final step of verification: the user's email."""
    email = (update.message.text or "").strip().lower()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email format. Please try again.")
        return VERIFY_EMAIL

    name = context.user_data.get('verify_name')
    phone = context.user_data.get('verify_phone')
    user = update.effective_user

    # Check if a pending verification exists with these details
    verification_hash = make_hash(name, email, phone)
    pending_user = await find_pending_by_hash(verification_hash)

    if not pending_user:
        await update.message.reply_text(
            "Your details could not be found in our pre-registered list. "
            "Please double-check them and try again, or contact an admin if the issue persists."
        )
        # Restart the flow by asking for the name again
        await update.message.reply_text("Let's start over. What is your full name?")
        return VERIFY_NAME

    # User found, complete verification
    await verify_user(pending_user['id'], user.id, name, email, phone)

    # Sync with external services
    gsheets.update_verification_status(email, "Verified", user.id)
    try:
        first, last = name.split(' ', 1) if ' ' in name else (name, '')
        systeme.create_contact(first, last, email, phone)
    except Exception as e:
        logger.error(f"Could not sync new verified user {email} to Systeme.io: {e}")

    await update.message.reply_text(
        "✅ Verification successful! Welcome to the AVAP community.",
        reply_markup=MAIN_MENU_MARKUP
    )
    return ConversationHandler.END


# --- Assignment Submission Handlers ---

async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user entering the module number for their submission."""
    user_id = update.effective_user.id
    if not await get_verified_user_by_telegram_id(user_id):
        await update.message.reply_text("You must be verified to submit assignments.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify Now", callback_data="verify_now")]]))
        return ConversationHandler.END

    try:
        module = int(update.message.text)
        if not 1 <= module <= 12:
            raise ValueError
        context.user_data['submit_module'] = module
        media_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Image", callback_data="media_image"),
             InlineKeyboardButton("Video", callback_data="media_video")]
        ])
        await update.message.reply_text("Is your submission an image or a video?", reply_markup=media_keyboard)
        return SUBMIT_MEDIA_TYPE
    except (ValueError, TypeError):
        await update.message.reply_text("That's not a valid module number. Please enter a number between 1 and 12.")
        return SUBMIT_MODULE


async def submit_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the final step of submission: the user uploading the media file."""
    media_type = context.user_data.get('submit_media_type')
    module = context.user_data.get('submit_module')
    user = update.effective_user
    username = user.username or user.full_name

    file_id = None
    if media_type == "image" and update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif media_type == "video" and update.message.video:
        file_id = update.message.video.file_id
    else:
        await update.message.reply_text(f"That wasn't a {media_type}. Please send your {media_type} submission.")
        return SUBMIT_MEDIA_UPLOAD

    submission_id = str(uuid.uuid4())
    await create_submission(submission_id, username, user.id, module, media_type, file_id)

    # Forward to assignments group
    if ASSIGNMENTS_GROUP_ID:
        caption = f"New submission from {username} for Module {module}."
        grade_button = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Grade Submission", callback_data=f"grade:{submission_id}")]])
        try:
            if media_type == "image":
                await context.bot.send_photo(chat_id=ASSIGNMENTS_GROUP_ID, photo=file_id, caption=caption, reply_markup=grade_button)
            else:
                await context.bot.send_video(chat_id=ASSIGNMENTS_GROUP_ID, video=file_id, caption=caption, reply_markup=grade_button)
        except Exception:
            logger.exception("Failed to forward submission to assignments group.")

    await update.message.reply_text("✅ Submission received! Thank you.", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END


# --- Share Win and Ask Question Handlers ---

async def win_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving the content for a 'small win'."""
    win_type = context.user_data.get('win_type')
    user = update.effective_user
    username = user.username or user.full_name

    content = None
    if win_type == "text" and update.message.text:
        content = update.message.text
    elif win_type == "image" and update.message.photo:
        content = update.message.photo[-1].file_id
    elif win_type == "video" and update.message.video:
        content = update.message.video.file_id
    else:
        await update.message.reply_text(f"That wasn't a {win_type}. Please send your {win_type} win.")
        return WIN_TYPE

    win_id = str(uuid.uuid4())
    await create_win(win_id, username, user.id, win_type, content)

    if SUPPORT_GROUP_ID:
        caption = f"🎉 New win from {username}!"
        try:
            if win_type == "text":
                await context.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=f"{caption}\n\n{content}")
            elif win_type == "image":
                await context.bot.send_photo(chat_id=SUPPORT_GROUP_ID, photo=content, caption=caption)
            else:
                await context.bot.send_video(chat_id=SUPPORT_GROUP_ID, video=content, caption=caption)
        except Exception:
            logger.exception("Failed to forward win to support group.")

    await update.message.reply_text("🚀 Awesome, win shared! Keep up the great work.", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END


async def ask_question_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving a student's question."""
    question_text = update.message.text
    if not question_text:
        await update.message.reply_text("Your question cannot be empty. Please try again.")
        return ASK_QUESTION

    user = update.effective_user
    username = user.username or user.full_name
    question_id = str(uuid.uuid4())

    await create_question(question_id, username, user.id, question_text)

    if QUESTIONS_GROUP_ID:
        message_text = f"❓ New question from {username} (ID: `{user.id}`):\n\n{question_text}"
        answer_button = InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Answer Question", callback_data=f"answer:{question_id}")]])
        try:
            await context.bot.send_message(
                chat_id=QUESTIONS_GROUP_ID,
                text=message_text,
                reply_markup=answer_button,
                parse_mode='MarkdownV2'
            )
        except Exception:
            logger.exception("Failed to forward question to questions group.")

    await update.message.reply_text("Your question has been sent to the support team. We'll get back to you shortly!", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END
