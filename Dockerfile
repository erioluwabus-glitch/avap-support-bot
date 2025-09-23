FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: FFmpeg + development headers for PyAV (faster-whisper dependency)
# Also install build-essential and pkg-config for compiling wheels when needed
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
    && rm -rf /var/lib/apt/lists/*

# Help pkg-config locate FFmpeg .pc files in some environments
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

# Start the FastAPI webhook app (bot.py reads $PORT)
CMD ["python", "bot.py"]


