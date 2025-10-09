"""
Main entry point for the AVAP Support Bot.
"""
import os
import logging
import asyncio
import time
import signal
import sys
from telegram import Update
from telegram.ext import Application
from fastapi import FastAPI, Request, Response, HTTPException
import uvicorn
import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from avap_bot.utils.logging_config import setup_logging
from avap_bot.services.supabase_service import init_supabase
from avap_bot.services.systeme_service import validate_api_key
from avap_bot.services.notifier import send_admin_notification
from avap_bot.handlers import register_all
from avap_bot.handlers.tips import schedule_daily_tips
from avap_bot.utils.cancel_registry import CancelRegistry
from avap_bot.features.cancel_feature import register_cancel_handlers, register_test_handlers
# AI features disabled
from avap_bot.utils.memory_monitor import monitor_memory, cleanup_resources, enable_detailed_memory_monitoring, get_memory_usage, log_memory_usage, ultra_aggressive_cleanup, start_memory_watchdog, graceful_restart

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

def handle_sigterm(signum, frame):
    """Handle SIGTERM signal for graceful shutdown."""
    logger.info("SIGTERM received — shutting down gracefully")
    
    # Clean shutdown - close connections, save state
    try:
        # Stop scheduler if running
        if scheduler and scheduler.running:
            logger.info("Stopping scheduler...")
            scheduler.shutdown(wait=False)
        
        # Give a moment for cleanup
        import time
        time.sleep(1)
        
    except Exception as e:
        logger.error("Error during shutdown cleanup: %s", e)
    
    logger.info("Graceful shutdown completed")
    import sys
    sys.exit(0)

# Register SIGTERM handler
signal.signal(signal.SIGTERM, handle_sigterm)

# Get bot token from environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# Create the FastAPI app
app = FastAPI()

# Health endpoint configuration
HEALTH_TOKEN = os.environ.get("HEALTH_TOKEN", "")
MIN_HEALTH_INTERVAL = int(os.environ.get("MIN_HEALTH_INTERVAL", "15"))  # seconds - increased from 8 to 15
_last_health_ts = 0

# Health endpoint (lightweight monitoring)
@app.get("/health")
@app.head("/health")
async def health_check(request: Request):
    """Lightweight health check endpoint for external monitoring"""
    global _last_health_ts

    # Authentication
    token = request.headers.get("X-Health-Token") or request.query_params.get("token")
    if HEALTH_TOKEN and token != HEALTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Rate limiting
    now = time.time()
    if now - _last_health_ts < MIN_HEALTH_INTERVAL:
        raise HTTPException(status_code=429, detail="Too Many Requests")
    _last_health_ts = now

    # Lightweight health check - no DB or model loads
    headers = {"X-App-State": "ok"}
    return Response(content="OK", status_code=200, headers=headers)

# Include admin endpoints
try:
    from avap_bot.web.admin_endpoints import router as admin_router
    if admin_router:
        app.include_router(admin_router, prefix="/api")
        logger.info("Admin endpoints registered successfully")
except Exception as e:
    logger.warning(f"Failed to register admin endpoints: {e}")

# Create the Telegram bot application
bot_app = Application.builder().token(BOT_TOKEN).build()

# Initialize cancel registry and store in bot data
cancel_registry = CancelRegistry()
bot_app.bot_data['cancel_registry'] = cancel_registry

# Register all handlers
logger.info("🔧 Registering all handlers...")
register_all(bot_app)
logger.info("✅ All handlers registered successfully")

# Register cancel handlers
logger.info("🔧 Registering cancel handlers...")
register_cancel_handlers(bot_app)
logger.info("✅ Cancel handlers registered successfully")

# Register test handlers (development only)
register_test_handlers(bot_app)

# Create scheduler for daily tips with conservative configuration
try:
    # Configure scheduler for async functions with minimal resource usage
    job_defaults = {
        'coalesce': True,  # If multiple instances of same job triggered, only run once
        'max_instances': 1,  # Only one instance of each job at a time
        'misfire_grace_time': 30  # Grace period for missed jobs
    }
    # Use default AsyncIOScheduler configuration which handles async functions properly
    scheduler = AsyncIOScheduler(job_defaults=job_defaults)
    scheduler.start()
    logger.debug("Scheduler started for daily tips with ultra-conservative settings")
    SCHEDULER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"APScheduler not available: {e}")
    logger.warning("Daily tips will not be scheduled automatically")
    scheduler = None
    SCHEDULER_AVAILABLE = False
