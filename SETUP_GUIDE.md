# AVAP Support Bot Setup Guide

## Prerequisites

1. **Telegram Bot**: Create a bot with @BotFather
2. **Supabase**: Create a free account and project
3. **Google Sheets**: Create a spreadsheet for data backup
4. **Render**: For hosting (free tier available)
5. **OpenAI API**: For AI features (optional)
6. **Hugging Face**: For AI features (optional)

## Environment Variables

Create a `.env` file with the following variables:

```bash
# Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_USER_ID=your_telegram_user_id_here

# Group IDs (get from @userinfobot)
SUPPORT_GROUP_ID=-1001234567890
VERIFICATION_GROUP_ID=-1001234567891
ASSIGNMENT_GROUP_ID=-1001234567892
QUESTIONS_GROUP_ID=-1001234567893

# Database Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS_FILE=path/to/credentials.json
GOOGLE_SHEETS_ID=your_google_sheets_id

# Systeme.io Configuration (optional)
SYSTEME_API_KEY=your_systeme_api_key
SYSTEME_TAG_ID=your_verified_tag_id

# AI Services
OPENAI_API_KEY=your_openai_api_key
HUGGINGFACE_TOKEN=your_huggingface_token

# Landing Page
LANDING_PAGE_URL=https://your-course-landing-page.com

# Render Configuration
RENDER_EXTERNAL_URL=https://your-app-name.onrender.com
AUTO_SET_WEBHOOK=true

# Logging
LOG_LEVEL=INFO
```

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

## Troubleshooting

1. **Bot not responding**: Check webhook URL and bot token
2. **Database errors**: Verify Supabase credentials and schema
3. **Sheets errors**: Check service account permissions
4. **AI features not working**: Verify API keys

## Support

For issues or questions, check the logs in Render dashboard or contact the admin.
