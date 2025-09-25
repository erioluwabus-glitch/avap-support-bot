#!/bin/bash

# Test webhook endpoint
# Usage: ./test_webhook.sh <BOT_TOKEN> <WEBHOOK_URL>

set -e

BOT_TOKEN="$1"
WEBHOOK_URL="$2"

if [ -z "$BOT_TOKEN" ] || [ -z "$WEBHOOK_URL" ]; then
    echo "Usage: $0 <BOT_TOKEN> <WEBHOOK_URL>"
    echo "Example: $0 123456789:ABCdefGHIjklMNOpqrsTUVwxyz https://your-app.onrender.com/webhook/123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    exit 1
fi

echo "🧪 Testing webhook endpoint..."

# Test webhook with sample update
curl -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $BOT_TOKEN" \
  -d '{
    "update_id": 123456789,
    "message": {
      "message_id": 1,
      "from": {
        "id": 123456789,
        "is_bot": false,
        "first_name": "Test",
        "username": "testuser"
      },
      "chat": {
        "id": 123456789,
        "first_name": "Test",
        "username": "testuser",
        "type": "private"
      },
      "date": 1640995200,
      "text": "/start"
    }
  }' \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo "✅ Webhook test completed"
