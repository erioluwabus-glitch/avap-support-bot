# 👨‍💼 AVAP Support Bot - Admin User Guide

## Admin Control Center

This guide covers all administrative features and best practices for managing the AVAP Support Bot.

---

## 🔐 Admin Access

### Your Admin Privileges
- Unique admin user ID configured in environment variables
- Access to all admin-only commands
- Control over student verification and removal
- Grading and messaging capabilities

### Admin Groups
You have access to three admin groups:

1. **Verification Group** - Student management (`VERIFICATION_GROUP_ID`)
2. **Assignment Group** - Grading submissions (`ASSIGNMENT_GROUP_ID`)
3. **Questions Group** - Answering student questions (`QUESTIONS_GROUP_ID`)

---

## 👥 Student Management

### 1. Adding Students - `/addstudent`

**Where:** Verification Group only  
**Flow:** Multi-step conversation

**Steps:**
1. Send `/addstudent` in verification group
2. Enter student's full name
3. Enter student's phone number
4. Enter student's email address

**What happens:**
- ✅ Student added to Supabase (persists across redeployments)
- ✅ Added to Google Sheets as "Pending"
- ✅ Added to Systeme.io with "verified" tag
- ✅ Duplicate detection runs automatically
- ✅ Acknowledgment sent to verification group
- ✅ "Verify Now" button appears for instant verification

**Important:**
- Each email and phone can only be used ONCE
- Duplicate attempts are blocked and you're notified
- Students are added as "Pending" until verified

---

### 2. Verifying Students - `/verify`

**Two Methods:**

#### Method A: Student Self-Verification (Recommended)
1. Student sends `/start` to bot
2. Student enters their email or phone
3. Bot automatically verifies if details match
4. Student gains immediate access
5. Support group join request auto-approved

