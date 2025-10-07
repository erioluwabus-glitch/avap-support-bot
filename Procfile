web: gunicorn -k uvicorn.workers.UvicornWorker avap_bot.bot:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 60
