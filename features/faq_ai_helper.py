"""
AI-powered FAQ Helper feature for AVAP bot.
Automatically generates suggested answers for unanswered questions using OpenAI.
"""
import logging
import os
import uuid
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters, Application
from utils.db_access import add_question, mark_question_answered, get_unanswered_questions, find_similar_faq, add_faq_history
from utils.faq_semantic import semantic_find, add_to_index
from utils.openai_client import suggest_answer
from utils.translator import translate

logger = logging.getLogger(__name__)

# Environment variables
QUESTIONS_GROUP_ID = int(os.getenv("QUESTIONS_GROUP_ID", "0")) if os.getenv("QUESTIONS_GROUP_ID") else None
UNANSWER_TIMEOUT_HOURS = int(os.getenv("UNANSWER_TIMEOUT_HOURS", "6"))
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

async def ask_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask command from groups or DMs."""
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question>")
        return
    
    question_text = " ".join(context.args)
    question_id = str(uuid.uuid4())
    
    # Get user info
    user = update.effective_user
    username = user.username or user.full_name or "Unknown"
    telegram_id = user.id
    
    # Before storing, try immediate reuse from history or semantic index
    try:
        answer = None
        # Semantic match (if available)
        answer = semantic_find(question_text) or answer
        # Fallback to difflib-based match from DB
        similar = await find_similar_faq(question_text)
        if not answer and similar:
            answer = similar.get("answer")
        if answer:
            await update.message.reply_text(f"🤖 This looks similar to a previous question. Here's an answer that might help:\n\n{answer}")
        # Still proceed to store and forward so admins can refine
    except Exception:
        pass

    # Add question to database
    success = await add_question(question_id, telegram_id, username, question_text)
    if not success:
        await update.message.reply_text("❌ Failed to submit question. Please try again.")
        return
    
    # Forward to questions group with Answer button
    if QUESTIONS_GROUP_ID:
        try:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Answer", callback_data=f"answer_{question_id}")
            ]])
            
            message = f"❓ Question from @{username}:\n\n{question_text}"
            await context.bot.send_message(
                chat_id=QUESTIONS_GROUP_ID,
                text=message,
                reply_markup=keyboard
            )
            
            await update.message.reply_text("✅ Question sent to support team!")
            
        except Exception as e:
            logger.exception(f"Failed to forward question to group: {e}")
            await update.message.reply_text("❌ Failed to send question to support team.")
    else:
        await update.message.reply_text("✅ Question recorded!")

async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Answer button click in questions group."""
    query = update.callback_query
    if not query:
        return
    
    # Check admin access
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("Admin access required.", show_alert=True)
        return
    
    await query.answer()
    
    # Extract question ID from callback data
    question_id = query.data.split("_", 1)[1]
    context.user_data['answering_question_id'] = question_id
    
    await query.message.reply_text("Please provide your answer:")

async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin's answer to a question."""
    question_id = context.user_data.get('answering_question_id')
    if not question_id:
        return
    
    answer_text = update.message.text
    if not answer_text:
        await update.message.reply_text("Please provide a valid answer.")
        return
    
    # Mark question as answered
    success = await mark_question_answered(question_id)
    if not success:
        await update.message.reply_text("❌ Failed to mark question as answered.")
        return
    
    # Archive in FAQ history for future reuse and update semantic index
    try:
        # We don't have the original question text here; reuse the message replied to if available
        original_question = None
        if update.message and update.message.reply_to_message:
            original_question = update.message.reply_to_message.text
        q_text = original_question or ""
        await add_faq_history(q_text, answer_text)
        try:
            add_to_index(q_text, answer_text)
        except Exception:
            pass
    except Exception:
        logger.exception("Failed to archive FAQ history")

    # Send confirmation
    await update.message.reply_text("✅ Answer recorded!")
    
    # Clear the question ID from context
    context.user_data.pop('answering_question_id', None)

async def check_unanswered_questions(application: Application):
    """Check for unanswered questions and generate AI suggestions."""
    try:
        unanswered = await get_unanswered_questions(UNANSWER_TIMEOUT_HOURS)
        
        for question in unanswered:
            question_id = question['question_id']
            question_text = question['question']
            telegram_id = question['telegram_id']
            username = question['username']
            
            # Try to reuse similar previous FAQ first
            suggestion = None
            similar = await find_similar_faq(question_text)
            if similar:
                suggestion = similar.get("answer")
            else:
                # Generate AI suggestion
                suggestion = await suggest_answer(question_text)
            if not suggestion:
                continue
            
            # Send suggestion to questions group
            if QUESTIONS_GROUP_ID:
                try:
                    message = f"🤖 Draft answer (auto-generated):\n\n"
                    message += f"Question from @{username}:\n{question_text}\n\n"
                    message += f"Suggested answer:\n{suggestion}\n\n"
                    message += f"Please review and send the final answer using the Answer button."
                    
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("Answer", callback_data=f"answer_{question_id}")
                    ]])
                    
                    await application.bot.send_message(
                        chat_id=QUESTIONS_GROUP_ID,
                        text=message,
                        reply_markup=keyboard
                    )
                    
                    # Also send to the student
                    student_message = f"🤖 We're working on your question and have generated a draft answer. Our team will review and send you the final response soon!"
                    await application.bot.send_message(
                        chat_id=telegram_id,
                        text=student_message
                    )
                    
                    logger.info(f"Generated AI suggestion for question {question_id}")
                    
                except Exception as e:
                    logger.exception(f"Failed to send AI suggestion for question {question_id}: {e}")
        
    except Exception as e:
        logger.exception(f"Failed to check unanswered questions: {e}")

def register_handlers(application: Application):
    """Register FAQ AI helper handlers."""
    application.add_handler(CommandHandler("ask", ask_handler))
    application.add_handler(CallbackQueryHandler(answer_callback, pattern="^answer_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_receive))

def schedule_faq_check(application: Application):
    """Schedule the FAQ check job."""
    from utils.scheduling import get_scheduler, schedule_faq_check_job
    
    scheduler = get_scheduler()
    schedule_faq_check_job(scheduler, check_unanswered_questions, application)
    
    if not scheduler.running:
        scheduler.start()
        logger.info("FAQ check scheduler started")
