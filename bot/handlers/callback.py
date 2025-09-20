"""
Handles all callback queries from inline keyboard buttons.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..config import logger, ASSIGNMENTS_GROUP_ID
from ..database import update_submission_score, get_submission, update_submission_comment
from .general import is_admin
from ..models import (
    VERIFY_NAME,
    SUBMIT_MODULE,
    WIN_TYPE,
    ASK_QUESTION,
    ANSWER_QUESTION,
    SUBMIT_MEDIA_TYPE,
)

# --- Main Menu Callbacks ---

async def menu_router_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes main menu callbacks to the appropriate handlers."""
    query = update.callback_query
    await query.answer()

    # Ensure the user and chat are accessible
    if not query.from_user or not query.message or not query.message.chat:
        return

    user_id = query.from_user.id
    chat_type = query.message.chat.type

    # Route based on callback data
    action = query.data

    if action == 'verify_now':
        return await start_verification_callback(update, context)
    elif action == 'submit':
        if chat_type != 'private':
            await query.message.reply_text("Please submit assignments in a private message with me.")
            return
        await query.message.reply_text("Which module are you submitting for? (Please enter a number from 1 to 12)")
        return SUBMIT_MODULE
    elif action == 'share_win':
        if chat_type != 'private':
            await query.message.reply_text("Please share your wins in a private message with me.")
            return
        win_type_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Text", callback_data="win_text"),
             InlineKeyboardButton("Image", callback_data="win_image"),
             InlineKeyboardButton("Video", callback_data="win_video")]
        ])
        await query.message.reply_text("What type of win would you like to share?", reply_markup=win_type_keyboard)
        return WIN_TYPE
    elif action == 'status':
        from .general import check_status_handler
        if chat_type != 'private':
            await query.message.reply_text("Please check your status in a private message with me.")
            return
        # We need to call the handler, which expects an Update object.
        # The query object has the original message.
        await check_status_handler(update, context)
    elif action == 'ask':
        if chat_type != 'private':
            await query.message.reply_text("To ask a question in a group, please use the `/ask <your question>` command.")
            return
        await query.message.reply_text("What is your question?")
        return ASK_QUESTION


async def start_verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the verification conversation flow when a user clicks 'Verify Now'."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("To begin, please enter your full name:")
    return VERIFY_NAME

# --- Submission and Grading Callbacks ---

async def submit_media_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice of media type for submission (Image or Video)."""
    query = update.callback_query
    await query.answer()
    media_type = "video" if query.data == "media_video" else "image"
    context.user_data['submit_media_type'] = media_type
    await query.message.edit_text(f"Please send your {media_type} for module {context.user_data.get('submit_module')}.")
    return SUBMIT_MEDIA_TYPE

async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the initial 'Grade' button click by an admin."""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("This action is for admins only.", show_alert=True)
        return

    sub_id = query.data.split(":", 1)[1]

    score_buttons = [
        [InlineKeyboardButton(str(i), callback_data=f"score:{sub_id}:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"score:{sub_id}:{i}") for i in range(6, 11)],
    ]

    await query.answer()
    # Edit the original message to show the score selection
    await query.message.edit_text(
        f"Grading submission `{sub_id}`. Please select a score:",
        reply_markup=InlineKeyboardMarkup(score_buttons),
        parse_mode='MarkdownV2'
    )

async def score_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles when an admin selects a score for a submission."""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("This action is for admins only.", show_alert=True)
        return

    _, sub_id, score_str = query.data.split(":")
    score = int(score_str)

    await update_submission_score(sub_id, score)

    comment_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Comment", callback_data=f"comment_yes:{sub_id}")],
        [InlineKeyboardButton("No Comment", callback_data=f"comment_no:{sub_id}")],
    ])

    await query.answer(f"Score {score} saved.")
    await query.message.edit_text(f"Submission graded with score {score}. Would you like to add a comment?", reply_markup=comment_kb)

async def comment_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the admin's choice to add a comment or not."""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("This action is for admins only.", show_alert=True)
        return

    action, sub_id = query.data.split(":", 1)

    if action == "comment_no":
        await query.answer("Grading complete.")
        submission = await get_submission(sub_id)
        await query.message.edit_text(f"✅ Graded submission from {submission['username']} for Module {submission['module']} with score {submission['score']}.")
        return ConversationHandler.END
    else: # comment_yes
        context.user_data['grading_sub_id'] = sub_id
        await query.answer("Waiting for comment.")
        await query.message.edit_text("Please send the comment for this submission as a reply to this message.")
        # We need a state to catch the reply, let's call it GRADE_COMMENT
        from ..models import GRADE_COMMENT_UPLOAD
        return GRADE_COMMENT_UPLOAD

# --- Win and Question Callbacks ---

async def win_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice of content type for their 'small win'."""
    query = update.callback_query
    await query.answer()
    win_type = query.data.split('_', 1)[1] # "win_text" -> "text"
    context.user_data['win_type'] = win_type
    await query.message.edit_text(f"Great! Please send your {win_type} win.")
    return WIN_TYPE


async def answer_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Initiates the process for an admin to answer a student's question."""
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("This action is for admins only.", show_alert=True)
        return

    question_id = query.data.split(":", 1)[1]
    context.user_data['answer_question_id'] = question_id

    await query.answer()
    await query.message.edit_text("Please send the answer as a reply to this message. It will be forwarded to the student.")
    return ANSWER_QUESTION
