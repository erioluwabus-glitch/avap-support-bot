FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install FFmpeg 5.x (compatible with av 10.0.0) + dev headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:savoury1/ffmpeg5 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg=7:5.1.3-0ubuntu1~ppa1~22.04 \
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

# Start the FastAPI webhook app
CMD ["uvicorn", "avap_bot.bot:app", "--host", "0.0.0.0", "--port", "10000"]