except Exception as e:
    logger.error(f"Failed to start scheduler: {e}")
    scheduler = None
    SCHEDULER_AVAILABLE = False

# --- Webhook and Health Check ---
def keep_alive_check(bot):
    """Ultra-aggressive keep-alive check to prevent Render timeouts."""
    try:
        # Perform database check to keep connection alive
        from avap_bot.services.supabase_service import get_supabase
        client = get_supabase()
        client.table("verified_users").select("id").limit(1).execute()

        # Make multiple HTTP requests to simulate heavy activity
        import socket

        # Make several requests to show activity
        def make_request(url, timeout=2.0):
            try:
                import requests
                response = requests.get(url, timeout=timeout)
                return response.status_code
            except:
                return None

        # Fire multiple requests
        urls = [
            "http://localhost:8080/health",
            "http://localhost:8080/health",
            "http://localhost:8080/health",
            "http://localhost:8080/ping",
            "http://localhost:8080/",
        ]

        successful_requests = 0
        for url in urls:
            result = make_request(url)
            if result == 200:
                successful_requests += 1

        # Additional network activity
        try:
            socket.gethostbyname('api.telegram.org')
        except:
            pass

        # Additional CPU activity
        _ = sum(i * i for i in range(1000))

        if successful_requests > 0:
            logger.debug(f"Keep-alive: {successful_requests}/5 requests successful")
        else:
            logger.debug("Keep-alive: All requests failed (expected during startup)")

    except Exception as e:
        logger.debug(f"Keep-alive check failed: {e}")
        # Try to reinitialize if there are issues
        try:
            from avap_bot.services.supabase_service import init_supabase
            init_supabase()
            logger.debug("Reinitialized Supabase connection")
        except Exception as reinit_error:
            logger.debug(f"Failed to reinitialize Supabase: {reinit_error}")


def ping_self():
    """Simple ping to keep the service alive."""
    try:
        import requests
        import socket
        # Use sync client
        requests.get("http://localhost:8080/ping", timeout=1.0)
        # Additional activity
        try:
            socket.gethostbyname('telegram.org')
        except:
            pass
    except:
        pass  # Silent fail to avoid log spam


def generate_activity():
    """Generate additional activity to prevent Render timeout."""
    try:
        import socket
        import random
        import time
        import hashlib

        # Generate network activity with multiple domains
        domains = ['google.com', 'api.telegram.org', 'github.com', 'stackoverflow.com']
        for domain in domains:
            try:
                socket.gethostbyname(domain)
            except:
                pass

        # Generate CPU activity with more intensive calculations
        _ = sum(i * i * i for i in range(500))

        # Hash operations to simulate cryptographic work
        data = f"activity-{time.time()}-{random.randint(1, 10000)}".encode()
        hashlib.sha256(data).hexdigest()

        # Small delay to simulate work
        time.sleep(0.005)

    except:
        pass  # Silent fail


