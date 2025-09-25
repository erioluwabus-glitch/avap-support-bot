#!/bin/bash

# Test admin endpoints
# Usage: ./check_admin_endpoints.sh <BASE_URL> <ADMIN_RESET_TOKEN>

set -e

BASE_URL="$1"
ADMIN_RESET_TOKEN="$2"

if [ -z "$BASE_URL" ] || [ -z "$ADMIN_RESET_TOKEN" ]; then
    echo "Usage: $0 <BASE_URL> <ADMIN_RESET_TOKEN>"
    echo "Example: $0 https://your-app.onrender.com your-secret-token"
    exit 1
fi

echo "🧪 Testing admin endpoints..."

# Test health endpoint
echo "Testing health endpoint..."
curl -X GET "$BASE_URL/health" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo ""

# Test admin stats (should require auth)
echo "Testing admin stats (should require auth)..."
curl -X GET "$BASE_URL/admin/stats" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo ""

# Test admin stats with auth
echo "Testing admin stats with auth..."
curl -X GET "$BASE_URL/admin/stats" \
  -H "X-Admin-Reset-Token: $ADMIN_RESET_TOKEN" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo ""

# Test purge email endpoint
echo "Testing purge email endpoint..."
curl -X POST "$BASE_URL/admin/purge/email" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Reset-Token: $ADMIN_RESET_TOKEN" \
  -d '{"email": "test@example.com"}' \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo ""

# Test purge pending endpoint
echo "Testing purge pending endpoint..."
curl -X POST "$BASE_URL/admin/purge/pending" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Reset-Token: $ADMIN_RESET_TOKEN" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo "✅ Admin endpoints test completed"
