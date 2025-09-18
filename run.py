# --- Run the bot with proper error handling ---
def run_bot():
    """Run the bot with automatic retries."""
    max_retries = 3
    retry_delay = 5  # seconds
    
    # Set higher timeout for uvicorn
    if os.getenv("RENDER") == "true":
        os.environ["UVICORN_TIMEOUT"] = "60"
    
    for attempt in range(max_retries):
        try:
            application = (
                Application.builder()
                .token(TELEGRAM_TOKEN)
                .connect_timeout(30.0)
                .read_timeout(30.0)
                .write_timeout(30.0)
                .pool_timeout(30.0)
                .get_updates_connection_pool_size(100)
                .concurrent_updates(True)
                .build()
            )
            
            add_handlers(application)
            logger.info("Starting bot...")
            
            is_render = os.getenv("RENDER") == "true"
            if is_render:
                # Webhook mode for Render
                fastapi_app = FastAPI()
                
                @fastapi_app.get("/")
                async def root():
                    return {"message": "AVAP Support Bot is active! Interact via Telegram."}
                    
                @fastapi_app.get("/health")
                async def health():
                    return "OK"
                    
                WEBHOOK_PATH = "/webhook"
                
                @fastapi_app.post(WEBHOOK_PATH)
                async def telegram_webhook(request: Request):
                    update_json = await request.json()
                    if update_json:
                        update = Update.de_json(update_json, application.bot)
                        await application.process_update(update)
                    return Response(status_code=200)
                
                port = int(os.environ.get("PORT", 10000))
                base_url = os.getenv("WEBHOOK_BASE_URL", f"http://localhost:{port}")
                webhook_url = f"{base_url}{WEBHOOK_PATH}"
                
                logger.info("Running in webhook mode on Render.")
                application.run_webhook(
                    listen="0.0.0.0",
                    port=port,
                    webhook_url=webhook_url,
                    drop_pending_updates=True
                )
            else:
                # Polling mode for local development
                logger.info("Running in polling mode locally.")
                application.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES
                )
            break  # If we get here, bot started successfully
            
        except TimedOut:
            if attempt < max_retries - 1:
                logger.warning(f"Connection timed out. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                continue
            else:
                logger.error("Failed to start bot after multiple retries.")
                raise
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            if 'application' in locals():
                application.stop()
            sys.exit(0)
        except Exception as e:
            logger.error(f"Bot error: {e}", exc_info=True)
            if 'application' in locals():
                application.stop()
            raise

if __name__ == "__main__":
    run_bot()