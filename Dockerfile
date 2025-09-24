FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: FFmpeg (system version) + dev headers for deps
# Add PostgreSQL dev libs for psycopg2-binary/asyncpg fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    build-essential \
    pkg-config \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Help pkg-config locate FFmpeg .pc files
ENV PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH

WORKDIR /app

# Install Python dependencies first (leverage docker layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose Render default port
EXPOSE 10000

# Start the FastAPI webhook app on Render-provided PORT
ENV PORT=10000
CMD ["sh", "-c", "uvicorn avap_bot.bot:app --host 0.0.0.0 --port ${PORT}"]