def webhook_health_check():
    """Check webhook health with robust 429 handling and distributed locking."""
    try:
        from avap_bot.utils.distributed_lock import acquire_lock, release_lock
        from avap_bot.utils.cooldown_manager import is_cooldown_active, set_cooldown_state
        from avap_bot.utils.http_client import request_with_429_handling
        import time
        import random

        # Check if we're in cooldown
        if is_cooldown_active("webhook_health_check"):
            logger.info("Webhook health check in cooldown - skipping")
            return

        # Try to acquire distributed lock to prevent multiple instances
        lock_token = acquire_lock("webhook_health_check", ttl_seconds=300)  # 5 minute lock
        if not lock_token:
            logger.info("Another instance is handling webhook health check - skipping")
            return

        try:
            webhook_url = os.getenv("WEBHOOK_URL")
            health_token = os.getenv("HEALTH_TOKEN")

            if not webhook_url:
                logger.info("No WEBHOOK_URL set - skipping webhook health check")
                return

            # Add random jitter to avoid synchronized requests
            jitter = random.uniform(1.0, 3.0)
            time.sleep(jitter)

            # Prepare headers
            headers = {}
            if health_token:
                headers["X-Health-Token"] = health_token

            # Make request with 429 handling
            logger.info("Performing webhook health check...")
            response = request_with_429_handling(
                "GET", 
                f"{webhook_url}/health", 
                headers=headers, 
                timeout=10
            )

            if response.status_code == 200:
                logger.debug("Webhook health check: OK")
                # Clear any existing cooldown on success
                from avap_bot.utils.cooldown_manager import clear_cooldown
                clear_cooldown("webhook_health_check")
            elif response.status_code == 401:
                logger.warning("Webhook health check: HTTP 401 - Authentication failed")
            elif response.status_code == 429:
                logger.warning("Webhook health check: HTTP 429 - Rate limited")
                # Set cooldown for 10 minutes to avoid further rate limiting
                cooldown_until = time.time() + 600  # 10 minutes
                set_cooldown_state("webhook_health_check", cooldown_until)
                logger.warning("Set 10-minute cooldown for webhook health check")
            else:
                logger.warning("Webhook health check: HTTP %s", response.status_code)

        except Exception as e:
            logger.warning("Webhook health check failed: %s", e)
            # Set shorter cooldown on error
            cooldown_until = time.time() + 300  # 5 minutes
            set_cooldown_state("webhook_health_check", cooldown_until)

        finally:
            # Always release the lock
            release_lock("webhook_health_check", lock_token)

    except Exception as e:
        logger.error("Webhook health check error: %s", e)


