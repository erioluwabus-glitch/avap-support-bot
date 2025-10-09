"""
Grading handlers for assignment evaluation
"""
import os
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode

from avap_bot.services.sheets_service import update_submission_grade, add_grade_comment, get_student_submissions
from avap_bot.services.supabase_service import update_assignment_grade, check_verified_user
from avap_bot.utils.run_blocking import run_blocking
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.chat_utils import should_disable_inline_keyboards, create_keyboard_for_chat
from avap_bot.features.cancel_feature import get_cancel_fallback_handler

logger = logging.getLogger(__name__)

# Conversation states
GRADE_SCORE, GRADE_COMMENT = range(2)

ASSIGNMENT_GROUP_ID = int(os.getenv("ASSIGNMENT_GROUP_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Inline grading states for callback data
WAITING_FOR_GRADE = "waiting_for_grade"
WAITING_FOR_COMMENT = "waiting_for_comment"


async def grade_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle assignment grading"""
    if not _is_admin(update):
        await update.message.reply_text("❌ Only admins can grade assignments.")
        return ConversationHandler.END
    
    # Extract submission info from forwarded message
    submission_info = _extract_submission_info(update.message)
    if not submission_info:
        await update.message.reply_text("❌ Could not extract submission information. Make sure the forwarded message contains the student's username, telegram ID, module, and type.")
        return ConversationHandler.END
    
    context.user_data['submission_info'] = submission_info

    # Show grading buttons (check if inline keyboards should be disabled)
    if should_disable_inline_keyboards(update, allow_admin_operations=True):
        logger.info("Disabling inline keyboard for group chat")
        keyboard = None
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{i}", callback_data=f"grade_{i}") for i in range(1, 6)],
            [InlineKeyboardButton(f"{i}", callback_data=f"grade_{i}") for i in range(6, 11)],
            [InlineKeyboardButton("❌ Cancel", callback_data="grade_cancel")]
        ])

    await update.message.reply_text(
        f"📝 **Grade Assignment**\n\n"
        f"Student: @{submission_info['username']}\n"
        f"Module: {submission_info['module']}\n"
        f"Type: {submission_info['type']}\n\n"
        f"Select a grade (1-10):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard if keyboard else None
    )
    return GRADE_SCORE


async def grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle grade selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "grade_cancel":
        await query.edit_message_text("❌ Grading cancelled.")
        context.user_data.clear()
        return ConversationHandler.END
    
    score = int(query.data.split("_")[1])
    submission_info = context.user_data['submission_info']
    context.user_data['grade'] = score
    
    try:
        # Update grade in Google Sheets
        await run_blocking(update_submission_grade, submission_info['username'], submission_info['module'], score)
        
        # Replace buttons with comment options (check if inline keyboards should be disabled)
        if should_disable_inline_keyboards(update, allow_admin_operations=True):
            logger.info("Disabling inline keyboard for group chat")
            keyboard = None
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Add Comments", callback_data="add_comment")],
                [InlineKeyboardButton("✅ No Comments", callback_data="no_comment")]
            ])

        await query.edit_message_text(
            f"✅ **Assignment Graded!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {score}/10\n\n"
            f"Would you like to add comments?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard if keyboard else None
        )
        return GRADE_COMMENT
        
    except Exception as e:
        logger.exception("Failed to grade assignment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Grading failed: {str(e)}")
        await query.edit_message_text("❌ Failed to grade assignment. Please try again.")
        return ConversationHandler.END


async def grade_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle comment decision"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "no_comment":
        await query.edit_message_text(
            f"✅ **Grading Complete!**\n\n"
            f"Student: @{context.user_data['submission_info']['username']}\n"
            f"Module: {context.user_data['submission_info']['module']}\n"
            f"Grade: {context.user_data.get('grade', 'N/A')}/10\n"
            f"Comments: None",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify student
        await _notify_student_grade(context, context.user_data['submission_info'], context.user_data.get('grade'), None)
        return ConversationHandler.END
    
    # Ask for comment
    await query.edit_message_text(
        f"💬 **Add Comments**\n\n"
        f"Please provide your comments (text, audio, or video):",
        parse_mode=ParseMode.MARKDOWN
    )
    return GRADE_COMMENT


async def add_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle comment submission"""
    try:
        submission_info = context.user_data['submission_info']
        grade = context.user_data.get('grade', 0)
        
        # Get comment content
        comment_text = None
        comment_file_id = None
        comment_file_type = None

        if update.message.text:
            comment_text = update.message.text
        elif update.message.voice:
            comment_file_id = update.message.voice.file_id
            comment_file_type = "voice"
            comment_text = "(Voice comment attached)"
        elif update.message.video:
            comment_file_id = update.message.video.file_id
            comment_file_type = "video"
            comment_text = "(Video comment attached)"
        elif update.message.document:
            comment_file_id = update.message.document.file_id
            comment_file_type = "document"
            comment_text = f"(Document comment attached: {update.message.document.file_name})"
        else:
            await update.message.reply_text("❌ Unsupported comment type. Please send text, document, audio, or video.")
            return GRADE_COMMENT
        
        # Add comment to Google Sheets
        await run_blocking(add_grade_comment, submission_info['username'], submission_info['module'], comment_text)
        
        await update.message.reply_text(
            f"✅ **Comment Added!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {grade}/10\n"
            f"Comment: {comment_text}",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify student
        await _notify_student_grade(context, submission_info, grade, comment_text, comment_file_id, comment_file_type)
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.exception("Failed to add comment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Comment addition failed: {str(e)}")
        await update.message.reply_text("❌ Failed to add comment. Please try again.")
        return ConversationHandler.END


async def _notify_student_grade(context: ContextTypes.DEFAULT_TYPE, submission_info: Dict[str, Any], grade: int, comment: Optional[str], comment_file_id: Optional[str] = None, comment_file_type: Optional[str] = None):
    """Notify student about their grade"""
    try:
        telegram_id = submission_info.get('telegram_id')
        username = submission_info.get('username', 'Unknown')
        
        if not telegram_id:
            logger.warning(f"Could not notify student: telegram_id is missing from submission info for {username}")
            await notify_admin_telegram(context.bot, f"Could not notify @{username}, telegram_id missing.")
            return

        logger.info(f"Preparing to notify student {telegram_id} (@{username}) about grade {grade}")

        message = (
            f"🎉 **Your assignment has been graded!**\n\n"
            f"**Module:** {submission_info['module']}\n"
            f"**Type:** {submission_info.get('type', 'Unknown')}\n"
            f"**Grade:** {grade}/10\n"
        )

        if comment:
            message += f"\n**Comments:**\n{comment}"
        else:
            message += "\n**Comments:**\nNo comments provided."

        # Send the main notification text
        logger.info(f"Sending grade notification to student {telegram_id}")
        await context.bot.send_message(chat_id=telegram_id, text=message, parse_mode=ParseMode.MARKDOWN)

        # If there is a file comment, send it as a separate message
        if comment_file_id and comment_file_type:
            logger.info(f"Sending {comment_file_type} comment to student {telegram_id}")
            if comment_file_type == 'voice':
                await context.bot.send_voice(chat_id=telegram_id, voice=comment_file_id)
            elif comment_file_type == 'video':
                await context.bot.send_video(chat_id=telegram_id, video=comment_file_id)
            elif comment_file_type == 'document':
                await context.bot.send_document(chat_id=telegram_id, document=comment_file_id)

        logger.info(f"Successfully notified student {telegram_id} (@{username}) about grade {grade}")

    except Exception as e:
        logger.exception(f"Failed to notify student {telegram_id} (@{username}) about grade: {e}")
        await notify_admin_telegram(context.bot, f"Failed to notify student {telegram_id} (@{username}) about grade. Error: {e}")


async def view_grades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle student request to view their grades"""
    user_id = update.effective_user.id

    # Check if user is verified
    verified_user = check_verified_user(user_id)
    if not verified_user:
        await update.message.reply_text("❌ You need to be verified to view your grades. Use /start to begin verification.")
        return

    try:
        # Get student's submissions
        username = verified_user.get('username')
        telegram_id = verified_user.get('telegram_id')

        logger.info(f"Looking up submissions for username: '{username}', telegram_id: {telegram_id}")
        submissions = await run_blocking(get_student_submissions, username, None, telegram_id)

        logger.info(f"Retrieved {len(submissions)} submissions for user {username or f'telegram_id:{telegram_id}'}")
        logger.info(f"Verified user data: {verified_user}")
        for i, sub in enumerate(submissions):
            logger.info(f"Submission {i}: username='{sub.get('username')}', status='{sub.get('status')}', grade='{sub.get('grade')}', module='{sub.get('module')}'")

        # If no submissions found by username, try searching by telegram_id as fallback
        if not submissions and verified_user.get('telegram_id'):
            logger.info(f"No submissions found by username, trying telegram_id: {verified_user['telegram_id']}")
            # Note: This would require updating the sheets_service to support telegram_id lookup

        if not submissions:
            await update.message.reply_text(
                "📊 **Your Grades**\n\n"
                "You haven't submitted any assignments yet.\n"
                "Use the menu to submit your first assignment!",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Filter graded submissions - check for various possible status values
        # First, let's see what status values exist in the data
        all_statuses = set(s.get('status') for s in submissions if s.get('status'))
        logger.info(f"All status values found in submissions: {all_statuses}")

        # Check for common graded status variations
        graded_submissions = [s for s in submissions if s.get('status') in ['Graded', 'graded', 'GRADED', 'Complete', 'complete', 'COMPLETED']]

        logger.info(f"Found {len(graded_submissions)} graded submissions out of {len(submissions)} total submissions")
        for i, sub in enumerate(graded_submissions):
            logger.info(f"Graded submission {i}: status='{sub.get('status')}', grade='{sub.get('grade')}', module='{sub.get('module')}'")

        if not graded_submissions:
            # Also check if there are any submissions with grades but different status
            submissions_with_grades = [s for s in submissions if s.get('grade') and s.get('grade') != 'N/A' and str(s.get('grade')).strip()]
            logger.info(f"Found {len(submissions_with_grades)} submissions with grade values regardless of status")

            if submissions_with_grades:
                logger.info("Found submissions with grades but non-graded status, using those instead")
                graded_submissions = submissions_with_grades

                # Update the message to reflect this situation
                await update.message.reply_text(
                    "📊 **Your Grades**\n\n"
                    "⚠️ Found assignments with grades but different status. Showing all assignments with grade data:\n\n",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "📊 **Your Grades**\n\n"
                    "You have submitted assignments, but none have been graded yet.\n"
                    "Please wait for your assignments to be reviewed.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

        # Show graded assignments
        message = "📊 **Your Graded Assignments**\n\n"

        for submission in graded_submissions:
            module = submission.get('module', 'Unknown')
            grade_value = submission.get('grade', 'N/A')
            comments = submission.get('comments', 'No comments')

            logger.info(f"Processing submission: module={module}, grade_value='{grade_value}', comments='{comments}', type={type(grade_value)}")

            # Handle grade value - should be numeric now
            if isinstance(grade_value, (int, float)) and grade_value > 0:
                grade = str(grade_value)
            elif isinstance(grade_value, str) and grade_value.isdigit():
                grade = grade_value
            else:
                # Fallback for old format or invalid grades
                grade = 'N/A'
                logger.warning(f"Invalid grade format for module {module}: {grade_value}")

            logger.info(f"Displaying graded submission: module={module}, grade={grade}, comments={comments}")

            message += (
                f"**Module:** {module}\n"
                f"**Grade:** {grade}/10\n"
                f"**Comments:** {comments}\n\n"
            )

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.exception("Failed to show student grades: %s", e)
        await update.message.reply_text("❌ Failed to retrieve your grades. Please try again later.")


def _extract_submission_info(message) -> Optional[Dict[str, Any]]:
    """Extract submission info from forwarded message or bot message"""
    try:
        # Check if this is a forwarded message from a student
        # Note: forward_from was removed in newer versions of python-telegram-bot
        # We'll check for forwarded message indicators in the text instead
        text = message.text or message.caption or ""
        
        # Check if this looks like a forwarded assignment message
        is_forwarded = (
            "📝 **New Assignment Submission**" in text or
            "Student:" in text or
            "Telegram ID:" in text or
            "Module:" in text
        )
        
        if is_forwarded:
            # This is a forwarded message - extract from the forwarded message content
            # Look for student info in the forwarded message
            username_match = re.search(r"Student: @(\w+)", text)
            telegram_id_match = re.search(r"Telegram ID: (\d+)", text)
            module_match = re.search(r"Module: (\d+)", text)
            type_match = re.search(r"Type: (\w+)", text)

            if username_match and module_match and type_match and telegram_id_match:
                return {
                    'username': username_match.group(1),
                    'telegram_id': int(telegram_id_match.group(1)),
                    'module': module_match.group(1),
                    'type': type_match.group(1),
                }
        else:
            # This might be a bot message with assignment details - look for the pattern

            # Look for assignment details pattern
            username_match = re.search(r"Student: @(\w+)", text)
            telegram_id_match = re.search(r"Telegram ID: (\d+)", text)
            module_match = re.search(r"Module: (\d+)", text)
            type_match = re.search(r"Type: (\w+)", text)

            if username_match and module_match and type_match and telegram_id_match:
                return {
                    'username': username_match.group(1),
                    'telegram_id': int(telegram_id_match.group(1)),
                    'module': module_match.group(1),
                    'type': type_match.group(1),
                }

        logger.warning("Could not extract all required info from message text: %s", text)
        return None

    except Exception as e:
        logger.exception("Failed to extract submission info: %s", e)
        return None


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel command"""
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    """Check if user is admin"""
    user_id = update.effective_user.id
    return user_id == ADMIN_USER_ID


def create_grading_keyboard(submission_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for grading assignments"""
    keyboard = [
        [InlineKeyboardButton("📝 GRADE", callback_data=f"grade_start:{submission_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"grade_cancel:{submission_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_score_keyboard(submission_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for selecting grade scores"""
    keyboard = [
        [InlineKeyboardButton(f"{i}", callback_data=f"grade_score:{submission_id}:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(f"{i}", callback_data=f"grade_score:{submission_id}:{i}") for i in range(6, 11)],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"grade_cancel:{submission_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_comment_keyboard(submission_id: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for comment options"""
    keyboard = [
        [InlineKeyboardButton("💬 Add Comment", callback_data=f"grade_comment:{submission_id}:yes")],
        [InlineKeyboardButton("✅ No Comment", callback_data=f"grade_comment:{submission_id}:no")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_inline_grading(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline grading button clicks"""
    query = update.callback_query
    await query.answer()

    logger.info(f"Inline grading callback received: {query.data} from user {update.effective_user.id}")

    if not _is_admin(update):
        logger.warning(f"Non-admin user {update.effective_user.id} tried to grade assignment")
        await query.edit_message_text("❌ Only admins can grade assignments.")
        return

    callback_data = query.data

    if callback_data.startswith("grade_start:"):
        # Extract submission ID and show grade selection
        submission_id = callback_data.split(":", 1)[1]

        # Store submission info in context
        context.user_data['grading_submission_id'] = submission_id
        context.user_data['grading_message_id'] = query.message.message_id

        # Update message with grade selection buttons (check if inline keyboards should be disabled)
        keyboard = create_score_keyboard(submission_id)
        if should_disable_inline_keyboards(update, allow_admin_operations=True):
            logger.info("Disabling inline keyboard for group chat in callback query")
            await query.edit_message_text("❌ Inline keyboards are disabled in group chats.")
        else:
            await query.edit_message_reply_markup(reply_markup=keyboard)

    elif callback_data.startswith("grade_score:"):
        # Extract submission ID and score
        parts = callback_data.split(":")
        submission_id = parts[1]
        score = int(parts[2])

        # Store grade in context
        context.user_data['grading_score'] = score
        context.user_data['grading_submission_id'] = submission_id

        # Update message to show selected grade and ask for comment
        keyboard = create_comment_keyboard(submission_id)

        # Get submission info for display
        submission_info = await get_submission_info(submission_id)
        if submission_info:
            if should_disable_inline_keyboards(update, allow_admin_operations=True):
                logger.info("Disabling inline keyboard for group chat in callback query")
                await query.edit_message_text(
                    f"✅ **Grade Selected!**\n\n"
                    f"Student: @{submission_info['username']}\n"
                    f"Module: {submission_info['module']}\n"
                    f"Grade: {score}/10\n\n"
                    f"❌ Inline keyboards are disabled in group chats. Please use DM for grading.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    f"✅ **Grade Selected!**\n\n"
                    f"Student: @{submission_info['username']}\n"
                    f"Module: {submission_info['module']}\n"
                    f"Grade: {score}/10\n\n"
                    f"Would you like to add comments?",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
        else:
            await query.edit_message_text("❌ Error: Could not find submission information.")

    elif callback_data.startswith("grade_comment:"):
        # Extract submission ID and comment decision
        parts = callback_data.split(":")
        submission_id = parts[1]
        wants_comment = parts[2] == "yes"

        if not wants_comment:
            # No comment - complete grading
            await complete_grading_without_comment(update, context, submission_id)
        else:
            # Wants comment - ask for comment
            # Ensure we have the required context data
            context.user_data['grading_submission_id'] = submission_id
            if not context.user_data.get('grading_score'):
                # Try to get score from previous context, default to 0 if not found
                context.user_data['grading_score'] = context.user_data.get('grading_score', 0)

            # Log context setup for debugging
            logger.info(f"Setting up grading context for comment: submission_id={submission_id}, score={context.user_data.get('grading_score')}")
            logger.info(f"Context keys after setup: {list(context.user_data.keys())}")

            await query.edit_message_text(
                f"💬 **Add Comments**\n\n"
                f"Please provide your comments (text, audio, or video).\n"
                f"Reply to this message with your comment.",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_comment'] = True
            
            # Log final context state
            logger.info(f"Final grading context: {context.user_data.get('grading_submission_id')}, {context.user_data.get('grading_score')}, {context.user_data.get('waiting_for_comment')}")

    elif callback_data.startswith("grade_cancel:"):
        # Cancel grading
        submission_id = callback_data.split(":", 1)[1]
        await query.edit_message_text("❌ Grading cancelled.")
        # Clear context data
        context.user_data.pop('grading_submission_id', None)
        context.user_data.pop('grading_score', None)
        context.user_data.pop('grading_message_id', None)
        context.user_data.pop('waiting_for_comment', None)


async def handle_comment_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle comment submission for grading"""
    # FIRST: Check if this is a question answer - ignore completely if so
    if context.user_data.get('question_username') or context.user_data.get('question_telegram_id'):
        # This is a question answer, let questions handler process it
        return
    
    # SECOND: Check if this is a broadcast message - ignore completely if so
    if context.user_data.get('broadcast_type') or context.user_data.get('broadcast_content'):
        # This is a broadcast message, let broadcast handler process it
        return
    
    # THIRD: Check if this is a grading comment (more specific check)
    if not context.user_data.get('waiting_for_comment'):
        # This is not a grading message, ignore silently
        return
    
    logger.info(f"🔄 GRADING COMMENT HANDLER CALLED from user {update.effective_user.id}")
    logger.info(f"Message type: {type(update.message)}")
    logger.info(f"User data keys: {list(context.user_data.keys())}")
    
    # Additional check: make sure this is NOT a question answering context
    if context.user_data.get('question_username') or context.user_data.get('question_telegram_id'):
        logger.info(f"❌ User {update.effective_user.id} is in question answering mode, not grading mode")
        return

    submission_id = context.user_data.get('grading_submission_id')
    score = context.user_data.get('grading_score')

    if not submission_id or not score:
        logger.warning(f"❌ Incomplete grading context for user {update.effective_user.id}: submission_id={submission_id}, score={score}")
        
        # Try to recover context from recent grading activity
        # Look for any recent grading context in the user's data
        if not submission_id and not score:
            logger.info("Attempting to recover grading context...")
            # Check if there are any recent grading-related keys
            grading_keys = [k for k in context.user_data.keys() if 'grading' in k.lower()]
            if grading_keys:
                logger.info(f"Found grading-related keys: {grading_keys}")
                # Try to extract submission_id from any available context
                for key in grading_keys:
                    if 'submission' in key.lower() and context.user_data[key]:
                        submission_id = context.user_data[key]
                        logger.info(f"Recovered submission_id from {key}: {submission_id}")
                        break
            
            # If we still don't have context, ask user to restart grading
            if not submission_id:
                await update.message.reply_text(
                    "❌ **Grading session expired**\n\n"
                    "Your grading context was lost. Please:\n"
                    "1. Click the 'Grade' button again on the assignment\n"
                    "2. Select your grade\n"
                    "3. Choose to add comments\n"
                    "4. Then send your comment",
                    parse_mode=ParseMode.MARKDOWN
                )
                # Clear any stale context data
                context.user_data.pop('grading_submission_id', None)
                context.user_data.pop('grading_score', None)
                context.user_data.pop('grading_message_id', None)
                context.user_data.pop('waiting_for_comment', None)
                return
        
        # If we have submission_id but no score, try to get a default score
        if submission_id and not score:
            logger.info(f"Recovered submission_id but no score, using default score of 5")
            score = 5  # Default score
            context.user_data['grading_score'] = score
    
    logger.info(f"✅ Grading context found for user {update.effective_user.id}: submission_id={submission_id}, score={score}")

    # Get comment content
    comment_text = None
    comment_file_id = None
    comment_file_type = None

    if update.message.text:
        comment_text = update.message.text
    elif update.message.voice:
        comment_file_id = update.message.voice.file_id
        comment_file_type = "voice"
        comment_text = "(Voice comment attached)"
    elif update.message.video:
        comment_file_id = update.message.video.file_id
        comment_file_type = "video"
        comment_text = "(Video comment attached)"
    elif update.message.document:
        comment_file_id = update.message.document.file_id
        comment_file_type = "document"
        comment_text = f"(Document comment attached: {update.message.document.file_name})"
    else:
        await update.message.reply_text("❌ Unsupported comment type. Please send text, document, audio, or video.")
        return

    # Complete grading with comment
    await complete_grading_with_comment(update, context, submission_id, score, comment_text, comment_file_id, comment_file_type)


async def complete_grading_without_comment(update: Update, context: ContextTypes.DEFAULT_TYPE, submission_id: str) -> None:
    """Complete grading without comment"""
    score = context.user_data.get('grading_score')
    submission_info = await get_submission_info(submission_id)

    if not submission_info or not score:
        await update.callback_query.edit_message_text("❌ Error: Could not complete grading.")
        return

    try:
        logger.info(f"Starting grading process for submission {submission_id} with score {score}")
        
        # Update grade in Google Sheets
        logger.info(f"Updating grade in Google Sheets for {submission_info['username']} - {submission_info['module']}")
        grade_updated = await run_blocking(update_submission_grade, submission_info['username'], submission_info['module'], score)
        
        if not grade_updated:
            logger.warning(f"Failed to update grade in Google Sheets for {submission_info['username']}")
            await notify_admin_telegram(context.bot, f"⚠️ Warning: Grade may not have been recorded in Google Sheets for {submission_info['username']}")

        # Update message to show completion
        await update.callback_query.edit_message_text(
            f"✅ **Grading Complete!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {score}/10\n"
            f"Comments: None\n\n"
            f"📧 Student has been notified of their grade.",
            parse_mode=ParseMode.MARKDOWN
        )

        # Notify student
        logger.info(f"Notifying student {submission_info.get('telegram_id')} about grade {score}")
        await _notify_student_grade(context, submission_info, score, None)

        # Clear context data
        context.user_data.pop('grading_submission_id', None)
        context.user_data.pop('grading_score', None)
        context.user_data.pop('grading_message_id', None)
        context.user_data.pop('waiting_for_comment', None)
        
        logger.info(f"Grading process completed successfully for {submission_info['username']}")

    except Exception as e:
        logger.exception("Failed to complete grading without comment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Grading failed: {str(e)}")
        await update.callback_query.edit_message_text("❌ Failed to complete grading. Please try again.")


async def complete_grading_with_comment(update: Update, context: ContextTypes.DEFAULT_TYPE, submission_id: str, score: int, comment: str, comment_file_id: str = None, comment_file_type: str = None) -> None:
    """Complete grading with comment"""
    submission_info = await get_submission_info(submission_id)

    if not submission_info:
        await update.message.reply_text("❌ Error: Could not find submission information.")
        return

    try:
        logger.info(f"Starting grading with comment process for submission {submission_id} with score {score}")
        
        # First, update the grade in Google Sheets
        logger.info(f"Updating grade in Google Sheets for {submission_info['username']} - {submission_info['module']} with score {score}")
        grade_updated = await run_blocking(update_submission_grade, submission_info['username'], submission_info['module'], score)
        
        if not grade_updated:
            logger.warning(f"Failed to update grade in Google Sheets for {submission_info['username']}")
            await notify_admin_telegram(context.bot, f"⚠️ Warning: Grade may not have been recorded in Google Sheets for {submission_info['username']}")
        
        # Then, add comment to Google Sheets
        logger.info(f"Adding comment to Google Sheets for {submission_info['username']} - {submission_info['module']}")
        comment_added = await run_blocking(add_grade_comment, submission_info['username'], submission_info['module'], comment)
        
        if not comment_added:
            logger.warning(f"Failed to add comment to Google Sheets for {submission_info['username']}")
            await notify_admin_telegram(context.bot, f"⚠️ Warning: Comment may not have been recorded in Google Sheets for {submission_info['username']}")

        # Update message to show completion
        await update.message.reply_text(
            f"✅ **Comment Added & Grading Complete!**\n\n"
            f"Student: @{submission_info['username']}\n"
            f"Module: {submission_info['module']}\n"
            f"Grade: {score}/10\n"
            f"Comment: {comment}\n\n"
            f"📧 Student has been notified of their grade.",
            parse_mode=ParseMode.MARKDOWN
        )

        # Notify student
        logger.info(f"Notifying student {submission_info.get('telegram_id')} about grade {score} with comment")
        await _notify_student_grade(context, submission_info, score, comment, comment_file_id, comment_file_type)

        # Clear context data
        context.user_data.pop('grading_submission_id', None)
        context.user_data.pop('grading_score', None)
        context.user_data.pop('grading_message_id', None)
        context.user_data.pop('waiting_for_comment', None)
        
        logger.info(f"Grading with comment process completed successfully for {submission_info['username']}")

    except Exception as e:
        logger.exception("Failed to complete grading with comment: %s", e)
        await notify_admin_telegram(context.bot, f"❌ Grading with comment failed: {str(e)}")
        await update.message.reply_text("❌ Failed to complete grading. Please try again.")

        # Clear context data even on failure to prevent stuck state
        context.user_data.pop('grading_submission_id', None)
        context.user_data.pop('grading_score', None)
        context.user_data.pop('grading_message_id', None)
        context.user_data.pop('waiting_for_comment', None)


async def get_submission_info(submission_id: str) -> Optional[Dict[str, Any]]:
    """Get submission information by ID"""
    from avap_bot.services.sheets_service import get_submission_by_id

    try:
        # Use run_blocking to call the synchronous sheets service function
        submission_info = await run_blocking(get_submission_by_id, submission_id)
        return submission_info
    except Exception as e:
        logger.exception(f"Failed to get submission info for {submission_id}: {e}")
        return None


# Conversation handler - available to admins in any chat
grade_conv = ConversationHandler(
    entry_points=[CommandHandler("grade", grade_assignment)],
    states={
        GRADE_SCORE: [CallbackQueryHandler(grade_score, pattern="^grade_|^grade_cancel$")],
        GRADE_COMMENT: [
            CallbackQueryHandler(grade_comment, pattern="^add_comment$|^no_comment$"),
            MessageHandler(filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO, add_comment)
        ],
    },
    fallbacks=[get_cancel_fallback_handler()],
    per_message=False,  # explicit
    conversation_timeout=600
)


def register_handlers(application):
    """Register all grading handlers with the application"""
    # Add conversation handler - available to admins for grading assignments
    application.add_handler(grade_conv)

    # Add inline grading handlers - handle all grading-related callbacks
    application.add_handler(CallbackQueryHandler(handle_inline_grading, pattern="^grade_"))
    # Only handle comment submission when user is in grading context
    application.add_handler(MessageHandler(
        filters.TEXT | filters.Document.ALL | filters.VOICE | filters.VIDEO,
        handle_comment_submission,
        block=False  # Don't block other handlers - let questions handler process question answers
    ))

    # Add command for students to view their grades (only in private chats)
    application.add_handler(CommandHandler("grades", view_grades_handler))