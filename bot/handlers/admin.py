"""
Handlers for administrator-specific commands and conversations.
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ..config import logger, EMAIL_RE, PHONE_RE, VERIFICATION_GROUP_ID
from ..database import (
    add_pending_student,
    get_pending_by_email,
    manual_verify_user,
    remove_verified_user,
    get_question,
    update_question_answer,
    update_submission_comment,
    get_submission,
    make_hash,
)
from ..external import gsheets, systeme
from ..models import ADD_STUDENT_PHONE, ADD_STUDENT_EMAIL
from .general import is_admin

# --- Add Student Conversation ---

async def add_student_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new student for pre-registration."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return ConversationHandler.END

    if VERIFICATION_GROUP_ID and update.effective_chat.id != VERIFICATION_GROUP_ID:
        await update.message.reply_text(f"Please use this command in the designated verification group.")
        return ConversationHandler.END

    await update.message.reply_text("Enter the student's full name:")
    return ADD_STUDENT_PHONE

async def add_student_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if len(name) < 3:
        await update.message.reply_text("Name must be at least 3 characters. Please try again.")
        return ADD_STUDENT_NAME
    context.user_data['new_student_name'] = name
    await update.message.reply_text("Enter the student's phone number (e.g., +1234567890):")
    return ADD_STUDENT_PHONE

async def add_student_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the student's phone number."""
    phone = (update.message.text or "").strip()
    if not PHONE_RE.match(phone):
        await update.message.reply_text("Invalid phone format. Please use `+<countrycode><number>`.")
        return ADD_STUDENT_PHONE
    context.user_data['new_student_phone'] = phone
    await update.message.reply_text("Enter the student's email address:")
    return ADD_STUDENT_EMAIL

async def add_student_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the student's email and finalizes the pre-registration."""
    email = (update.message.text or "").strip().lower()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email format. Please try again.")
        return ADD_STUDENT_EMAIL

    name = context.user_data.get('new_student_name')
    phone = context.user_data.get('new_student_phone')

    if await add_pending_student(name, email, phone):
        # Also add to Google Sheets if configured
        h = make_hash(name, email, phone)
        from datetime import datetime
        created_at = datetime.utcnow().isoformat()
        gsheets.append_pending_student(name, email, phone, h, created_at)

        await update.message.reply_text(
            f"✅ Student {name} has been pre-registered.\n"
            f"They can now verify themselves by starting a conversation with me.\n"
            f"You can also manually verify them with the command:\n"
            f"`/verify_student {email}`"
        )
    else:
        await update.message.reply_text("A student with this email address already exists in the pending list.")

    return ConversationHandler.END

# --- Admin Command Handlers ---

async def verify_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually verifies a student using their email address."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /verify_student <email>")
        return

    email = context.args[0].lower()
    pending_user = await get_pending_by_email(email)

    if not pending_user:
        await update.message.reply_text("No pending student found with that email. Have they been added with /add_student?")
        return

    await manual_verify_user(email)

    # Sync with external services
    gsheets.update_verification_status(email, "Verified (Manual)", 0)
    try:
        name = pending_user['name']
        phone = pending_user['phone']
        first, last = name.split(' ', 1) if ' ' in name else (name, '')
        systeme.create_contact(first, last, email, phone)
    except Exception as e:
        logger.error(f"Could not sync manually verified user {email} to Systeme.io: {e}")

    await update.message.reply_text(f"✅ Student with email {email} has been manually verified.")


async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a student's verified status."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove_student <telegram_id>")
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid Telegram ID. It must be a number.")
        return

    result = await remove_verified_user(telegram_id)
    if result:
        email, name = result
        gsheets.update_verification_status(email, "Removed", telegram_id)
        await update.message.reply_text(f"🗑️ Student {name} (ID: {telegram_id}) has been removed. They will need to re-verify to regain access.")
    else:
        await update.message.reply_text("No verified student found with that Telegram ID.")

# --- Grading and Answering Handlers (Receiving replies) ---

async def grade_comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the admin's comment for a submission."""
    sub_id = context.user_data.get('grading_sub_id')
    if not sub_id:
        return ConversationHandler.END

    comment = update.message.text
    if not comment:
        await update.message.reply_text("Comment cannot be empty. Please send a text comment.")
        return

    await update_submission_comment(sub_id, comment)
    submission = await get_submission(sub_id)
    student_id = submission['telegram_id']

    # Notify student
    try:
        await context.bot.send_message(
            chat_id=student_id,
            text=f"You have received a new comment on your submission for Module {submission['module']}:\n\n_{comment}_",
            parse_mode='MarkdownV2'
        )
    except Exception:
        logger.warning(f"Failed to send comment notification to user {student_id}")

    await update.message.reply_text("✅ Comment saved and sent to the student.")
    context.user_data.pop('grading_sub_id', None)
    return ConversationHandler.END


async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the admin's answer to a student's question."""
    question_id = context.user_data.get('answer_question_id')
    if not question_id:
        return ConversationHandler.END

    answer_text = update.message.text
    if not answer_text:
        await update.message.reply_text("Answer cannot be empty. Please send a text answer.")
        return

    await update_question_answer(question_id, answer_text)
    question = await get_question(question_id)
    student_id = question['telegram_id']

    # Notify student
    try:
        await context.bot.send_message(
            chat_id=student_id,
            text=f"💡 You have received an answer to your question:\n\n*Q: {question['question']}*\n\n*A: {answer_text}*",
            parse_mode='Markdown'
        )
    except Exception:
        logger.warning(f"Failed to send answer to user {student_id}")

    await update.message.reply_text("✅ Answer saved and sent to the student.")
    context.user_data.pop('answer_question_id', None)
    return ConversationHandler.END
