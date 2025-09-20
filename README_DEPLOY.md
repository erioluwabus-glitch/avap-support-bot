# AVAP Telegram Bot - Render Deployment Guide

This guide provides step-by-step instructions for deploying the AVAP Telegram Bot to Render with webhook mode.

## Prerequisites

1. **GitHub Repository**: Code must be pushed to a GitHub repository
2. **Render Account**: Sign up at [render.com](https://render.com)
3. **Telegram Bot Token**: Get from [@BotFather](https://t.me/BotFather)
4. **Google Sheets Setup** (Optional): Service account credentials
5. **Systeme.io Account** (Optional): API key and tag ID

## Environment Variables

Set these environment variables in your Render service:

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `BOT_TOKEN` | Telegram bot token from BotFather | `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz` |
| `ADMIN_USER_ID` | Your Telegram user ID (integer) | `123456789` |
| `RENDER_EXTERNAL_URL` | Your Render app URL | `avap-support-bot.onrender.com` |

### Optional Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `GOOGLE_SHEET_ID` | Google Sheets spreadsheet ID | - | `1ABCdefGHIjklMNOpqrsTUVwxyz1234567890` |
| `GOOGLE_CREDENTIALS_JSON` | Google service account JSON | - | `{"type": "service_account", ...}` |
| `SYSTEME_IO_API_KEY` | Systeme.io API key | - | `sk_1234567890abcdef` |
| `SYSTEME_VERIFIED_STUDENT_TAG_ID` | Systeme.io tag ID for verified students | - | `12345` |
| `SUPPORT_GROUP_ID` | Telegram support group ID | - | `-1001234567890` |
| `ASSIGNMENTS_GROUP_ID` | Telegram assignments group ID | - | `-1001234567891` |
| `QUESTIONS_GROUP_ID` | Telegram questions group ID | - | `-1001234567892` |
| `VERIFICATION_GROUP_ID` | Telegram verification group ID | - | `-1001234567893` |
| `DB_PATH` | Database file path | `./bot.db` | `./bot.db` |
| `ACHIEVER_MODULES` | Modules required for Achiever badge | `6` | `6` |
| `ACHIEVER_WINS` | Wins required for Achiever badge | `3` | `3` |
| `TIMEZONE` | Timezone for scheduler | `Africa/Lagos` | `Africa/Lagos` |

## Deployment Steps

### 1. Create New Web Service

1. Go to your [Render Dashboard](https://dashboard.render.com)
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Select the repository containing the bot code

### 2. Configure the Service

**Basic Settings:**
- **Name**: `avap-support-bot` (or your preferred name)
- **Region**: Choose closest to your users
- **Branch**: `main` (or your deployment branch)
- **Runtime**: `Python 3`

**Build & Deploy:**
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python bot.py`

### 3. Set Environment Variables

1. Go to "Environment" tab in your service settings
2. Add each environment variable listed above
3. **Important**: Set `RENDER_EXTERNAL_URL` to your app's URL (e.g., `avap-support-bot.onrender.com`)

### 4. Deploy

1. Click "Create Web Service"
2. Wait for build to complete (2-3 minutes)
3. Check logs for successful startup

## Verification

### 1. Check Health Endpoint

```bash
curl https://your-app-name.onrender.com/health
```

Expected response:
```json
{"status": "ok"}
```

### 2. Check Root Endpoint

```bash
curl https://your-app-name.onrender.com/
```

Expected response:
```json
{"message": "AVAP Bot running"}
```

### 3. Check Startup Logs

Look for these log messages:
- ✅ "Google Sheets connected" (if configured)
- ✅ "Webhook set successfully"
- ✅ "Scheduler started"
- ✅ "Application initialized and started"

### 4. Test Bot Functionality

1. Start a conversation with your bot
2. Send `/start` command
3. Verify bot responds correctly

## Database Persistence

### Option 1: Render Free Disk (Recommended)

1. Go to "Disks" in your Render dashboard
2. Create a new disk:
   - **Name**: `avap-bot-data`
   - **Mount Path**: `/data`
   - **Size**: 1 GB
3. Attach the disk to your web service
4. Update `DB_PATH` environment variable to `/data/bot.db`

### Option 2: External Database

Consider using PostgreSQL for production:
1. Create a Render PostgreSQL database
2. Update the code to use PostgreSQL instead of SQLite
3. Set database connection environment variables

## Monitoring

### 1. Health Checks

Render automatically monitors your service health via the `/health` endpoint.

### 2. Logs

- View logs in the Render dashboard
- Monitor for errors and performance issues
- Set up log alerts if needed

### 3. Metrics

- Monitor CPU and memory usage
- Check response times
- Monitor webhook delivery success

## Troubleshooting

### Common Issues

#### 1. Webhook Not Setting

**Symptoms**: Bot doesn't receive messages
**Solutions**:
- Check `RENDER_EXTERNAL_URL` is correct
- Verify bot token is valid
- Check for 409 Conflict errors in logs
- Manually set webhook: `https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-app.onrender.com/webhook/<TOKEN>`

#### 2. Database Errors

**Symptoms**: Bot crashes or data not persisting
**Solutions**:
- Check `DB_PATH` permissions
- Verify disk is attached and mounted
- Check disk space

#### 3. Google Sheets Errors

**Symptoms**: Data not syncing to sheets
**Solutions**:
- Verify `GOOGLE_CREDENTIALS_JSON` format
- Check sheet permissions
- Verify `GOOGLE_SHEET_ID` is correct

#### 4. Systeme.io Errors

**Symptoms**: Contacts not created
**Solutions**:
- Verify `SYSTEME_IO_API_KEY` is valid
- Check `SYSTEME_VERIFIED_STUDENT_TAG_ID` exists
- Verify API permissions

### Debug Commands

```bash
# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Delete webhook (if needed)
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"

# Set webhook manually
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-app.onrender.com/webhook/<TOKEN>"
```

## Security Considerations

### 1. Environment Variables

- Never commit sensitive data to git
- Use Render's environment variable system
- Rotate API keys regularly

### 2. Bot Security

- Keep bot token secret
- Use admin-only commands appropriately
- Validate all user inputs

### 3. Database Security

- Use persistent disk for data
- Regular backups
- Monitor access logs

## Scaling

### 1. Performance Optimization

- Monitor resource usage
- Optimize database queries
- Use connection pooling if needed

### 2. Load Balancing

- Consider multiple instances for high traffic
- Use external database for shared state
- Implement proper session management

## Maintenance

### 1. Regular Updates

- Keep dependencies updated
- Monitor security advisories
- Test updates in staging first

### 2. Backup Strategy

- Regular database backups
- Code version control
- Environment variable documentation

### 3. Monitoring

- Set up alerts for failures
- Monitor performance metrics
- Track user engagement

## Rollback Procedure

### 1. Code Rollback

```bash
# Revert to previous commit
git revert <commit-hash>
git push origin main

# Or redeploy previous version
# Use Render's deployment history
```

### 2. Database Rollback

```bash
# Restore from backup
# Copy backup file to /data/bot.db
```

### 3. Configuration Rollback

- Revert environment variable changes
- Redeploy service
- Verify functionality

## Support

### 1. Documentation

- Refer to this guide
- Check bot.py code comments
- Review TEST_PLAN.md

### 2. Logs

- Check Render service logs
- Look for error patterns
- Monitor webhook delivery

### 3. Community

- Telegram Bot API documentation
- Python-telegram-bot documentation
- Render support

## Success Checklist

Before considering deployment complete:

- [ ] All environment variables set correctly
- [ ] Health endpoint responding
- [ ] Webhook set successfully
- [ ] Bot responding to commands
- [ ] Database persisting data
- [ ] Google Sheets syncing (if configured)
- [ ] Systeme.io integration working (if configured)
- [ ] All 11 features tested
- [ ] Error handling working
- [ ] Logs showing no critical errors
- [ ] Performance acceptable
- [ ] Security measures in place

## Next Steps

After successful deployment:

1. **Test all features** using TEST_PLAN.md
2. **Monitor performance** for first 24 hours
3. **Set up alerts** for critical failures
4. **Document any customizations** made
5. **Train users** on bot functionality
6. **Plan maintenance schedule**

---

**Deployment Date**: _________________  
**Deployed By**: _________________  
**Version**: _________________  
**Status**: _________________
