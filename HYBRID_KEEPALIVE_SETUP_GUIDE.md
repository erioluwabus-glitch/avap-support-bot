# Hybrid Keep-Alive Setup Guide

## ✅ Phase 1 Complete: Internal Keep-Alive Fixed

The code changes have been successfully implemented and deployed to GitHub. Render will automatically deploy the new version.

## 🔧 Phase 2: External Pinger Setup (Manual Steps Required)

### Step 1: Add Environment Variable in Render Dashboard

1. **Go to your Render Dashboard**: https://dashboard.render.com
2. **Navigate to your bot service** (avap-support-bot)
3. **Click on "Environment" tab**
4. **Add new environment variable**:
   - **Key**: `RENDER_URL`
   - **Value**: `https://avap-support-bot-93z2.onrender.com`
5. **Click "Save Changes"**
6. **Restart the service** to pick up the new environment variable

### Step 2: Primary External Pinger - Pulsetic

1. **Go to Pulsetic**: https://pulsetic.com
2. **Sign up for free account** (no credit card required)
3. **Click "Add Monitor"**
4. **Configure the monitor**:
   - **Name**: `AVAP Bot Keep-Alive`
   - **Type**: `HTTP/HTTPS`
   - **URL**: `https://avap-support-bot-93z2.onrender.com/health`
   - **Check interval**: `Every 10 minutes`
   - **Timeout**: `30 seconds`
   - **Expected status**: `200`
   - **Regions**: Select multiple regions (US, EU, Asia)
5. **Click "Save"**
6. **Verify the first ping succeeds** (should show green status)

### Step 3: Backup External Pinger - Cron-Job.org

1. **Go to Cron-Job.org**: https://cron-job.org
2. **Sign up for free account**
3. **Create new cron job**:
   - **Title**: `AVAP Bot Backup Ping`
   - **URL**: `https://avap-support-bot-93z2.onrender.com/ping`
   - **Schedule**: `*/10 * * * *` (every 10 minutes)
   - **Enabled**: `Yes`
   - **Timezone**: Your local timezone
4. **Click "Save"**
5. **Test the job** by clicking "Run now"

### Step 4: Optional Third Layer - Better Stack

1. **Go to Better Stack**: https://betterstack.com/uptime
2. **Sign up for free account** (3 monitors free)
3. **Add monitor**:
   - **URL**: `https://avap-support-bot-93z2.onrender.com/health`
   - **Interval**: `10 minutes`
   - **Alert on downtime**: `Yes` (email notifications)
   - **Regions**: Multiple regions
4. **Save and verify**

## 🔍 Phase 3: Testing and Validation

### Immediate Testing (Next 30 minutes):

1. **Wait for Render deployment** (check Render logs for "Deploy successful")
2. **Run the monitoring script**:
   ```bash
   python monitor_keepalive.py
   ```
3. **Check Render logs** for:
   - `"Self-ping successful - service kept awake"` messages every 12 minutes
   - No 429 rate limit errors
   - No SIGTERM conflicts
4. **Test external pingers**:
   - Pulsetic should show green status
   - Cron-Job.org should show successful runs
5. **Send a Telegram message** to your bot - should respond instantly

### 24-Hour Validation:

1. **Monitor for 24 hours** without manual interaction
2. **Send Telegram messages** at random times - should always respond instantly
3. **Check Render metrics**:
   - Service should show continuous uptime
   - No "service spinning up" delays
4. **Monitor resource usage**:
   - Instance hours should stay under 750/month
   - Bandwidth should stay under 100GB/month

## 📊 Expected Results

### Traffic Analysis:
- **Internal pings**: ~4,320 requests/month (every 12 minutes)
- **External pings**: ~8,640 requests/month (every 10 minutes from 2 services)
- **Total**: ~12,960 requests/month (well within free tier limits)

### Redundancy Layers:
1. **Internal self-ping**: Every 12 minutes (backup)
2. **Pulsetic**: Every 10 minutes (primary external)
3. **Cron-Job.org**: Every 10 minutes (backup external)
4. **Better Stack**: Every 10 minutes (optional third layer)

## 🚨 Troubleshooting Guide

### If Service Still Sleeps:
1. Check Render logs for ping failures
2. Verify `RENDER_URL` environment variable is set correctly
3. Confirm external pingers show successful pings
4. Check if rate limiting is blocking pings

### If Suspended for Traffic:
1. Disable internal keep-alive (comment out `background_keepalive` task)
2. Rely only on external pingers
3. Contact Render support to explain it's a low-traffic bot

### If External Pingers Fail:
1. Verify URLs are correct and accessible
2. Check if health endpoint returns 200
3. Try different pinger service
4. Ensure no authentication blocking external requests

## ✅ Success Criteria

- ✅ Bot responds instantly to Telegram messages 24/7
- ✅ No "service spinning up" delays
- ✅ Render logs show consistent uptime
- ✅ No suspension warnings
- ✅ Resource usage stays within free tier limits

## 🎯 Next Steps

1. **Complete the external pinger setup** (Steps 1-4 above)
2. **Run the monitoring script** to verify endpoints
3. **Test for 24 hours** to confirm 24/7 uptime
4. **Monitor resource usage** to avoid suspension

The hybrid keep-alive system is now implemented! The combination of internal self-pinging (every 12 minutes) + external pingers (every 10 minutes) provides maximum reliability with minimal suspension risk.
