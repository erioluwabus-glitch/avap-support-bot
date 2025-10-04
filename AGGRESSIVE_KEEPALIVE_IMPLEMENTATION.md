# Aggressive Keep-Alive Implementation for 24/7 Bot Operation

## Problem
The bot was shutting down after ~16 minutes due to Render's free tier timeout limits, despite having a keep-alive mechanism.

## Solution: Multi-Layer Keep-Alive Strategy

### 1. **Ultra-Frequent Scheduler Tasks**
- **Keep-alive check**: Every 30 seconds (was 1 minute)
- **Simple ping**: Every 15 seconds (new)
- **Background task**: Every 5 seconds (new)

### 2. **Multiple HTTP Endpoints**
- `/ping` - Simple pong response (fastest)
- `/` - Root endpoint with basic status
- `/health` - Comprehensive health check

### 3. **Background Keep-Alive Task**
- Continuously pings all endpoints every 5 seconds
- Uses `asyncio.gather()` for concurrent requests
- Silent failure to avoid log spam

### 4. **Reduced Logging Noise**
- Changed webhook logs from INFO to DEBUG
- Suppressed APScheduler, Uvicorn, and HTTP client logs
- Keep-alive logs use DEBUG level

## Implementation Details

### Modified Files:
1. **`avap_bot/bot.py`** - Main keep-alive implementation
2. **`avap_bot/utils/logging_config.py`** - Reduced logging noise
3. **`keepalive_monitor.py`** - External monitoring script (new)

### Key Features:

#### 1. **Triple-Layer Keep-Alive**
```python
# Layer 1: Scheduler every 30 seconds
scheduler.add_job(keep_alive_check, 'interval', seconds=30)

# Layer 2: Scheduler every 15 seconds  
scheduler.add_job(ping_self, 'interval', seconds=15)

# Layer 3: Background task every 5 seconds
asyncio.create_task(background_keepalive())
```

#### 2. **Multiple Endpoints for Activity**
```python
# Simple ping (fastest response)
@app.get("/ping")
async def ping():
    return {"status": "pong", "timestamp": time.time()}

# Root endpoint
@app.get("/")
async def root():
    return {"status": "ok", "service": "avap-support-bot"}

# Health check (comprehensive)
@app.get("/health")
async def health_check():
    # Full health validation
```

#### 3. **Concurrent Request Strategy**
```python
# Multiple concurrent requests to show heavy activity
await asyncio.gather(
    client.get("http://localhost:8080/ping"),
    client.get("http://localhost:8080/"),
    client.get("http://localhost:8080/health"),
    return_exceptions=True
)
```

#### 4. **Silent Failure Design**
- All keep-alive operations fail silently
- No log spam from failed requests
- Continues running even if some requests fail

## External Monitoring

### Option 1: Use the provided script
```bash
# Edit keepalive_monitor.py to set your bot URL
python keepalive_monitor.py
```

### Option 2: Use external services
- **UptimeRobot**: Monitor `/ping` endpoint every 5 minutes
- **Pingdom**: Monitor `/health` endpoint every 1 minute
- **Cron job**: `curl https://your-bot.onrender.com/ping` every 30 seconds

## Expected Results

### Before:
- Bot shuts down after ~16 minutes
- Keep-alive every 5 minutes (too infrequent)
- Lots of log noise

### After:
- Bot stays alive 24/7
- Multiple keep-alive mechanisms running every 5-30 seconds
- Clean logs with only important information
- Multiple activity indicators to prevent timeouts

## Monitoring

### Check if bot is alive:
```bash
curl https://your-bot.onrender.com/ping
# Should return: {"status": "pong", "timestamp": 1234567890.123}
```

### Check health:
```bash
curl https://your-bot.onrender.com/health
# Should return comprehensive health status
```

## Logs to Watch For

### Good signs:
- `Background keepalive task started`
- `Ultra-aggressive keep-alive health checks scheduled every 30 seconds`
- `Simple ping scheduled every 15 seconds`

### Warning signs:
- `Shutting down` (indicates timeout)
- `Keep-alive check failed` (connection issues)
- No webhook activity for extended periods

## Deployment Notes

1. **Deploy the updated code** - All changes are in the main bot file
2. **Monitor the logs** - Should see much less noise
3. **Test the endpoints** - Verify `/ping` and `/health` work
4. **Set up external monitoring** - Use the provided script or external service

## Status: ✅ IMPLEMENTED

The bot now has multiple layers of keep-alive protection and should stay online 24/7 even on Render's free tier.
