# AVAP Bot - New Engagement Features

This document describes the 6 new engagement features added to the AVAP Telegram bot.

## Features Overview

### 1. Daily Tips / Inspiration
- **Command**: `/add_tip <tip text>` (admin only)
- **Schedule**: Posts daily at 08:00 WAT to support group
- **Optional**: Can also DM verified users if `DAILY_TIPS_TO_DMS=true`
- **Database**: Stores tips in `daily_tips` table
- **Fallback**: Uses predefined tips if database is empty

### 2. AI-powered FAQ Helper
- **Command**: `/ask <question>` (works in groups and DMs)
- **Auto-response**: If unanswered for `UNANSWER_TIMEOUT_HOURS` (default 6), generates AI draft
- **Integration**: Uses OpenAI GPT-3.5-turbo for answer suggestions
- **Database**: Tracks questions in `asked_questions` table
- **Workflow**: Question → Group → AI Draft → Admin Review → Student Answer

### 3. Broadcast Messages
- **Command**: `/broadcast <message>` (admin only)
- **Target**: All verified users via DM
- **Features**: 
  - Rate limiting to avoid Telegram 429 errors
  - Translation to user's preferred language
  - Detailed success/failure report
- **Throttling**: 0.2s delay between messages

### 4. Multi-language Support
- **Commands**: 
  - `/setlang <language_code>` - Set language preference
  - `/getlang` - Show current language
- **Translation**: All outgoing messages translated to user's language
- **Languages**: 40+ supported languages via Google Translate
- **Caching**: Translation results cached to avoid repeated API calls
- **Database**: Stores language preference in `verified_users.language`

### 5. Voice Note Transcription
- **Trigger**: Voice messages in private chats
- **Processing**: Downloads and transcribes using OpenAI Whisper API
- **Response**: Returns transcribed text to user
- **Integration**: Can save transcriptions to Google Sheets
- **Error Handling**: Graceful fallback on transcription failures

### 6. Study Groups Matching
- **Command**: `/match` (DM only)
- **Process**: Adds user to match queue, pairs when enough students
- **Admin Commands**:
  - `/match_status` - View queue statistics
  - `/force_match` - Force immediate matching
- **Configuration**: `MATCH_SIZE` environment variable (default 2 for pairs)
- **Database**: Tracks matches in `match_queue` table
- **Notifications**: Sends match details to all group members

## Environment Variables

### Required
- `BOT_TOKEN` - Telegram bot token
- `ADMIN_IDS` - Comma-separated admin user IDs
- `SUPPORT_GROUP_ID` - Group for daily tips and questions
- `ASSIGNMENTS_GROUP_ID` - Group for assignment submissions
- `QUESTIONS_GROUP_ID` - Group for student questions
- `VERIFICATION_GROUP_ID` - Group for verification flow
- `GOOGLE_SHEET_ID` - Google Sheets integration
- `SYSTEME_API_KEY` - Systeme.io API key
- `SYSTEME_VERIFIED_STUDENT_TAG_ID` - Tag ID for verified students
- `OPENAI_API_KEY` - OpenAI API key for AI features

### Optional
- `UNANSWER_TIMEOUT_HOURS` - Hours before AI generates answer (default: 6)
- `DAILY_TIP_HOUR` - Hour for daily tips in WAT (default: 8)
- `DEFAULT_LANGUAGE` - Default language code (default: en)
- `DAILY_TIPS_TO_DMS` - Send tips to user DMs (default: false)
- `MATCH_SIZE` - Size of study groups (default: 2)
- `WHISPER_ENDPOINT` - Custom Whisper endpoint (optional)

## Database Schema

### New Tables
```sql
-- Asked questions tracking
CREATE TABLE asked_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT UNIQUE,
    telegram_id INTEGER,
    username TEXT,
    question TEXT,
    answered INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily tips storage
CREATE TABLE daily_tips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tip TEXT NOT NULL
);

-- Study group matching queue
CREATE TABLE match_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Updated Tables
```sql
-- Added language preference
ALTER TABLE verified_users ADD COLUMN language TEXT DEFAULT 'en';
```

## File Structure

```
features/
├── daily_tips.py          # Daily tips feature
├── faq_ai_helper.py       # AI FAQ helper
├── broadcast.py           # Broadcast messages
├── multilanguage.py       # Multi-language support
├── voice_transcription.py # Voice transcription
└── group_matching.py      # Study group matching

utils/
├── db_access.py           # Database utilities
├── translator.py          # Translation utilities
├── openai_client.py       # OpenAI API client
├── scheduling.py          # APScheduler utilities
└── matching.py            # Matching algorithms

tests/
├── test_translator.py     # Translation tests
├── test_openai_client.py  # OpenAI client tests
├── test_matching.py       # Matching algorithm tests
└── test_daily_tips.py     # Daily tips tests
```

## Testing

### Unit Tests
Run tests with:
```bash
python -m pytest tests/
```

### Manual Test Plan

#### Daily Tips
1. Admin adds tip: `/add_tip "Test tip"`
2. Wait for scheduled time or trigger manually
3. Verify tip appears in support group
4. Check DM delivery if enabled

#### AI FAQ Helper
1. Student asks question: `/ask "How do I study?"`
2. Verify question appears in questions group
3. Wait for timeout period
4. Check AI draft generation
5. Test admin answer flow

#### Broadcast
1. Admin broadcasts: `/broadcast "Test message"`
2. Verify delivery to verified users
3. Check translation for non-English users
4. Review success/failure report

#### Multi-language
1. User sets language: `/setlang es`
2. Send various bot messages
3. Verify translation to Spanish
4. Test language switching

#### Voice Transcription
1. Send voice message to bot in DM
2. Verify transcription response
3. Test with different languages
4. Check error handling

#### Study Matching
1. Multiple users send `/match`
2. Verify queue status with `/match_status`
3. Check automatic pairing
4. Test manual matching with `/force_match`

## Error Handling

- All network calls wrapped in try/catch
- Fatal errors sent to admin IDs
- Rate limiting for broadcast messages
- Graceful fallbacks for AI features
- Database transaction safety

## Performance Considerations

- Translation caching to reduce API calls
- Rate limiting to avoid Telegram limits
- Async processing for all operations
- Database connection pooling
- Efficient queue management for matching

## Security

- Admin-only commands check `ADMIN_IDS`
- Private chat restrictions for student features
- Input validation and sanitization
- Secure API key handling
- Database query parameterization