#### Method B: Admin Manual Verification
1. After adding student, click "✅ Verify Now" button
2. Student instantly verified
3. Confirmation sent to verification group
4. Student notified (if they've contacted bot)

**When to use Manual Verification:**
- Testing new student additions
- Student having trouble with self-verification
- Immediate access needed

---

### 3. Removing Students - `/remove_student`

**Where:** Verification Group only  
**Flow:** Search → Confirm → Remove

**Steps:**
1. Send `/remove_student`
2. Enter identifier (email, phone, or full name)
3. Review student details
4. Click "🗑️ REMOVE" or "❌ CANCEL"

**What happens on removal:**
- ❌ Removed from Supabase
- ❌ Removed from Systeme.io
- ❌ Banned from support group
- ❌ Google Sheets status updated to "Removed"
- ❌ Bot access revoked (inline keyboards disappear)
- 📋 Confirmation sent to verification group
- ⚠️ Manual prompt to revoke course access

**Important:**
- This action is destructive but reversible (you can re-add)
- Student loses all bot access immediately
- Remember to manually revoke their course access

---

## 📝 Assignment Grading

### Grading Flow - `/grade`

**Where:** Assignment Group only  
**Trigger:** Reply to a forwarded assignment

**Steps:**
1. Student submits assignment → forwarded to assignment group
2. Reply to the assignment message
3. Send `/grade`
4. Select grade (1-10) from inline buttons
5. Choose to add comments or not

**Assignment Message Contains:**
- Student username
- Telegram ID
- Module number
- Submission type (Text/Audio/Video)
- File ID (if applicable)

**Grading Options:**
- **Grades:** 1-10 scale
- **Comments:** Optional
  - Text comment
  - Audio comment  
  - Video comment
  - No comment

**What happens after grading:**
- ✅ Google Sheets updated (status: "Graded")
- ✅ Grade and comments saved
- ✅ Student notified via DM
- ✅ Confirmation in assignment group

**Student receives:**
- Module number
- Grade (X/10)
- Your comments (text or file)

---

## ❓ Answering Questions

### Answer Flow - `/answer` (via button)

**Where:** Questions Group  
**Trigger:** Click "💬 Answer" button on question

**Steps:**
1. Question forwarded to questions group
2. Click "💬 Answer" button
3. Send your answer (text, audio, or video)
4. Answer automatically sent to student

**Question Message Contains:**
- Student username
- Telegram ID
- Question text
- Source (DM or Support Group)

**Answer Types Supported:**
- **Text** - Written explanations
- **Audio** - Voice explanations
- **Video** - Video tutorials/demos
- **Document** - Files, PDFs, etc.

**What happens:**
- ✅ Answer sent to student's DM
- ✅ Question status updated to "Answered"
- ✅ Confirmation in questions group
- ✅ Google Sheets updated

---

## 📊 Student Analytics

### View Submissions - `/get_submission`

**Where:** Anywhere (DM with bot)  
**Usage:** `/get_submission <username> <module>`

**Example:**
```
/get_submission john_doe 1
```

**Returns:**
- Submission type
- Submission status
- Date submitted
- Grade (if graded)
- Comments (if any)

**Use cases:**
- Check specific student progress
- Review past submissions
- Verify grading completion

---

### List Top Students - `/list_achievers`

**Where:** Anywhere (DM with bot)  
**Shows:** Students with 3+ assignments AND 3+ wins

**Information displayed:**
- Username
- Total assignments submitted
- Total wins shared
- Badge status (🥇 Top Student)


---

## 📢 Messaging Features

- Important updates
- Motivational messages

**Shows:**
- Success count (messages sent)
- Failure count (couldn't send)

---

### Message Top Students

**How:** Click "📢 Broadcast to Achievers" from `/list_achievers`

**Flow:**
1. Use `/list_achievers`
2. Click broadcast button
3. Send your message(s)
4. Messages sent to all top students

**Message types supported:**
- Multiple messages (send as many as needed)
- Text messages
- Audio messages
- Video messages

**Use cases:**
- Recognize achievements
- Offer advanced opportunities
- Send special resources
- Encourage continued excellence

---

## 💡 Daily Tips Management

### Add Manual Tip - `/add_tip`

**Where:** Anywhere (DM with bot)  
**Usage:** `/add_tip <tip content>`

**Example:**
```
/add_tip Don't just learn to code, code to learn!
```

**What happens:**
- ✅ Tip saved to database
- ✅ Added to Google Sheets
- ✅ Included in daily rotation
- ✅ Confirmation sent to you

**Tip Rotation Schedule:**
- **Monday:** AI-generated tip
- **Tuesday:** Manual tip
- **Wednesday:** AI-generated tip
- **Thursday:** Manual tip
- **Friday:** AI-generated tip
- **Saturday:** Manual tip
- **Sunday:** AI-generated tip

**Pro tips:**
- Add tips regularly to build a library
- Keep tips motivational and relevant
- Vary the topics (technical, mindset, habits)
- Tips under 200 characters work best

---

## 🔍 Monitoring & Alerts

### Error Notifications

You automatically receive notifications for:
- Failed student additions
- Failed verifications
- Failed removals
- Duplicate student attempts
- Assignment submission failures
- Question submission failures
- Grading failures
- Daily tip failures
- System errors

**Notification format:**
```
🚨 AVAP Bot Alert:

[Error description]
[Context/details]
[Affected user if applicable]
```

**What to do:**
1. Check the error message
2. Verify the affected feature
3. Check Render logs if needed
4. Take corrective action
5. Notify students if it affects them

---

## 📋 Best Practices

### Student Management
1. **Add students promptly** - Don't keep them waiting
2. **Verify duplicates carefully** - Check if it's a mistake or genuine duplicate
3. **Document removals** - Keep track of why students were removed
4. **Communicate changes** - Let students know about status changes

### Grading
1. **Grade consistently** - Use the same rubric
2. **Add helpful comments** - Guide student improvement
3. **Be timely** - Grade within 48 hours when possible
4. **Use file comments** - Audio/video feedback is powerful

### Communication
1. **Be clear and concise** - Students appreciate brevity
2. **Use broadcasts wisely** - Don't spam
3. **Personalize when possible** - Use names, acknowledge progress
4. **Respond to questions promptly** - 24-hour turnaround ideal

### System Health
1. **Monitor notifications** - Act on errors quickly
2. **Check logs regularly** - Catch issues early (enhanced logging now available)
3. **Test new features** - Use `/test_sheets` and `/test_tip` commands
4. **Backup important data** - Google Sheets serves this purpose (CSV fallback available)
5. **Bot stability** - Ultra-aggressive keepalive (3-second intervals) + memory management
6. **Memory monitoring** - Automatic cleanup when approaching 512MB limit

---

## 🛠️ Troubleshooting

### Common Issues

#### Student Can't Verify
**Symptoms:** Student says bot doesn't recognize their details  
**Solutions:**
1. Check if student was added via `/addstudent`
2. Verify email/phone matches exactly
3. Check for typos in student data
4. Use admin verification as temporary fix
5. Re-add student if necessary

#### Assignment Not Forwarding
**Symptoms:** Student submitted but you didn't receive  
**Solutions:**
1. Check student is verified
2. Verify ASSIGNMENT_GROUP_ID is correct
3. Check bot has access to assignment group
4. Review Render logs for errors

#### Grading Not Working
**Symptoms:** Can't grade or student not notified  
**Solutions:**
1. Ensure using `/grade` command
2. Reply to the correct message
3. Check student has telegram_id
4. Verify Google Sheets access
5. Check error notifications

#### Daily Tips Not Sending
**Symptoms:** Tips not arriving at 8 AM
**Solutions:**
1. Check scheduler is running (Render logs)
2. Verify SUPPORT_GROUP_ID is configured
3. Add manual tips with `/add_tip`
4. Check OPENAI_API_KEY for AI tips
5. Review error notifications
6. Test with `/test_tip` command (admin only)

#### Support Group /ask Not Working
**Symptoms:** `/ask` commands in support group not responding
**Solutions:**
1. Verify SUPPORT_GROUP_ID is correctly configured
2. Check that handler is registered (should appear in logs)
3. Test with `/test_sheets` to verify bot connectivity
4. Review logs for "Support group ask handler triggered" messages
5. Ensure student is verified before using `/ask`

#### Google Sheets Not Updating
**Symptoms:** Wins, assignments, verification not appearing in Sheets
**Solutions:**
1. Test with `/test_sheets` command (admin only)
2. Verify GOOGLE_SHEET_ID and GOOGLE_CREDENTIALS_JSON are configured
3. Check CSV fallback directory exists and is writable
4. Review error notifications for Sheets failures
5. Check Render logs for authentication errors

#### Memory Issues (Bot Crashing)
**Symptoms:** Bot exceeding 512MB memory limit on Render
**Solutions:**
1. Bot now has aggressive memory management (1-minute model cache)
2. Conversation timeouts prevent abandoned conversations
3. Check logs for memory usage warnings
4. Monitor for high memory usage alerts
5. Restart bot if memory issues persist

---

## 📊 Admin Dashboard

### Quick Stats Check

**Verification Status:**
```
/list_achievers  # See top students
```

**Check Submissions:**
```
/get_submission <username> <module>
```

**System Health:**
- Monitor error notifications
- Check Render deployment logs
- Verify webhook health: `https://your-app.onrender.com/health`

---

## 🔄 Daily Admin Workflow

### Morning Routine (15 min)
1. ✅ Check overnight error notifications
2. ✅ Review pending verifications
3. ✅ Check if daily tip sent (8 AM WAT)
4. ✅ Scan support group for issues

### During Day (As needed)
1. ✅ Verify new students
2. ✅ Grade submitted assignments
3. ✅ Answer student questions
4. ✅ Respond to error notifications

### Evening Review (10 min)
1. ✅ Check day's activity
2. ✅ Grade any pending assignments
3. ✅ Answer remaining questions
4. ✅ Plan tomorrow's manual tip (if needed)

---

## 📈 Growth & Engagement

### Encourage Participation
1. **Recognize top students** - Use `/list_achievers` and message them
2. **Share success stories** - Broadcast achievements
3. **Create challenges** - "Submit 3 assignments this week"
4. **Use daily tips effectively** - Mix motivation with tactics

### Build Community
1. **Encourage win sharing** - Celebrate all progress (now shows actual text content!)
2. **Promote student matching** - Help students connect
3. **Acknowledge questions** - Thank students for asking
4. **Feature excellent work** - Highlight great submissions
5. **Direct students to new features** - `/faq` and `/help` commands for better self-service

### Track Metrics
- Verification rate (how many added students verify?)
- Submission completion (how many complete all modules?)
- Top student rate (how many achieve 3/3?)
- Question response time (how fast do you answer?)

### 🤖 Enhanced FAQ System

**New Smart Question Answering:**
- **FAQ Database Matching:** Questions matching 80%+ similarity to FAQ database get instant answers
- **Previous Answer Matching:** Questions similar to previously answered questions (80%+ match) return those answers
- **AI Fallback:** New questions get AI-generated responses
- **Admin Escalation:** Complex questions still reach you for personalized help

**Support Group Integration:**
- Students can use `/ask <question>` directly in support groups
- Smart auto-answering reduces admin workload
- Questions still forwarded to assignment group if no auto-answer found

**Benefits:**
- Faster response times for common questions
- Reduced admin workload for repetitive questions
- Better student experience with instant answers
- Questions stored for future FAQ matching

**Monitoring:**
- Watch for "Similar Question Found!" messages in logs
- Check Google Sheets for auto-answered questions
- Monitor AI answer quality and adjust as needed

---

## 🚨 Emergency Procedures

### Bot Not Responding
1. Check Render deployment status
2. View latest logs
3. Verify webhook is set
4. Restart if necessary
5. Notify students of downtime

### Mass Error Notifications
1. Don't panic - errors are logged
2. Check common cause
3. Fix root issue
4. Test fix
5. Monitor recovery

### Data Loss Concern
1. Google Sheets serves as backup
2. Supabase has point-in-time recovery
3. Export data regularly
4. Document critical information

### Student Complaints
1. Listen and understand
2. Check logs for their activity
3. Verify their account status
4. Test the feature yourself
5. Fix or explain the issue

---

## 📞 Admin Quick Reference

### Commands by Location

**Verification Group:**
- `/addstudent` - Add new student
- `/remove_student` - Remove student

**Assignment Group:**
- `/grade` - Grade submission (reply to assignment)

**Questions Group:**
- `💬 Answer` button - Answer question

**Any Location (DM):**
- `/get_submission <username> <module>` - View submission
- `/list_achievers` - See top students
- `/broadcast <message>` - Message all students
- `/add_tip <tip>` - Add daily tip
- `/test_sheets` - Test Google Sheets connection (admin only)
- `/test_tip` - Test daily tip sending (admin only)

---

## 🎯 Success Metrics

### Your KPIs
- **Response Time:** < 24 hours for questions
- **Grading Time:** < 48 hours for assignments
- **Verification Rate:** > 90% of added students
- **Completion Rate:** Track module completion
- **Engagement:** Monitor wins and questions

### Bot Health
- **Memory Management:** Aggressive cleanup (1-minute model cache, 10-minute conversation timeouts)
- **Connection Stability:** Ultra-aggressive keepalive (3-second intervals)
- **Error Monitoring:** Enhanced logging for all operations
- **Auto-Recovery:** System continues working even if components fail
- **Student Satisfaction:** Gather feedback

---

## 💼 Professional Tips

### Maintain Consistency
- Grade with same criteria
- Respond in similar timeframes
- Use consistent language
- Set clear expectations

### Leverage Automation
- Let bot handle notifications
- Use broadcasts for updates
- Trust duplicate detection
- Rely on error alerts

### Stay Organized
- Use Google Sheets to track
- Document special cases
- Keep notes on student progress
- Plan tips in advance

### Continuous Improvement
- Ask for student feedback
- Monitor which features are used most
- Adjust grading rubrics as needed
- Update tips based on student needs

---

## 🎓 Remember

**You're not just managing a bot—you're supporting student success.**

- Every verification is a student's entry to learning
- Every grade is feedback for growth
- Every answer removes a roadblock
- Every tip provides encouragement

**Your admin work directly impacts student outcomes!**

---

## 📝 Admin Checklist

### Setup Complete
- [ ] Verified admin access works
- [ ] All three groups configured
- [ ] Tested `/addstudent`
- [ ] Tested `/grade`
- [ ] Tested `/answer`
- [ ] Added first daily tip

### Daily Operations
- [ ] Check error notifications
- [ ] Process new verifications
- [ ] Grade pending assignments
- [ ] Answer student questions
- [ ] Monitor system health

### Weekly Tasks
- [ ] Review top students
- [ ] Send encouragement broadcasts
- [ ] Add new manual tips
- [ ] Check completion rates
- [ ] Plan upcoming support

---

*For student guide, see STUDENT_USER_GUIDE.md*  
*For technical documentation, see FINAL_IMPLEMENTATION_REPORT.md*

**Admin Power, Student Success! 💪**


