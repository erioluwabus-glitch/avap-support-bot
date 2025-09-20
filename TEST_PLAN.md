# AVAP Telegram Bot - Test Plan

This document outlines comprehensive testing procedures for the AVAP Telegram Bot with all 11 features implemented.

## Prerequisites

1. **Environment Setup**
   - Python 3.13 environment
   - All required environment variables set
   - ngrok for local webhook testing
   - Test Telegram bot token
   - Test admin user ID

2. **Required Environment Variables**
   ```bash
   BOT_TOKEN=your_bot_token
   ADMIN_USER_ID=your_admin_telegram_id
   RENDER_EXTERNAL_URL=your_ngrok_url_or_render_url
   GOOGLE_SHEET_ID=your_google_sheet_id
   GOOGLE_CREDENTIALS_JSON=your_google_credentials_json
   SYSTEME_IO_API_KEY=your_systeme_api_key
   SYSTEME_VERIFIED_STUDENT_TAG_ID=your_tag_id
   SUPPORT_GROUP_ID=your_support_group_id
   ASSIGNMENTS_GROUP_ID=your_assignments_group_id
   QUESTIONS_GROUP_ID=your_questions_group_id
   VERIFICATION_GROUP_ID=your_verification_group_id
   DB_PATH=./bot.db
   ACHIEVER_MODULES=6
   ACHIEVER_WINS=3
   TIMEZONE=Africa/Lagos
   ```

## Local Testing Setup

### 1. Start the Bot Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN=your_bot_token
export ADMIN_USER_ID=your_admin_telegram_id
export RENDER_EXTERNAL_URL=https://your-ngrok-url.ngrok.io
# ... set other variables

# Start the bot
uvicorn bot:app --host 0.0.0.0 --port 8080
```

### 2. Setup ngrok for Webhook Testing

```bash
# Install ngrok if not already installed
# Start ngrok tunnel
ngrok http 8080

# Copy the https URL (e.g., https://abc123.ngrok.io)
# Update RENDER_EXTERNAL_URL with this URL
```

### 3. Verify Webhook Setup

Check the startup logs for:
- "Google Sheets connected" (if configured)
- "Webhook set successfully"
- "Scheduler started"
- "Application initialized and started"

## Feature Testing

### Feature 1: Admin Add Student (/add_student)

**Test Steps:**
1. Admin sends `/add_student` in VERIFICATION_GROUP_ID
2. Follow prompts: name, phone, email
3. Verify student appears in pending_verifications table
4. Verify Google Sheets row added (if configured)

**Expected Results:**
- Student added to pending list
- Confirmation message sent
- Data synced to Google Sheets

### Feature 2: Student Verification (/start)

**Test Steps:**
1. Student DMs bot `/start`
2. Click "Verify Now" button
3. Enter name, phone, email matching admin-added student
4. Verify successful verification

**Expected Results:**
- Student marked as verified
- Main menu displayed
- Systeme.io contact created (if configured)
- Google Sheets updated

### Feature 3: Admin Manual Verification (/verify_student)

**Test Steps:**
1. Admin sends `/verify_student student@email.com`
2. Verify student marked as verified
3. Check Systeme.io integration

**Expected Results:**
- Student verified without Telegram interaction
- Confirmation message sent

### Feature 4: Admin Remove Student (/remove_student)

**Test Steps:**
1. Admin sends `/remove_student 123456789`
2. Verify student removed from verified_users
3. Check status updated to "Removed"

**Expected Results:**
- Student removed from verified list
- Confirmation message sent

### Feature 5: Assignment Submission

**Test Steps:**
1. Verified student DMs bot
2. Click "Submit Assignment" or send module number (1-12)
3. Choose media type (video/image)
4. Send media file
5. Verify submission forwarded to ASSIGNMENTS_GROUP_ID

**Expected Results:**
- Submission stored in database
- Media forwarded to assignments group
- Grade button available for admin

### Feature 6: Grading (Inline & Manual)

**Test Steps:**
1. Admin clicks "Grade" button in ASSIGNMENTS_GROUP_ID
2. Select score (1-10)
3. Choose to add comment or not
4. If comment, send text/audio/video
5. Verify student receives grade and comment

**Expected Results:**
- Score recorded in database
- Comment sent to student
- Grading complete confirmation

### Feature 7: Share Small Win

**Test Steps:**
1. Verified student DMs bot
2. Click "Share Small Win"
3. Choose type (text/image/video)
4. Send content
5. Verify forwarded to SUPPORT_GROUP_ID

**Expected Results:**
- Win stored in database
- Content forwarded to support group
- Confirmation message sent

### Feature 8: Ask Question (Group & DM)

**Test Steps:**
1. **Group**: Verified student sends `/ask What is the deadline?` in group
2. **DM**: Student clicks "Ask a Question" and sends question
3. Verify question forwarded to QUESTIONS_GROUP_ID
4. Admin clicks "Answer" button
5. Admin sends answer
6. Verify student receives answer

**Expected Results:**
- Question stored in database
- Question forwarded to questions group
- Answer sent to student
- Status updated to "Answered"

### Feature 9: Check Status

**Test Steps:**
1. Verified student DMs bot
2. Click "Check Status"
3. Verify progress display
4. Test Achiever badge logic

**Expected Results:**
- Shows completed modules with scores
- Shows win count
- Shows Achiever badge if criteria met

### Feature 10: Join Request Handling

**Test Steps:**
1. Verified user requests to join group
2. Unverified user requests to join group
3. Verify appropriate responses

**Expected Results:**
- Verified users approved automatically
- Unverified users declined with verification prompt

### Feature 11: Sunday Reminder

**Test Steps:**
1. Wait for Sunday 18:00 (or modify scheduler for testing)
2. Verify reminders sent to all verified users

**Expected Results:**
- All verified users receive reminder message
- Message includes status check and win sharing prompts

## FastAPI Endpoint Testing

### Health Check
```bash
curl https://your-app-url/health
# Expected: {"status": "ok"}
```

### Root Endpoint
```bash
curl https://your-app-url/
# Expected: {"message": "AVAP Bot running"}
```

### Webhook Endpoint
```bash
# Test with valid token
curl -X POST https://your-app-url/webhook/your_bot_token \
  -H "Content-Type: application/json" \
  -d '{"update_id": 1, "message": {"message_id": 1, "from": {"id": 123, "first_name": "Test"}, "chat": {"id": 123, "type": "private"}, "date": 1234567890, "text": "/start"}}'

