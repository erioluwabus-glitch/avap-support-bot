# AVAP Support Bot - Complete Features Guide (A-Z)

## Overview
The AVAP Support Bot is a comprehensive Telegram bot designed for student support, assignment management, and community engagement. This guide covers all features from A to Z.

---

## 🎯 **STUDENT FEATURES**

### **A - Ask Questions**
- **Command**: `/ask` or use "❓ Ask Question" button
- **Description**: Students can ask questions via text, voice, or video
- **How to use**: 
  1. Send `/ask` command
  2. Type your question or send voice/video
  3. Question is forwarded to support group
- **Groups**: Questions are forwarded to `QUESTIONS_GROUP_ID`


### **C - Cancel Operations**
- **Command**: Available in all conversation flows
- **Description**: Cancel any ongoing operation
- **How to use**: Type "❌ Cancel" or use cancel button during conversations

### **D - Daily Tips**
- **Command**: `/send_tip` (admin), `/test_tip` (admin)
- **Description**: Automated daily tips sent to support group
- **Schedule**: Daily at 8:00 AM
- **Admin features**: Manual tip sending and testing

### **E - Email Verification**
- **Command**: Part of `/start` flow
- **Description**: Students verify using email or phone
- **Process**: 
  1. Send `/start`
  2. Enter email or phone
  3. Admin verifies in verification group
  4. Student gets access to all features

### **F - FAQ System**
- **Command**: `/faq`
- **Description**: Frequently Asked Questions
- **Features**: Pre-defined answers to common questions
- **Access**: Available to all verified students

### **G - Grading System**
- **Command**: `/grade` (admin), `/grades` (student)
- **Description**: Grade student assignments
- **Features**:
  - Score assignments 1-10
  - Add comments
  - View grades
  - Inline grading interface
- **Admin only**: Grading commands

### **H - Help System**
- **Command**: `/help`
- **Description**: Comprehensive help and feature list
- **Features**: Shows all available commands and features
- **Access**: Available to all verified students

### **I - Inline Keyboards**
- **Description**: Interactive buttons for easy navigation
- **Features**:
  - 5-button main menu for DMs
  - No keyboards in group chats
  - Context-aware buttons
- **Smart behavior**: Automatically disabled in group chats

### **J - Join Support Group**
- **Description**: Automatic approval for verified students
- **Process**: Students are auto-approved when verified
- **Group**: `SUPPORT_GROUP_ID`

### **K - Keep-Alive System**
- **Description**: Prevents bot from sleeping on Render
- **Features**:
  - Self-ping every 9 minutes
  - External pinger support
  - Memory monitoring
- **Technical**: Hybrid keep-alive with fallback options

### **L - Landing Page**
- **Description**: Welcome page for new students
- **Features**: Link provided after verification
- **URL**: `LANDING_PAGE_LINK` environment variable

### **M - Main Menu**
- **Description**: 5-button navigation menu
- **Buttons**:
  - 📝 Submit Assignment
  - 🏆 Share Win
  - ❓ Ask Question
  - 📊 View Grades
  - ❓ Help
- **Access**: Available after verification

### **N - Notifications**
- **Description**: Admin notifications for important events
- **Features**:
  - Assignment submissions
  - Student verification requests
  - System errors
  - Broadcast statistics

### **O - Operations Management**
- **Description**: Various admin operations
- **Features**:
  - Clear match requests
  - Test system connections
  - Fix database headers
  - System diagnostics

### **P - Phone Verification**
- **Command**: Part of `/start` flow
- **Description**: Alternative to email verification
- **Format**: International format (e.g., +1234567890)
- **Process**: Same as email verification

### **Q - Question Management**
- **Description**: Handle student questions
- **Features**:
  - Text, voice, video questions
  - Forward to support group
  - Admin can answer via `/answer` command
- **Groups**: Questions forwarded to `QUESTIONS_GROUP_ID`

### **R - Rate Limiting**
- **Description**: Built-in rate limiting protection
- **Features**:
  - Exponential backoff
  - Retry mechanisms
  - 429 error handling
- **Protection**: Prevents API abuse

### **S - Student Management**
- **Commands**: `/addstudent`, `/remove_student`
- **Description**: Admin student management
- **Features**:
  - Add students manually
  - Remove students
  - Verification management
- **Admin only**: Yes

### **T - Tips System**
- **Command**: `/add_tip` (admin)
- **Description**: Add and manage daily tips
- **Features**:
  - Manual tip addition
  - Scheduled daily tips
  - Tip testing
- **Admin only**: Tip management

### **U - User Verification**
- **Description**: Multi-step verification process
- **Steps**:
  1. Student sends `/start`
  2. Enters email/phone
  3. Admin verifies in verification group
  4. Student gets full access
- **Groups**: Verification happens in `VERIFICATION_GROUP_ID`

### **V - View Grades**
- **Command**: `/grades` or "📊 View Grades" button
- **Description**: Students can view their grades
- **Features**: Shows all graded assignments with scores and comments
- **Access**: Available to all verified students

