#!/bin/bash
# Test admin endpoints with proper authentication

# Configuration
BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_TOKEN="${ADMIN_RESET_TOKEN:-your_admin_token_here}"

echo "Testing admin endpoints with token: ${ADMIN_TOKEN:0:8}..."

# Test admin stats endpoint
echo "1. Testing admin stats endpoint..."
curl -X GET "${BASE_URL}/admin/stats" \
  -H "X-Admin-Reset-Token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo -e "\n"

# Test purge email endpoint
echo "2. Testing purge email endpoint..."
curl -X POST "${BASE_URL}/admin/purge/email" \
  -H "X-Admin-Reset-Token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}' \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo -e "\n"

# Test purge all pending endpoint
echo "3. Testing purge all pending endpoint..."
curl -X POST "${BASE_URL}/admin/purge/pending" \
  -H "X-Admin-Reset-Token: ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo -e "\n"

# Test unauthorized access (should fail)
echo "4. Testing unauthorized access (should return 403)..."
curl -X GET "${BASE_URL}/admin/stats" \
  -H "Content-Type: application/json" \
  -w "\nHTTP Status: %{http_code}\n" \
  -s

echo -e "\nAdmin endpoint tests completed"