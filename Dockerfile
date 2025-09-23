FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: PostgreSQL dev libs for asyncpg/psycopg2-binary
# Note: FFmpeg deps removed since av/faster-whisper are not used (OpenAI handles voice)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (leverage docker layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose Render default port
EXPOSE 10000

# Start the FastAPI webhook app
CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "10000"]
