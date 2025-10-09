# AVAP Support Bot - Detailed Usage Guide

## 📋 **STUDENT FEATURES - STEP BY STEP**

### **1. Getting Started**
```
1. Send /start to the bot
2. Enter your email or phone number
3. Wait for admin verification in verification group
4. Once verified, you'll get access to the main menu
```

### **2. Main Menu Features**

#### **📝 Submit Assignment**
```
1. Click "📝 Submit Assignment" button
2. Select module (Module 1, Module 2, etc.)
3. Choose submission type:
   - 📝 Text: Type your assignment
   - 🎤 Audio: Send voice message
   - 🎥 Video: Send video file
4. Submit your work
5. Assignment is forwarded to grading group
```

#### **🏆 Share Win**
```
1. Click "🏆 Share Win" button
2. Choose win type:
   - 📝 Text: Type your achievement
   - 🎤 Audio: Send voice message
   - 🎥 Video: Send video file
3. Share your success story
4. Win is forwarded to support group
```

#### **❓ Ask Question**
```
1. Click "❓ Ask Question" button
2. Type your question or send:
   - Text message
   - Voice message
   - Video message
3. Question is forwarded to questions group
4. Admin will answer via /answer command
```

#### **📊 View Grades**
```
1. Click "📊 View Grades" button
2. View all your graded assignments
3. See scores (1-10) and comments
4. Track your progress
```

#### **❓ Help**
```
1. Click "❓ Help" button
2. View comprehensive help
3. See all available features
4. Get assistance
```

### **3. Support Group Features**
```
- Send /ask in support group
- Get help from community
- Share experiences
- Receive daily tips
```

---

## 🔧 **ADMIN FEATURES - STEP BY STEP**

### **1. Student Management**

#### **Add Student**
```
1. Go to verification group
2. Send /addstudent
3. Enter student name
4. Enter phone number
5. Enter email
6. Student is added to system
```

#### **Remove Student**
```
1. Go to verification group
2. Send /remove_student
3. Enter student identifier (email/phone/name)
4. Confirm removal
5. Student is removed from system
```

### **2. Assignment Grading**

#### **Grade Assignment**
```
1. Go to assignment group
2. Send /grade
3. Select assignment to grade
4. Give score (1-10)
5. Add comments (optional)
6. Grade is recorded
```

#### **View Grades**
```
1. Send /grades command
2. View all graded assignments
3. See student progress
4. Export data if needed
```

### **3. Question Management**

#### **Answer Questions**
```
1. Go to questions group
2. Send /answer command
3. Select question to answer
4. Choose answer type:
   - 📝 Text answer
   - 🎤 Voice answer
   - 🎥 Video answer
5. Provide answer
6. Student receives response
```

### **4. Broadcasting**

#### **Broadcast to All**
```
1. Send /broadcast command
2. Choose broadcast type:
   - 📝 Text broadcast
   - 🎤 Audio broadcast
   - 🎥 Video broadcast
3. Enter broadcast content
4. Send to all verified students
```

#### **Broadcast to Achievers**
```
1. Send /broadcast_achievers command
2. Enter message for achievers
3. Send to high-performing students
4. Track broadcast statistics
```

### **5. System Management**

#### **View Statistics**
```
1. Send /stats command
2. View user statistics
3. See submission counts
4. Monitor system health
```

#### **Test Connections**
```
1. Send /test_systeme command
2. Test Systeme.io API connection
3. Verify API key validity
4. Check integration status
```

#### **Clear Data**
```
1. Send /clear_matches command
2. Clear match requests
3. Reset system state
4. Clean up data
```

---

## 🌐 **WEB ENDPOINTS - USAGE**

### **Health Monitoring**
```
GET /health
- Check bot health status
- View memory usage
- Verify database connection
- Monitor system status
```

