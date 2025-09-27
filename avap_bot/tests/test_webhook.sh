#!/bin/bash
# Test webhook endpoint with sample Telegram update

# Configuration
BOT_TOKEN="${BOT_TOKEN:-your_bot_token_here}"
BASE_URL="${BASE_URL:-http://localhost:8080}"
WEBHOOK_PATH="/webhook/${BOT_TOKEN}"

echo "Testing webhook endpoint: ${BASE_URL}${WEBHOOK_PATH}"

# Sample Telegram update (simulating /start command)
curl -X POST "${BASE_URL}${WEBHOOK_PATH}" \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 123456789,
    "message": {
      "message_id": 1,
      "date": 1700000000,
      "chat": {
        "id": 123456789,
        "type": "private"
      },
      "from": {
        "id": 123456789,
        "is_bot": false,
        "first_name": "Test",
        "username": "testuser"
      },
      "text": "/start"
    }
  }' \
  -w "\nHTTP Status: %{http_code}\nResponse Time: %{time_total}s\n"

echo "Webhook test completed"