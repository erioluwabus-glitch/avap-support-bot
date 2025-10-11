# AVAP Support Bot

A comprehensive Telegram bot for managing student verification, assignments, and community features for the AVAP course.

## Features

### 🔐 Admin Verification Features
- **`/addstudent`** - Add new students to the system
- **`/verify`** - Verify students manually or allow self-verification
- **`/remove_student`** - Remove students and revoke access
- **`/grade`** - Grade submitted assignments with scores and comments

### 👨‍🎓 Student Features
- **`/start`** - Initial greeting and verification gate
- **Submit Assignment** - Submit work for grading (text/audio/video)
- **Share Win** - Share successes to motivate peers
- **Check Status** - Track progress and badges
- **Ask Question** - Get help with AI fallback
- **`/match`** - Find study partners

### 🤖 AI Features
- **Daily Tips** - Motivational tips at 8AM WAT
- **FAQ Matching** - Automatic question answering
- **Audio Transcription** - Convert voice to text
- **Smart Responses** - AI-powered support

### 📊 Admin Tools
- **`/add_tip`** - Add manual daily tips
- **`/get_submission`** - Retrieve specific submissions

## Tech Stack

- **Bot Framework**: python-telegram-bot
- **Database**: Supabase (PostgreSQL)
- **Backup**: Google Sheets
- **AI**: Hugging Face + OpenAI
- **Hosting**: Render
- **Scheduling**: APScheduler

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd avap-support-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

4. **Set up database**
   - Run `database_schema.sql` in Supabase
   - Configure Google Sheets

5. **Deploy to Render**
   - Connect GitHub repository
   - Set environment variables
   - Deploy

## Database Schema

The bot uses Supabase with the following tables:
- `pending_verifications` - Students awaiting verification
- `verified_users` - Verified students with access
- `assignments` - Student submissions
- `wins` - Student success stories
- `questions` - Student questions
- `faqs` - FAQ database for AI matching
- `tips` - Daily motivational tips
- `match_requests` - Student pairing system

## Environment Variables

See `SETUP_GUIDE.md` for detailed setup instructions.

## Features in Detail

### Student Verification Flow
1. Admin adds student with `/addstudent`
2. Student self-verifies with `/start` or admin verifies with `/verify`
3. Student gains access to all features
4. Data persists across redeploys

### Assignment System
1. Student submits assignment via inline keyboard
2. Assignment forwarded to grading group
3. Admin grades with score and comments
4. Student receives feedback automatically

### AI Integration
- **Daily Tips**: Generated at 8AM WAT using Hugging Face
- **FAQ Matching**: Semantic search using sentence transformers
- **Question Answering**: AI-powered responses with manual fallback

### Community Features
- **Win Sharing**: Students share successes to motivate others
- **Student Matching**: Pair students for collaboration
- **Progress Tracking**: Badges and status updates

## Security

- **Row Level Security** enabled on all Supabase tables
- **Admin-only commands** protected by user ID checks
- **Verification required** for all student features
- **Unique constraints** prevent duplicate registrations

## Monitoring

- **Error handling** with admin notifications
- **Comprehensive logging** for debugging
- **Health checks** for uptime monitoring
- **Performance metrics** via Prometheus

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues or questions:
1. Check the logs in Render dashboard
2. Review the setup guide
3. Contact the admin team

---

**Built with ❤️ for the AVAP community**
