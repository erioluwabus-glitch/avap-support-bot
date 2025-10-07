web: gunicorn -k uvicorn.workers.UvicornWorker avap_bot.bot:app --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 30 --max-requests 100 --max-requests-jitter 10
