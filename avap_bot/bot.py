"""
AVAP Support Bot - Modular Architecture
Main entrypoint with FastAPI + Telegram bot integration
"""
import os
import logging
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ChatType
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Import modular components - FIXED IMPORTS
from avap_bot.handlers import register_all
from avap_bot.handlers.tips import schedule_daily_tips
from avap_bot.handlers.webhook import webhook_handler, health_check
from avap_bot.web.admin_endpoints import router as admin_router

from avap_bot.services.supabase_service import init_supabase
from avap_bot.services.notifier import notify_admin_telegram
from avap_bot.utils.logging_config import setup_logging
from avap_bot.utils.run_blocking import shutdown_executor

# Setup logging
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
AUTO_SET_WEBHOOK = os.getenv("AUTO_SET_WEBHOOK", "false").lower() == "true"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# FastAPI app
app = FastAPI(title="AVAP Support Bot", version="2.0.0")

# Telegram application
telegram_app = None
scheduler = None


@app.on_event("startup")
async def on_startup():
    """Initialize bot on startup"""
    global telegram_app, scheduler
    
    try:
        logger.info("🚀 Starting AVAP Support Bot v2.0.0")
        
        # Initialize Supabase
        init_supabase()
        logger.info("✅ Supabase initialized")
        
        # Initialize Telegram application
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        
        # Register handlers
        register_all(telegram_app)
        logger.info("✅ Handlers registered")
        
        # Initialize scheduler
        scheduler = AsyncIOScheduler()
        await schedule_daily_tips(telegram_app, scheduler)
        scheduler.start()
        logger.info("✅ Scheduler started")
        
        # Start Telegram application
        await telegram_app.initialize()
        await telegram_app.start()
        logger.info("✅ Telegram application started")
        
        # Set webhook if enabled
        if AUTO_SET_WEBHOOK and RENDER_EXTERNAL_URL:
            await _set_webhook()
        
        logger.info("🎉 Bot startup complete")
        
    except Exception as e:
        logger.exception("❌ Bot startup failed: %s", e)
        raise


@app.on_event("shutdown")
async def on_shutdown():
    """Cleanup on shutdown"""
    global telegram_app, scheduler
    
    try:
        logger.info("🛑 Shutting down bot...")
        
        # Stop scheduler
        if scheduler:
            scheduler.shutdown()
            logger.info("✅ Scheduler stopped")
        
        # Stop Telegram application
        if telegram_app:
            await telegram_app.stop()
            await telegram_app.shutdown()
            logger.info("✅ Telegram application stopped")
        
        # Shutdown thread pool
        shutdown_executor()
        logger.info("✅ Thread pool shutdown")
        
        logger.info("✅ Bot shutdown complete")
        
    except Exception as e:
        logger.exception("❌ Bot shutdown error: %s", e)


# Handler registration is now handled by register_all() from handlers package


async def _set_webhook():
    """Set webhook URL"""
    try:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{BOT_TOKEN}"
        
        # Delete existing webhook
        await telegram_app.bot.delete_webhook()
        
        # Set new webhook
        result = await telegram_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query", "chat_join_request"]
        )
        
        if result:
            logger.info("✅ Webhook set successfully: %s", webhook_url)
        else:
            logger.warning("⚠️ Failed to set webhook")

    except Exception as e:
        logger.exception("❌ Failed to set webhook: %s", e)


# Webhook endpoint
@app.post("/webhook/{token}")
async def webhook_endpoint(request: Request, token: str):
    """Handle incoming webhook updates"""
    try:
        # Verify token
        if token != BOT_TOKEN:
            raise HTTPException(status_code=403, detail="Forbidden")
        
        # Get update data
        update_data = await request.json()
        
        # Process update asynchronously
        asyncio.create_task(_process_update(update_data))
        
        return {"status": "ok"}

    except Exception as e:
        logger.exception("Webhook error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


async def _process_update(update_data: dict):
    """Process Telegram update"""
    try:
        from telegram import Update
        update = Update.de_json(update_data, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception as e:
        logger.exception("Failed to process update: %s", e)


# Health check endpoint
@app.get("/health")
async def health():
    """Health check endpoint"""
    return await health_check()


# Admin endpoints
app.include_router(admin_router, prefix="", tags=["admin"])


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "AVAP Support Bot",
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={"error": "Not found", "path": str(request.url)}
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    logger.exception("Internal server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


# Testing functions
async def test_supabase_connection():
    """Test Supabase connection"""
    try:
        client = get_supabase()
        result = client.table("verified_users").select("count").execute()
        logger.info("✅ Supabase connection test passed")
        return True
    except Exception as e:
        logger.error("❌ Supabase connection test failed: %s", e)
        return False


async def test_ai_features():
    """Test AI features"""
    try:
        from avap_bot.services.ai_service import generate_daily_tip, find_faq_match
        
        # Test tip generation
        tip = await generate_daily_tip()
        if tip:
            logger.info("✅ AI tip generation test passed")
        else:
            logger.warning("⚠️ AI tip generation returned empty")
        
        # Test FAQ matching
        faq_match = await find_faq_match("How do I submit an assignment?")
        if faq_match:
            logger.info("✅ FAQ matching test passed")
        else:
            logger.info("ℹ️ No FAQ match found (expected for empty database)")
        
        return True
    except Exception as e:
        logger.error("❌ AI features test failed: %s", e)
        return False


async def test_database_schema():
    """Test database schema"""
    try:
        client = get_supabase()
        
        # Test all required tables exist
        tables = [
            "pending_verifications", "verified_users", "assignments", 
            "wins", "questions", "faqs", "tips", "match_requests"
        ]
        
        for table in tables:
            result = client.table(table).select("count").limit(1).execute()
            if result.error:
                logger.error("❌ Table %s not found or accessible", table)
                return False
            logger.info("✅ Table %s accessible", table)
        
        logger.info("✅ Database schema test passed")
        return True
    except Exception as e:
        logger.error("❌ Database schema test failed: %s", e)
        return False


async def test_environment_variables():
    """Test required environment variables"""
    required_vars = [
        "BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", 
        "ADMIN_USER_ID", "GOOGLE_CREDENTIALS_JSON", "GOOGLE_SHEET_ID"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.warning("⚠️ Missing environment variables: %s", ", ".join(missing_vars))
        return False
    
    logger.info("✅ Environment variables test passed")
    return True


async def run_tests():
    """Run all tests"""
    logger.info("🧪 Running bot tests...")
    
    tests = [
        ("Environment Variables", test_environment_variables),
        ("Database Schema", test_database_schema),
        ("Supabase Connection", test_supabase_connection),
        ("AI Features", test_ai_features),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info("Running %s test...", test_name)
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.exception("Test %s failed with exception: %s", test_name, e)
            results.append((test_name, False))
    
    # Summary
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    logger.info("🧪 Test Results: %d/%d passed", passed, total)
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info("  %s: %s", test_name, status)
    
    return passed == total


if __name__ == "__main__":
    import uvicorn
    import asyncio
    
    # Check if running tests
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "test":
        # Run tests
        asyncio.run(run_tests())
    else:
        # Run bot normally
        port = int(os.getenv("PORT", "8080"))
        logger.info("Starting uvicorn on port %s", port)
        
        uvicorn.run(
            "avap_bot.bot:app",
            host="0.0.0.0",
            port=port,
            log_level="info"
        )