async def health_check():
    """Comprehensive health check endpoint with keep-alive functionality."""
    try:
        # Check if Supabase is still connected
        from avap_bot.services.supabase_service import get_supabase
        client = get_supabase()
        client.table("verified_users").select("id").limit(1).execute()

        # Check if bot application is initialized
        if not bot_app or not hasattr(bot_app, 'bot'):
            raise RuntimeError("Bot application not initialized")

        # Check if scheduler is running
        if not scheduler or scheduler.state == 0:
            logger.warning("Scheduler may not be running properly")

        # Log health check activity to prevent timeouts (less verbose)
        logger.debug("Health check passed - Bot is alive and responsive")

        return {
            "status": "healthy",
            "service": "avap-support-bot",
            "version": "2.0.0",
            "timestamp": time.time(),
            "uptime": "active",
            "supabase_connected": True,
            "bot_initialized": True,
            "scheduler_running": scheduler.running if scheduler else False,
            "keep_alive": "active"
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        logger.debug(f"Received webhook request to: {request.url.path}")
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        logger.debug("Successfully processed webhook update")
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error in webhook: {e}", exc_info=True)
        return Response(status_code=500)

# Handle webhook with bot token in path (Telegram standard format)
app.post("/webhook/{bot_token}")(telegram_webhook)


app.get("/health_check")(health_check)

# Simple ping endpoint for keep-alive
@app.get("/ping")
async def ping():
    """Simple ping endpoint for keep-alive."""
    return {"status": "pong", "timestamp": time.time()}

# Memory cleanup endpoint
@app.post("/admin/cleanup-memory")
async def cleanup_memory():
    """Admin endpoint to manually trigger memory cleanup."""
    try:
        memory_before = get_memory_usage()
        log_memory_usage("before manual cleanup")

        # AI features disabled

        # Force garbage collection
        import gc
        gc.collect()

        memory_after = get_memory_usage()
        log_memory_usage("after manual cleanup")

        memory_freed = memory_before - memory_after

        return {
            "status": "success",
            "memory_before_mb": round(memory_before, 1),
            "memory_after_mb": round(memory_after, 1),
            "memory_freed_mb": round(memory_freed, 1),
            "message": f"Memory cleanup completed. Freed {round(memory_freed, 1)}MB"
        }
    except Exception as e:
        logger.error(f"Memory cleanup failed: {e}")
        # Ensure log_memory_usage is available for error logging
        try:
            from avap_bot.utils.memory_monitor import log_memory_usage
            log_memory_usage("error in cleanup")
        except (NameError, ImportError) as e2:
            logger.error(f"log_memory_usage function not available for error logging: {e2}")
        return {
            "status": "error",
            "error": str(e)
        }

# Root endpoint for basic health check
@app.get("/")
async def root():
    """Root endpoint."""
    return {"status": "ok", "service": "avap-support-bot"}


async def initialize_services():
    """Initializes services and sets up the bot."""
    logger.debug("Initializing services...")

    # Check for critical environment variables first
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        raise Exception("BOT_TOKEN is required for bot operation")

    try:
        # Initialize Supabase (lightweight - no blocking operations)
        try:
            init_supabase()
            logger.debug("Supabase initialized successfully")
        except Exception as e:
            logger.error(f"❌ Supabase initialization failed: {e}")
            logger.warning("Continuing without Supabase - some features may not work")

        # Validate Systeme API key (optional - non-blocking)
        try:
            systeme_api_key = os.getenv('SYSTEME_API_KEY')
            if not systeme_api_key:
                logger.info("SYSTEME_API_KEY not set - Systeme.io integration disabled")
            else:
                if not validate_api_key():
                    logger.warning("SYSTEME_API_KEY validation failed - Systeme.io integration will be disabled")
                    logger.warning("This is not critical - bot will continue to work without Systeme.io integration")
                else:
                    logger.info("Systeme API key validation successful")
        except Exception as e:
            logger.warning(f"Systeme API validation failed: {e}")
            logger.info("Continuing without Systeme.io integration - this is not critical")

        # Initialize the Telegram Application with timeout protection
        logger.debug("Initializing Telegram Application...")
        try:
            await asyncio.wait_for(bot_app.initialize(), timeout=60.0)  # 60 second timeout
            logger.debug("Telegram Application initialized successfully")
        except asyncio.TimeoutError:
            logger.error("❌ Telegram Application initialization timed out")
            raise Exception("Telegram Application initialization failed - cannot continue")
        except Exception as e:
            logger.error(f"❌ Telegram Application initialization failed: {e}")
            raise Exception(f"Telegram Application initialization failed: {e}")

        # Enhanced memory monitoring to prevent Render restarts (reduced frequency)
        try:
            enable_detailed_memory_monitoring()
            bot_app.job_queue.run_repeating(monitor_memory, interval=300, first=60)  # Every 5 minutes, starting in 60 seconds
            await bot_app.job_queue.start()  # Start the job queue
            logger.info("Memory monitoring scheduled every 5 minutes (starting in 60 seconds)")
        except Exception as e:
            logger.error(f"❌ Memory monitoring setup failed: {e}")
            logger.warning("Continuing without memory monitoring")

        # Disable memory watchdog to prevent restart loops
        # start_memory_watchdog()
        logger.info("Memory watchdog disabled to prevent restart loops")

        # Schedule daily tips (if scheduler is available)
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                await schedule_daily_tips(bot_app.bot, scheduler)
                logger.debug("Daily tips scheduled successfully")
            except Exception as e:
                logger.error(f"❌ Daily tips scheduling failed: {e}")
                logger.warning("Continuing without daily tips scheduling")
        else:
            logger.warning("Scheduler not available - daily tips will not be scheduled")

        # Schedule balanced keep-alive health checks to prevent SIGTERM without overwhelming scheduler
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                scheduler.add_job(
                    keep_alive_check,
                    'interval',
                    seconds=45,  # Balanced: Every 45 seconds
                    args=[bot_app.bot],
                    id='keep_alive',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=15
                )
                logger.info("Balanced keep-alive health checks scheduled every 45 seconds")

                # Schedule simple ping every 30 seconds (balanced)
                scheduler.add_job(
                    ping_self,
                    'interval',
                    seconds=30,  # Balanced: Every 30 seconds
                    id='ping_self',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=10
                )
                logger.info("Balanced simple ping scheduled every 30 seconds")

                # Schedule additional activity every 40 seconds (balanced)
                scheduler.add_job(
                    generate_activity,
                    'interval',
                    seconds=40,  # Balanced: Every 40 seconds
                    id='activity_generator',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=10
                )
                logger.info("Balanced activity generator scheduled every 40 seconds")

                # Schedule webhook health check every 15 minutes (further reduced to avoid rate limiting)
                scheduler.add_job(
                    webhook_health_check,
                    'interval',
                    minutes=15,  # Further reduced frequency to avoid rate limiting
                    id='webhook_health',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=60
                )
                logger.info("Webhook health check scheduled every 15 minutes to avoid rate limiting")
                
                # Schedule cleanup of expired locks and cooldowns every hour
                def cleanup_locks_and_cooldowns():
                    try:
                        from avap_bot.utils.distributed_lock import cleanup_expired_locks
                        cleanup_expired_locks()
                        logger.debug("Cleaned up expired locks")
                    except Exception as e:
                        logger.warning("Failed to cleanup expired locks: %s", e)
                
                scheduler.add_job(
                    cleanup_locks_and_cooldowns,
                    'interval',
                    hours=1,
                    id='cleanup_locks',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=300
                )
                logger.info("Lock cleanup scheduled every hour")
                
            except Exception as e:
                logger.warning(f"Failed to schedule some keep-alive jobs: {e}")
        else:
            logger.warning("Scheduler not available - some keep-alive features disabled")

        # Schedule periodic memory cleanup every 10 minutes (if scheduler available)
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                scheduler.add_job(
                    _periodic_memory_cleanup,
                    'interval',
                    minutes=10,
                    id='memory_cleanup',
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=60
                )
                logger.debug("Memory cleanup scheduled every 10 minutes")
            except Exception as e:
                logger.warning(f"Failed to schedule memory cleanup: {e}")
        else:
            logger.warning("Scheduler not available - memory cleanup not scheduled")

        # Schedule FAST aggressive memory cleanup every 15 minutes for critical memory management
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                scheduler.add_job(
                    ultra_aggressive_cleanup,
                    'interval',
                    minutes=15,
                    id='fast_aggressive_memory_cleanup',
                    replace_existing=True,
                    max_instances=1,  # Prevent overlapping instances
                    coalesce=True,
                    misfire_grace_time=60
                )
                logger.debug("FAST aggressive memory cleanup scheduled every 15 minutes")
            except Exception as e:
                logger.warning(f"Failed to schedule FAST aggressive memory cleanup: {e}")
        else:
            logger.warning("Scheduler not available - FAST aggressive memory cleanup not scheduled")

        # Schedule graceful restart daily at 3 AM (low usage time) to prevent memory leaks
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                scheduler.add_job(
                    graceful_restart,
                    'cron',
                    hour=3,
                    minute=0,
                    id='graceful_restart',
                    replace_existing=True,
                    max_instances=1
                )
                logger.debug("Graceful restart scheduled daily at 3 AM")
            except Exception as e:
                logger.warning(f"Failed to schedule graceful restart: {e}")

        logger.info("Services initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize services: {e}", exc_info=True)
        # Exit if services fail to initialize
        raise


def graceful_restart():
    """Graceful restart to prevent memory leaks"""
    try:
        logger.info("🔄 Graceful restart triggered - preventing memory leaks")

        # Log memory before restart
        from avap_bot.utils.memory_monitor import get_memory_usage
        memory_mb = get_memory_usage()
        logger.info(f"Memory before graceful restart: {memory_mb:.1f}MB")

        # Gracefully shutdown scheduler
        if SCHEDULER_AVAILABLE and scheduler:
            try:
                scheduler.shutdown(wait=True)
                logger.info("Scheduler shut down gracefully")
            except Exception as e:
                logger.warning(f"Scheduler shutdown failed: {e}")

        # Exit gracefully (Render will restart the service)
        import sys
        logger.info("Exiting for graceful restart")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Graceful restart failed: {e}")
        # Force exit if graceful restart fails
        import sys
        sys.exit(1)

async def main_polling():
    """Main function to start the bot in polling mode."""
    await initialize_services()
    logger.info("Starting bot in polling mode for local development...")
    await bot_app.run_polling(allowed_updates=["message", "callback_query"])

# Background task to continuously ping health endpoint
def _periodic_memory_cleanup():
    """Periodic memory cleanup to prevent memory leaks."""
    try:
        # Import here to ensure it's available
        from avap_bot.utils.memory_monitor import log_memory_usage

        memory_before = get_memory_usage()
        log_memory_usage("before periodic cleanup")

        # AI features disabled

        # Force garbage collection
        import gc
        gc.collect()

        memory_after = get_memory_usage()
        memory_freed = memory_before - memory_after

        log_memory_usage("after periodic cleanup")

        if memory_freed > 10:  # Only log if we freed significant memory
            logger.info(f"Memory cleanup completed. Freed {memory_freed:.1f}MB (before: {memory_before:.1f}MB, after: {memory_after:.1f}MB)")

    except Exception as e:
        logger.error(f"Periodic memory cleanup failed: {e}")
        # Ensure log_memory_usage is available for error logging
        try:
            from avap_bot.utils.memory_monitor import log_memory_usage
            log_memory_usage("error in cleanup")
        except (NameError, ImportError) as e2:
            logger.error(f"log_memory_usage function not available for error logging: {e2}")


def _aggressive_memory_cleanup():
    """Aggressive memory cleanup for critical memory management"""
    try:
        import gc
        from avap_bot.utils.memory_monitor import get_memory_usage, log_memory_usage
        # AI features disabled
        
        memory_before = get_memory_usage()
        log_memory_usage("before aggressive cleanup")
        
        # AI features disabled
        
        # Force aggressive garbage collection
        for _ in range(5):
            gc.collect()
            
        memory_after = get_memory_usage()
        memory_freed = memory_before - memory_after
        
        log_memory_usage("after aggressive cleanup")
        
        if memory_freed > 5:  # Log if we freed any significant memory
            logger.info(f"Aggressive memory cleanup completed. Freed {memory_freed:.1f}MB (before: {memory_before:.1f}MB, after: {memory_after:.1f}MB)")
        else:
            logger.debug(f"Aggressive memory cleanup completed. Freed {memory_freed:.1f}MB (before: {memory_before:.1f}MB, after: {memory_after:.1f}MB)")
            
    except Exception as e:
        logger.error(f"Aggressive memory cleanup failed: {e}")
        # Ensure log_memory_usage is available for error logging
        try:
            from avap_bot.utils.memory_monitor import log_memory_usage
            log_memory_usage("error in aggressive cleanup")
        except (NameError, ImportError) as e2:
            logger.error(f"log_memory_usage function not available for error logging: {e2}")


async def background_keepalive():
    """Background task that pings the public Render URL to prevent sleep."""
    import asyncio
    import httpx
    import socket

    # Get Render URL from environment variable
    render_url = os.getenv("RENDER_URL", "https://avap-support-bot-93z2.onrender.com")
    
    try:
        while True:
            try:
                # Ping public Render URL to prevent sleep
                tasks = []
                
                # 1. HTTP ping to our public endpoints
                try:
                    tasks.append(
                        httpx.AsyncClient().get(f"{render_url}/health", timeout=10.0)
                    )
                    tasks.append(
                        httpx.AsyncClient().get(f"{render_url}/ping", timeout=10.0)
                    )
                except Exception as e:
                    logger.debug(f"HTTP ping setup failed: {e}")

                # 2. DNS resolution to generate network activity
                try:
                    socket.gethostbyname('google.com')
                    socket.gethostbyname('api.telegram.org')
                except:
                    pass

                # Execute HTTP pings
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    successful_pings = sum(1 for r in results if hasattr(r, 'status_code') and r.status_code == 200)
                    if successful_pings > 0:
                        logger.info(f"Self-ping successful - service kept awake ({successful_pings}/{len(tasks)} pings)")
                    else:
                        logger.warning("Self-ping failed - service may sleep")

            except asyncio.CancelledError:
                logger.info("Background keepalive task cancelled - shutting down gracefully")
                break
            except Exception as e:
                logger.debug(f"Background keepalive error: {e}")
            finally:
                try:
                    await asyncio.sleep(720)  # Ping every 12 minutes (720 seconds)
                except asyncio.CancelledError:
                    logger.info("Background keepalive sleep cancelled - shutting down")
                    break

    except asyncio.CancelledError:
        logger.info("Background keepalive task cancelled during startup - shutting down")
    except Exception as e:
        logger.error(f"Unexpected error in background keepalive: {e}")


async def emergency_keepalive_task():
    """Emergency keepalive task that runs even more aggressively."""
    import asyncio
    import httpx
    import socket
    import random

    try:
        while True:
            try:
                # Emergency keep-alive with multiple concurrent requests
                tasks = []
                
                # Balanced HTTP requests (reduced to prevent memory issues)
                for i in range(2):  # Reduced from 5 to 2
                    try:
                        tasks.append(httpx.AsyncClient().get("http://localhost:8080/ping", timeout=1.0))
                        tasks.append(httpx.AsyncClient().get("http://localhost:8080/health", timeout=1.0))
                    except:
                        pass
                
                # Reduced DNS lookups to prevent memory issues
                domains = ['google.com', 'api.telegram.org']  # Reduced from 5 to 2 domains
                for domain in domains:
                    try:
                        socket.gethostbyname(domain)
                    except:
                        pass
                
                # Reduced CPU activity to prevent memory issues
                _ = sum(i * i for i in range(100))  # Reduced from 1000 to 100
                
                # Execute all tasks concurrently
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
            except asyncio.CancelledError:
                logger.info("Emergency keepalive task cancelled - shutting down")
                break
            except Exception as e:
                logger.debug(f"Emergency keepalive error: {e}")
            finally:
                try:
                    await asyncio.sleep(5.0)  # Balanced: every 5 seconds to reduce memory usage
                except asyncio.CancelledError:
                    logger.info("Emergency keepalive sleep cancelled - shutting down")
                    break
                    
    except asyncio.CancelledError:
        logger.info("Emergency keepalive task cancelled during startup - shutting down")
    except Exception as e:
        logger.error(f"Unexpected error in emergency keepalive: {e}")


# --- FastAPI event handlers ---
@app.on_event("startup")
async def on_startup():
    """Actions to perform on application startup."""
    # Initialize services first (including Telegram Application)
    await initialize_services()

    # Start ULTRA-AGGRESSIVE background keepalive task
    asyncio.create_task(background_keepalive())
    logger.info("🚀 ULTRA-AGGRESSIVE background keepalive task started")
    
    # Emergency keepalive task removed to prevent SIGTERM conflicts
    logger.info("✅ Startup completed without emergency keepalive")

    # Set webhook URL only if needed (check current webhook first)
    webhook_base = os.getenv("WEBHOOK_URL")
    bot_token = os.getenv("BOT_TOKEN")

    if webhook_base and bot_token:
        # Construct proper webhook URL: https://your-app.com/webhook/BOT_TOKEN
        webhook_url = f"{webhook_base.rstrip('/')}/webhook/{bot_token}"
        logger.info(f"Checking webhook with WEBHOOK_URL: {webhook_base}")
        logger.info(f"Checking webhook with BOT_TOKEN: {bot_token[:10]}...")  # Only log first 10 chars for security
        logger.info(f"Target webhook URL: {webhook_url[:50]}...")  # Truncate webhook URL for security

        try:
            # Use the robust webhook setting function
            from avap_bot.utils.http_client import set_webhook_if_needed
            success = set_webhook_if_needed(bot_token, webhook_url)
            
            if success:
                logger.info("✅ Webhook configured successfully")
            else:
                logger.warning("⚠️ Webhook configuration failed - bot will run in polling mode")
                
        except Exception as e:
            logger.error(f"❌ Failed to configure webhook: {e}")
            logger.warning("Bot will run in polling mode if webhook setup fails")
    elif webhook_base:
        logger.warning("WEBHOOK_URL set but BOT_TOKEN missing. Webhook not configured.")
    else:
        logger.warning("WEBHOOK_URL not set. Bot will not receive updates unless webhook is set manually.")

@app.on_event("shutdown")
async def on_shutdown():
    """Actions to perform on application shutdown."""
    logger.info("Shutting down...")

    # Stop the job queue first
    try:
        await bot_app.job_queue.stop()
        logger.info("Job queue stopped successfully")
    except asyncio.CancelledError:
        logger.info("Job queue stop cancelled during shutdown")
    except Exception as e:
        logger.warning(f"Error stopping job queue: {e}")

    # Enhanced memory monitoring to prevent Render restarts - cleanup resources
    try:
        await cleanup_resources()
    except asyncio.CancelledError:
        logger.info("Resource cleanup cancelled during shutdown")
    except Exception as e:
        logger.warning(f"Error during resource cleanup: {e}")

    # Delete webhook if configured
    if os.getenv("WEBHOOK_URL"):
        try:
            await bot_app.bot.delete_webhook()
            logger.info("Webhook deleted successfully")
        except asyncio.CancelledError:
            logger.info("Webhook deletion cancelled during shutdown")
        except Exception as e:
            logger.warning(f"Error deleting webhook: {e}")

    logger.info("Shutdown complete")

if __name__ == "__main__":
    # This block is for local development with polling
    # To run: python -m avap_bot.bot
    try:
        asyncio.run(main_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}", exc_info=True)