### **W - Win Sharing**
- **Command**: "🏆 Share Win" button
- **Description**: Students share their achievements
- **Features**:
  - Text, voice, video wins
  - Forwarded to support group
  - Motivational sharing
- **Groups**: Wins forwarded to `SUPPORT_GROUP_ID`

### **X - X-API Integration**
- **Description**: Systeme.io API integration
- **Features**:
  - Contact creation
  - Tag management
  - API key validation
- **Technical**: Handles 401, 422 errors gracefully

### **Y - YouTube Integration**
- **Description**: Video assignment support
- **Features**:
  - Video file uploads
  - Video question support
  - Video win sharing
- **Formats**: MP4, MOV, AVI supported

### **Z - Zero Downtime**
- **Description**: High availability design
- **Features**:
  - Keep-alive system
  - Error recovery
  - Graceful shutdowns
- **Technical**: Prevents service interruptions

---

## 🔧 **ADMIN FEATURES**

### **Admin Commands**
- `/addstudent` - Add new student
- `/remove_student` - Remove student
- `/stats` - View statistics
- `/broadcast` - Send broadcast to all
- `/get_submission` - Get specific submission
- `/clear_matches` - Clear match requests
- `/test_systeme` - Test Systeme.io connection
- `/fix_headers` - Fix database headers
- `/list_students` - List all students
- `/grade` - Grade assignments
- `/answer` - Answer questions
- `/add_tip` - Add daily tip
- `/send_tip` - Send tip manually
- `/test_tip` - Test tip sending

### **Admin Groups**
- **Verification Group**: Student verification
- **Assignment Group**: Assignment grading
- **Questions Group**: Question handling
- **Support Group**: General support

### **Admin Tools**
- **Broadcast System**: Send messages to achievers
- **Statistics**: View user stats and submissions
- **Student Management**: Add/remove students
- **Grading System**: Grade assignments with scores and comments
- **Question Answering**: Answer student questions
- **System Diagnostics**: Test connections and fix issues

---

## 🌐 **WEB ENDPOINTS**

### **Health Endpoints**
- `/health` - Basic health check
- `/ping` - Simple ping endpoint

### **Admin Endpoints**
- `/admin/purge/email` - Purge single email
- `/admin/purge/phone` - Purge single phone
- `/admin/purge/telegram` - Purge single Telegram ID
- `/admin/reset` - Reset bot state

---

## 📊 **DATABASE FEATURES**

### **Tables**
- `verified_users` - Verified students
- `pending_verifications` - Pending verifications
- `submissions` - Assignment submissions
- `wins` - Student achievements
- `questions` - Student questions
- `broadcasts` - Admin broadcasts
- `locks` - Distributed locks
- `cooldown_states` - Rate limiting states

### **Services**
- **Supabase**: Primary database
- **Google Sheets**: Data backup and reporting
- **Systeme.io**: Contact management

---

## 🔒 **SECURITY FEATURES**

### **Authentication**
- Admin user verification
- Group-specific commands
- Token-based authentication
- Rate limiting protection

### **Privacy**
- No inline keyboards in groups
- Secure data handling
- Environment variable protection
- Error logging without sensitive data

---

## 🚀 **DEPLOYMENT FEATURES**

### **Render Integration**
- Automatic deployment from GitHub
- Environment variable management
- Health monitoring
- Keep-alive system

### **Monitoring**
- Memory usage tracking
- Error logging
- Performance monitoring
- Uptime tracking

---

## 📱 **USER INTERFACE**

### **Main Menu (5 Buttons)**
1. 📝 Submit Assignment
2. 🏆 Share Win
3. ❓ Ask Question
4. 📊 View Grades
5. ❓ Help

### **Conversation Flows**
- Assignment submission
- Win sharing
- Question asking
- Grade viewing
- Help system

### **Smart Behavior**
- No keyboards in group chats
- Context-aware responses
- Error handling
- Retry mechanisms

---

## 🎯 **USAGE INSTRUCTIONS**

### **For Students**
1. Send `/start` to begin
2. Verify with email/phone
3. Wait for admin verification
4. Use main menu for all features
5. Submit assignments, share wins, ask questions

### **For Admins**
1. Use verification group for student approval
2. Use assignment group for grading
3. Use questions group for answering
4. Use support group for general management
5. Use admin commands for system management

### **For Developers**
1. Set up environment variables
2. Configure group IDs
3. Set up external pingers
4. Monitor logs and performance
5. Use admin endpoints for maintenance

---

## 🔧 **TECHNICAL FEATURES**

### **Architecture**
- FastAPI web framework
- Telegram Bot API
- Supabase database
- Google Sheets integration
- Systeme.io API
- Render deployment

### **Performance**
- Async/await patterns
- Connection pooling
- Memory monitoring
- Rate limiting
- Error recovery

### **Reliability**
- Keep-alive system
- External pinger support
- Graceful shutdowns
- Error handling
- Retry mechanisms

---

This comprehensive guide covers all features of the AVAP Support Bot from A to Z. The bot is designed for student support, assignment management, and community engagement with robust admin tools and monitoring capabilities.
