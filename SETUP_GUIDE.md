# AVAP Support Bot Setup Guide

## 🚨 CRITICAL FIXES APPLIED - October 5, 2025

**Fixed Issues:**
- ✅ Added persistent CSV storage (no more ephemeral /tmp directory)
- ✅ Updated render.yaml with all required environment variables
- ✅ Fixed database schema migration script
- ✅ Improved error handling for missing credentials
- ❌ **Google Sheets** - Still needs credentials configuration
- ❌ **Systeme.io** - Still needs API key configuration

## Prerequisites

1. **Telegram Bot**: Create a bot with @BotFather
2. **Supabase**: Create a free account and project
3. **Google Sheets**: Create a spreadsheet for data backup
4. **Systeme.io**: Create account and get API key
5. **Render**: For hosting (free tier available)
6. **OpenAI API**: For AI features (optional)

## ⚙️ Environment Variables Setup

### Required for Render Deployment

Set these as **secrets** in your Render dashboard:

#### 🔑 Required Secrets:
```bash
# Bot Configuration
BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
WEBHOOK_URL=https://your-app.onrender.com

# Telegram Group IDs (get from @userinfobot)
ASSIGNMENT_GROUP_ID=your_assignment_group_id
SUPPORT_GROUP_ID=your_support_group_id
VERIFICATION_GROUP_ID=your_verification_group_id
QUESTIONS_GROUP_ID=your_questions_group_id

# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key

# Optional but Recommended
STABLE_BACKUP_DIR=/opt/render/persistent/csv_backup

# Optional Integrations (configure if needed)
GOOGLE_CREDENTIALS_JSON=base64_encoded_service_account_json
GOOGLE_SHEET_ID=your_google_sheet_id_here
SYSTEME_API_KEY=your_systeme_api_key_here
SYSTEME_ACHIEVER_TAG_ID=your_achiever_tag_id_here
```

#### 🔧 How to Get Each Secret:

**1. Google Sheets:**
- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Create service account → Generate JSON key
- Base64 encode: `cat credentials.json | base64 -w 0`
- Get Sheet ID from URL: `https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit`

**2. Systeme.io:**
- Login to Systeme.io → Account Settings → API
- Generate API key (starts with `sk_` or `pk_`)
- Get tag ID from Tags section

**3. Supabase:**
- Project Settings → API → URL and anon/public key

**4. Telegram Bot & Groups:**
- Message @BotFather → Create bot → Copy token
- Message @userinfobot → Add to groups → Copy group IDs (-100xxxxxxxxx format)

## Database Setup

1. **Run the SQL schema**: Execute `database_schema.sql` in your Supabase SQL editor
2. **Enable RLS**: Row Level Security is already configured
3. **Test connection**: The bot will test the connection on startup

## Google Sheets Setup

1. **Create a spreadsheet** with the following tabs:
   - `Verification` - For pending/verified students
   - `Contacts` - For Systeme.io integration
   - `Assignments` - For assignment submissions
   - `Wins` - For student wins
   - `Questions` - For student questions
   - `Tips` - For daily tips

2. **Set up service account**:
   - Go to Google Cloud Console
   - Create a service account
   - Download credentials JSON
   - Share the spreadsheet with the service account email

## Deployment

1. **Deploy to Render**:
   - Connect your GitHub repository
   - Set environment variables
   - Deploy

2. **Set webhook**:
   - The bot will automatically set the webhook on startup
   - Or manually set it: `https://your-app.onrender.com/webhook/YOUR_BOT_TOKEN`

## Testing

1. **Test admin commands**:
   - `/addstudent` - Add a new student
   - `/verify` - Verify a student
   - `/remove_student` - Remove a student

2. **Test student features**:
   - `/start` - Start the bot
   - Submit assignments
   - Share wins
   - Ask questions

3. **Test AI features**:
   - Daily tips (scheduled at 8AM WAT)
   - FAQ matching
   - Question answering

## Features Overview

### Admin Features
- `/addstudent` - Add new students
- `/verify` - Verify students manually
- `/remove_student` - Remove students
- `/grade` - Grade assignments
- `/list_achievers` - List top students
- `/broadcast` - Broadcast to all students
- `/add_tip` - Add manual tips

### Student Features
- `/start` - Start and verify
- Submit assignments
- Share wins
- Check status
- Ask questions
- `/match` - Find study partners

### AI Features
- Daily motivational tips
- FAQ matching
- Question answering
- Audio transcription

## 🔍 Current Issues & Solutions

### ❌ Google Sheets Not Working
**Error:** `credentials.json file not found and GOOGLE_CREDENTIALS_JSON not set`

**Solution:**
1. Set `GOOGLE_CREDENTIALS_JSON` with base64-encoded service account JSON
2. Set `GOOGLE_SHEET_ID` with your sheet ID
3. Ensure service account has edit access to the sheet

### ❌ Systeme.io Not Working
**Error:** `Full authentication is required to access this resource`

**Solution:**
1. Set `SYSTEME_API_KEY` with valid API key from Systeme.io
2. Verify API key starts with `sk_` or `pk_`
3. Check API permissions in Systeme.io dashboard

### ⚠️ Database Schema Issues
**Error:** `Status column not found, inserting without status field`

**Solution:**
1. Run `database_migration.sql` in your Supabase SQL editor
2. This adds missing columns: status, username, comment, tip_type

## 🛠️ General Troubleshooting

1. **Bot not responding**: Check webhook URL and bot token
2. **CSV fallback active**: Google Sheets not configured - set credentials
3. **Systeme.io auth errors**: Verify API key format and permissions
4. **Database errors**: Run migration script and verify credentials

## Support

For issues or questions, check the logs in Render dashboard or contact the admin.
