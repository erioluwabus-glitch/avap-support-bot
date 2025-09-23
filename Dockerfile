# Use official Python 3.11 slim image
FROM python:3.11-slim

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy all code
COPY . .

# Expose port
EXPOSE 8000

# Run the bot
CMD ["uvicorn", "avap_bot.bot:app", "--host", "0.0.0.0", "--port", "8000"]
