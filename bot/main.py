"""
Main application file for the AVAP Support Bot.
Initializes the FastAPI app, sets up the Telegram bot, and registers all handlers.
"""

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ChatJoinRequestHandler,
)

from .config import BOT_TOKEN, WEBHOOK_URL, logger
from .database import init_db
from .external import gsheets
from .scheduler import setup_scheduler, scheduler
from .models import *
from .handlers import admin, student, general, callback

# Initialize the FastAPI app
app = FastAPI(title="AVAP Support Bot")

# --- Telegram Application Setup ---

def register_handlers(application: Application):
    """Registers all command, conversation, and callback handlers."""

    # General handlers
    application.add_handler(CommandHandler("start", general.start_handler))
    application.add_handler(CommandHandler("status", general.check_status_handler))
    application.add_handler(CommandHandler("cancel", general.cancel_handler))
    application.add_handler(ChatJoinRequestHandler(general.chat_join_request_handler))

    # Verification conversation
    verify_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback.start_verification_callback, pattern="^verify_now$")],
        states={
            VERIFY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, student.verify_name)],
            VERIFY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, student.verify_phone)],
            VERIFY_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, student.verify_email)],
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(verify_conv)

    # Admin conversations
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler("add_student", admin.add_student_start)],
        states={
            ADD_STUDENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_student_name)],
            ADD_STUDENT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_student_phone)],
            ADD_STUDENT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.add_student_email)],
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(add_student_conv)
    application.add_handler(CommandHandler("verify_student", admin.verify_student_cmd))
    application.add_handler(CommandHandler("remove_student", admin.remove_student_cmd))

    # Student action conversations
    submit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, student.submit_module)],
        states={
            SUBMIT_MODULE: [MessageHandler(filters.Regex(r"^[1-9]$|^1[0-2]$") & ~filters.COMMAND, student.submit_module)],
            SUBMIT_MEDIA_TYPE: [CallbackQueryHandler(callback.submit_media_type_callback, pattern="^media_(video|image)$")],
            SUBMIT_MEDIA_UPLOAD: [MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, student.submit_media_upload)],
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(submit_conv)

    win_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback.win_type_callback, pattern="^win_")],
        states={
            WIN_TYPE: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO & ~filters.COMMAND, student.win_receive)]
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(win_conv)

    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", student.ask_question_receive)],
        states={
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, student.ask_question_receive)]
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(ask_conv)

    # Grading and Answering conversations (reply-based)
    grading_comment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback.comment_choice_callback, pattern="^comment_yes:")],
        states={
            GRADE_COMMENT_UPLOAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.grade_comment_receive)]
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(grading_comment_conv)

    answer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback.answer_question_callback, pattern="^answer:")],
        states={
            ANSWER_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin.answer_receive)]
        },
        fallbacks=[CommandHandler("cancel", general.cancel_handler)],
        per_message=False,
    )
    application.add_handler(answer_conv)

    # Generic callback handlers
    application.add_handler(CallbackQueryHandler(callback.menu_router_callback, pattern="^(submit|share_win|status|ask)$"))
    application.add_handler(CallbackQueryHandler(callback.grade_callback, pattern="^grade:"))
    application.add_handler(CallbackQueryHandler(callback.score_selected_callback, pattern="^score:"))
    application.add_handler(CallbackQueryHandler(callback.comment_choice_callback, pattern="^comment_no:"))

    logger.info("All handlers registered.")


# --- FastAPI Lifecycle Events ---

@app.on_event("startup")
async def on_startup():
    """Actions to perform on application startup."""
    logger.info("Application starting up...")

    # Initialize database
    init_db()

    # Initialize Google Sheets
    gsheets.init_gsheets()

    # Build and initialize the Telegram application
    application = Application.builder().token(BOT_TOKEN).build()
    register_handlers(application)

    await application.initialize()
    await application.start()

    # Store the application instance in the app state
    app.state.telegram_app = application

    # Set up and start the scheduler
    setup_scheduler(application)

    # Set the webhook
    if WEBHOOK_URL:
        try:
            await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
            logger.info(f"Webhook set successfully to {WEBHOOK_URL}")
        except Exception:
            logger.exception("Failed to set webhook.")
    else:
        logger.warning("WEBHOOK_URL not set. Bot will not be able to receive updates via webhook.")


@app.on_event("shutdown")
async def on_shutdown():
    """Actions to perform on application shutdown."""
    logger.info("Application shutting down...")
    application: Application = app.state.telegram_app

    # Stop scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")

    # Stop bot
    await application.stop()
    await application.shutdown()
    logger.info("Telegram application shut down.")


# --- Webhook Endpoints ---

@app.get("/", summary="Health check endpoint")
async def health_check():
    """A simple endpoint to confirm the web server is running."""
    return {"status": "ok"}

@app.post(f"/webhook/{BOT_TOKEN}", include_in_schema=False)
async def telegram_webhook(request: Request):
    """The main webhook endpoint that receives updates from Telegram."""
    application: Application = app.state.telegram_app
    try:
        update_data = await request.json()
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return {"status": "ok"}
    except Exception:
        logger.exception("Error processing webhook update.")
        return {"status": "error"}

@app.get("/set_webhook", summary="Manually set the Telegram webhook")
async def set_webhook_endpoint():
    """An endpoint to manually set the webhook (useful for setup)."""
    if not WEBHOOK_URL:
        raise HTTPException(status_code=500, detail="WEBHOOK_URL is not configured.")

    application: Application = app.state.telegram_app
    try:
        await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        return {"status": "webhook set successfully", "url": WEBHOOK_URL}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
