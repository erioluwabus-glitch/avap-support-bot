#!/bin/bash
# AVAP Support Bot Deployment Script for Render

echo "🚀 Starting AVAP Support Bot deployment..."

# Check if we're in the right directory
if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt not found. Please run from project root."
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Run database setup
echo "🗄️ Setting up database..."
python -c "
import os
from avap_bot.services.supabase_service import init_supabase
try:
    init_supabase()
    print('✅ Database connection successful')
except Exception as e:
    print(f'❌ Database connection failed: {e}')
    exit(1)
"

# Run tests
echo "🧪 Running tests..."
python test_bot.py

if [ $? -eq 0 ]; then
    echo "✅ All tests passed!"
else
    echo "❌ Tests failed. Please fix issues before deployment."
    exit 1
fi

# Start the application
echo "🚀 Starting bot application..."
exec uvicorn avap_bot.bot:app --host 0.0.0.0 --port ${PORT:-10000}
