#!/usr/bin/env bash
# ping_with_jitter.sh
# expects HEALTH_TOKEN env var present on the cron host
# random sleep to jitter and avoid aligning with internal jobs
sleep $((RANDOM % 60))

HEALTH_TOKEN="${HEALTH_TOKEN:-}"
URL="https://your-app.onrender.com/health"

if [ -z "$HEALTH_TOKEN" ]; then
  echo "HEALTH_TOKEN not set; exiting"
  exit 1
fi

# Use HEAD to be light-weight (-I)
curl -s -I -m 8 -H "X-Health-Token: $HEALTH_TOKEN" "$URL" >/dev/null
STATUS=$?
if [ $STATUS -ne 0 ]; then
  # optional: log to file or alert mechanism
  echo "$(date -Iseconds) ping failed (curl exit $STATUS)" >> /var/log/health_ping.log
fi