### **Admin Operations**
```
POST /admin/purge/email
- Purge single email
- Reset user data
- Clean up database

POST /admin/purge/phone
- Purge single phone
- Remove contact info
- Update records

POST /admin/purge/telegram
- Purge Telegram ID
- Remove user access
- Clean up data

POST /admin/reset
- Reset bot state
- Clear all data
- Restart system
```

---

## 📊 **DATABASE OPERATIONS**

### **User Management**
```
- Add verified users
- Update user information
- Remove inactive users
- Track user activity
```

### **Content Management**
```
- Store assignments
- Save student wins
- Record questions
- Track broadcasts
```

### **System Data**
```
- Manage distributed locks
- Track cooldown states
- Monitor system health
- Log operations
```

---

## 🔒 **SECURITY BEST PRACTICES**

### **Admin Security**
```
1. Use verification group for student approval
2. Keep admin commands in appropriate groups
3. Monitor system logs regularly
4. Use strong authentication tokens
```

### **Data Protection**
```
1. No sensitive data in logs
2. Secure environment variables
3. Regular data backups
4. Access control for groups
```

---

## 🚀 **DEPLOYMENT GUIDE**

### **Environment Setup**
```
1. Set BOT_TOKEN
2. Configure group IDs:
   - ASSIGNMENT_GROUP_ID
   - SUPPORT_GROUP_ID
   - QUESTIONS_GROUP_ID
   - VERIFICATION_GROUP_ID
3. Set admin credentials
4. Configure database
5. Set up external services
```

### **Monitoring Setup**
```
1. Configure keep-alive system
2. Set up external pingers
3. Monitor memory usage
4. Track error logs
5. Set up alerts
```

### **Maintenance**
```
1. Regular log monitoring
2. Database cleanup
3. Performance optimization
4. Security updates
5. Backup verification
```

---

## 🎯 **TROUBLESHOOTING**

### **Common Issues**

#### **Bot Not Responding**
```
1. Check if service is running
2. Verify webhook configuration
3. Check rate limiting
4. Monitor memory usage
5. Restart if needed
```

#### **Students Can't Verify**
```
1. Check verification group
2. Verify admin commands
3. Check database connection
4. Monitor error logs
5. Test verification flow
```

#### **Assignments Not Graded**
```
1. Check assignment group
2. Verify grading commands
3. Check admin permissions
4. Monitor system logs
5. Test grading flow
```

#### **Questions Not Answered**
```
1. Check questions group
2. Verify answer commands
3. Check admin permissions
4. Monitor system logs
5. Test question flow
```

### **System Diagnostics**
```
1. Send /test_systeme command
2. Check /stats for system health
3. Monitor memory usage
4. Check database connectivity
5. Verify external services
```

---

## 📱 **USER INTERFACE GUIDE**

### **Button Layout**
```
Main Menu (5 buttons):
┌─────────────────────────┐
│ 📝 Submit Assignment    │
│ 🏆 Share Win           │
│ ❓ Ask Question        │
│ 📊 View Grades         │
│ ❓ Help               │
└─────────────────────────┘
```

### **Conversation Flows**
```
Assignment Submission:
1. Click "📝 Submit Assignment"
2. Select module
3. Choose type (text/audio/video)
4. Submit content
5. Confirmation message

Win Sharing:
1. Click "🏆 Share Win"
2. Choose type (text/audio/video)
3. Share content
4. Confirmation message

Question Asking:
1. Click "❓ Ask Question"
2. Type or send content
3. Question forwarded
4. Wait for admin response
```

---

## 🔧 **ADVANCED FEATURES**

### **Customization**
```
1. Modify button text
2. Change conversation flows
3. Add new features
4. Customize responses
5. Update help text
```

### **Integration**
```
1. Google Sheets integration
2. Systeme.io API
3. Supabase database
4. External pingers
5. Web endpoints
```

### **Monitoring**
```
1. Health checks
2. Performance metrics
3. Error tracking
4. User analytics
5. System diagnostics
```

---

This detailed usage guide provides step-by-step instructions for all features of the AVAP Support Bot, from basic student usage to advanced admin management and system maintenance.
