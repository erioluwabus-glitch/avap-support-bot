#!/usr/bin/env python3
"""
Simplified AVAP Support Bot - Focus on core functionality
"""
import os
import logging
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ChatType

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
ASSIGNMENTS_GROUP_ID = os.getenv("ASSIGNMENTS_GROUP_ID")
QUESTIONS_GROUP_ID = os.getenv("QUESTIONS_GROUP_ID")

# Conversation states
VERIFY_NAME, VERIFY_PHONE, VERIFY_EMAIL = range(3)
SUBMIT_MODULE, SUBMIT_MEDIA = range(3, 5)
ASK_QUESTION = 5
ANSWER_QUESTION = 6
GRADING_COMMENT = 7

# Database setup
db_conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = db_conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS verified_users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        email TEXT,
        verified_at TEXT
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        submission_id TEXT PRIMARY KEY,
        telegram_id INTEGER,
        module INTEGER,
        file_id TEXT,
        file_type TEXT,
        status TEXT DEFAULT 'Pending',
        score INTEGER,
        comment TEXT,
        created_at TEXT
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        question_id TEXT PRIMARY KEY,
        telegram_id INTEGER,
        question TEXT,
        answer TEXT,
        status TEXT DEFAULT 'Open',
        created_at TEXT
    )
""")
db_conn.commit()

# Helper functions
async def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID and int(user_id) == int(ADMIN_USER_ID)

async def user_verified(telegram_id: int) -> bool:
    cur = db_conn.cursor()
    cur.execute("SELECT 1 FROM verified_users WHERE telegram_id = ?", (telegram_id,))
    return cur.fetchone() is not None

def get_main_menu():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📤 Submit Assignment"), KeyboardButton("🎉 Share Win")],
        [KeyboardButton("📊 Check Status"), KeyboardButton("❓ Ask Question")]
    ], resize_keyboard=True, is_persistent=True)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    
    if await user_verified(update.effective_user.id):
        await update.message.reply_text("Welcome back! Choose an option:", reply_markup=get_main_menu())
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Verify Now", callback_data="verify_now")]])
        await update.message.reply_text("Welcome! Please verify your identity first.", reply_markup=keyboard)

# Verification flow
async def verify_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Enter your full name:")
    return VERIFY_NAME

async def verify_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Enter your phone number:")
    return VERIFY_PHONE

async def verify_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("Enter your email:")
    return VERIFY_EMAIL

async def verify_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text
    name = context.user_data['name']
    phone = context.user_data['phone']
    
    # Store in database
    cur = db_conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO verified_users 
        (telegram_id, username, full_name, phone, email, verified_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (update.effective_user.id, update.effective_user.username, name, phone, email, datetime.now().isoformat()))
    db_conn.commit()
    
    await update.message.reply_text("✅ Verification complete! Welcome to AVAP!", reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# Submit assignment
async def submit_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_verified(update.effective_user.id):
        await update.message.reply_text("Please verify first!")
        return
    await update.message.reply_text("Which module? (1-12):")
    return SUBMIT_MODULE

async def submit_module(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        module = int(update.message.text)
        if not (1 <= module <= 12):
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Please enter a number between 1 and 12:")
        return SUBMIT_MODULE
    
    context.user_data['module'] = module
    await update.message.reply_text("Send your video or image:")
    return SUBMIT_MEDIA

async def submit_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    module = context.user_data['module']
    file_id = None
    file_type = None
    
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
    else:
        await update.message.reply_text("Please send a photo or video:")
        return SUBMIT_MEDIA
    
    # Store submission
    submission_id = f"sub_{update.effective_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO submissions (submission_id, telegram_id, module, file_id, file_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (submission_id, update.effective_user.id, module, file_id, file_type, datetime.now().isoformat()))
    db_conn.commit()
    
    # Forward to admin group
    if ASSIGNMENTS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Grade", callback_data=f"grade_{submission_id}")]
        ])
        await context.bot.send_message(
            chat_id=ASSIGNMENTS_GROUP_ID,
            text=f"New submission from @{update.effective_user.username}:\nModule {module}",
            reply_markup=keyboard
        )
    
    await update.message.reply_text("✅ Submission received! You'll get feedback soon.", reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# Ask question
async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_verified(update.effective_user.id):
        await update.message.reply_text("Please verify first!")
        return
    await update.message.reply_text("What's your question?")
    return ASK_QUESTION

async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    question_id = f"q_{update.effective_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Store question
    cur = db_conn.cursor()
    cur.execute("""
        INSERT INTO questions (question_id, telegram_id, question, created_at)
        VALUES (?, ?, ?, ?)
    """, (question_id, update.effective_user.id, question, datetime.now().isoformat()))
    db_conn.commit()
    
    # Forward to admin group
    if QUESTIONS_GROUP_ID:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Answer", callback_data=f"answer_{question_id}")]
        ])
        await context.bot.send_message(
            chat_id=QUESTIONS_GROUP_ID,
            text=f"Question from @{update.effective_user.username}:\n{question}",
            reply_markup=keyboard
        )
    
    await update.message.reply_text("✅ Question sent! You'll get an answer soon.", reply_markup=get_main_menu())
    context.user_data.clear()
    return ConversationHandler.END

# Answer question
async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("Not authorized")
        return
    
    question_id = query.data.split("_", 1)[1]
    context.user_data['question_id'] = question_id
    await query.answer()
    await query.message.reply_text("Send your answer:")
    return ANSWER_QUESTION

async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question_id = context.user_data['question_id']
    answer = update.message.text
    
    # Get question info
    cur = db_conn.cursor()
    cur.execute("SELECT telegram_id FROM questions WHERE question_id = ?", (question_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Question not found")
        return ConversationHandler.END
    
    student_id = row[0]
    
    # Update question
    cur.execute("UPDATE questions SET answer = ?, status = ? WHERE question_id = ?", 
                (answer, "Answered", question_id))
    db_conn.commit()
    
    # Send answer to student
    try:
        await context.bot.send_message(chat_id=student_id, text=f"Answer: {answer}")
    except Exception as e:
        logger.error(f"Failed to send answer: {e}")
    
    await update.message.reply_text("✅ Answer sent!")
    context.user_data.clear()
    return ConversationHandler.END

# Grade submission
async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("Not authorized")
        return
    
    submission_id = query.data.split("_", 1)[1]
    context.user_data['submission_id'] = submission_id
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Comment", callback_data=f"comment_{submission_id}")]
    ])
    await query.answer()
    await query.message.reply_text("Add a comment?", reply_markup=keyboard)

async def comment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id):
        await query.answer("Not authorized")
        return
    
    submission_id = query.data.split("_", 1)[1]
    context.user_data['submission_id'] = submission_id
    context.user_data['expecting_comment'] = True
    
    await query.answer()
    await query.message.reply_text("Send your comment:")
    return GRADING_COMMENT

async def comment_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('expecting_comment'):
        return
    
    submission_id = context.user_data['submission_id']
    comment = update.message.text
    
    # Update submission
    cur = db_conn.cursor()
    cur.execute("UPDATE submissions SET comment = ? WHERE submission_id = ?", (comment, submission_id))
    db_conn.commit()
    
    # Get student info
    cur.execute("SELECT telegram_id FROM submissions WHERE submission_id = ?", (submission_id,))
    row = cur.fetchone()
    if row:
        student_id = row[0]
        try:
            await context.bot.send_message(chat_id=student_id, text=f"Comment on your submission: {comment}")
        except Exception as e:
            logger.error(f"Failed to send comment: {e}")
    
    await update.message.reply_text("✅ Comment sent!")
    context.user_data.clear()
    return ConversationHandler.END

# Check status
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_verified(update.effective_user.id):
        await update.message.reply_text("Please verify first!")
        return
    
    cur = db_conn.cursor()
    cur.execute("SELECT module, status, comment FROM submissions WHERE telegram_id = ?", (update.effective_user.id,))
    submissions = cur.fetchall()
    
    if not submissions:
        await update.message.reply_text("No submissions yet.", reply_markup=get_main_menu())
        return
    
    status_text = "📊 Your Status:\n\n"
    for module, status, comment in submissions:
        status_text += f"Module {module}: {status}"
        if comment:
            status_text += f" (Comment: {comment})"
        status_text += "\n"
    
    await update.message.reply_text(status_text, reply_markup=get_main_menu())

def main():
    """Main function"""
    if not BOT_TOKEN:
        print("BOT_TOKEN not set")
        return
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Create conversation handlers
    verify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(verify_now_callback, pattern="^verify_now$")],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_email)]
        },
        fallbacks=[],
        per_message=False
    )
    
    submit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📤 Submit Assignment$"), submit_assignment)],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_module)],
            SUBMIT_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, submit_media)]
        },
        fallbacks=[],
        per_message=False
    )
    
    ask_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^❓ Ask Question$"), ask_question)],
        states={
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)]
        },
        fallbacks=[],
        per_message=False
    )
    
    answer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(answer_callback, pattern="^answer_")],
        states={
            ANSWER_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_receive)]
        },
        fallbacks=[],
        per_message=False
    )
    
    grading_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(comment_callback, pattern="^comment_")],
        states={
            GRADING_COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, comment_receive)]
        },
        fallbacks=[],
        per_message=False
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(verify_conv)
    app.add_handler(submit_conv)
    app.add_handler(ask_conv)
    app.add_handler(answer_conv)
    app.add_handler(grading_conv)
    app.add_handler(CallbackQueryHandler(grade_callback, pattern="^grade_"))
    app.add_handler(MessageHandler(filters.Regex("^📊 Check Status$"), check_status))
    
    # Start bot
    print("Starting simplified AVAP bot...")
    app.run_polling()

if __name__ == "__main__":
    main()