# Test with invalid token
curl -X POST https://your-app-url/webhook/invalid_token
# Expected: 403 Forbidden
```

## Error Handling Tests

### 1. Invalid Environment Variables
- Test with missing BOT_TOKEN
- Test with missing RENDER_EXTERNAL_URL
- Test with missing ADMIN_USER_ID

### 2. Database Errors
- Test with invalid DB_PATH
- Test with permission issues

### 3. API Integration Errors
- Test with invalid Google Sheets credentials
- Test with invalid Systeme.io API key
- Test with network timeouts

### 4. Telegram API Errors
- Test with invalid bot token
- Test with webhook conflicts
- Test with rate limiting

## Performance Tests

### 1. Concurrent Users
- Test multiple users verifying simultaneously
- Test multiple submissions at once
- Test multiple grading operations

### 2. Large Data Sets
- Test with many pending verifications
- Test with many submissions
- Test with many questions

## Security Tests

### 1. Authorization
- Test admin commands with non-admin users
- Test group restrictions
- Test DM-only features

### 2. Input Validation
- Test with malicious input
- Test with oversized messages
- Test with invalid file types

## Deployment Testing

### 1. Render Deployment
1. Push code to GitHub
2. Deploy to Render
3. Verify webhook setup
4. Test all features in production

### 2. Environment Variables
- Verify all required variables set
- Test with production values
- Verify Google Sheets access
- Verify Systeme.io integration

## Rollback Testing

### 1. Database Rollback
```bash
# Backup database before testing
cp bot.db bot.db.backup

# Test rollback procedures
# Restore from backup if needed
```

### 2. Code Rollback
```bash
# Test git revert procedures
git revert <commit-hash>
# Redeploy and verify functionality
```

## Monitoring and Logging

### 1. Log Verification
- Check for proper log levels
- Verify error logging
- Check performance logs

### 2. Health Monitoring
- Monitor /health endpoint
- Check webhook status
- Monitor database connections

## Success Criteria

All tests must pass for successful deployment:

- [ ] All 11 features working correctly
- [ ] Webhook mode functioning
- [ ] Database operations working
- [ ] Google Sheets integration (if configured)
- [ ] Systeme.io integration (if configured)
- [ ] Error handling working
- [ ] Security measures in place
- [ ] Performance acceptable
- [ ] Logging comprehensive
- [ ] Deployment successful

## Troubleshooting

### Common Issues

1. **Webhook not setting**
   - Check RENDER_EXTERNAL_URL format
   - Verify bot token is correct
   - Check for 409 conflicts

2. **Database errors**
   - Check DB_PATH permissions
   - Verify SQLite installation
   - Check disk space

3. **Google Sheets errors**
   - Verify credentials JSON format
   - Check sheet permissions
   - Verify sheet ID

4. **Systeme.io errors**
   - Check API key format
   - Verify tag ID exists
   - Check network connectivity

### Debug Commands

```bash
# Check bot status
curl https://your-app-url/health

# Check logs
# View Render logs or local console output

# Test webhook manually
# Use Telegram's setWebhook API directly
```

## Test Data

### Sample Test Users
- Admin: User ID 123456789
- Student 1: User ID 987654321
- Student 2: User ID 555666777

### Sample Test Data
- Name: "John Doe"
- Email: "john.doe@example.com"
- Phone: "+1234567890"

## Test Schedule

1. **Development Testing**: Continuous during development
2. **Integration Testing**: After each feature completion
3. **System Testing**: Before deployment
4. **User Acceptance Testing**: With actual users
5. **Production Testing**: After deployment

## Sign-off

- [ ] All features tested and working
- [ ] Performance requirements met
- [ ] Security requirements met
- [ ] Documentation complete
- [ ] Ready for production deployment

**Tester**: _________________ **Date**: _________________

**Approver**: _________________ **Date**: _________________
