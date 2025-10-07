# 🤖 AVAP Support Bot - Complete Testing Checklist

## 📋 **PRE-TESTING SETUP**

### ✅ **Environment Verification**
- [ ] Bot is deployed and running (check logs for "Your service is live 🎉")
- [ ] Memory usage is stable (should be ~105-120MB)
- [ ] All services initialized successfully
- [ ] Webhook is set correctly
- [ ] Google Sheets connection working
- [ ] Supabase connection working

---

## 🔐 **1. USER VERIFICATION SYSTEM**

### ✅ **New User Registration**
- [ ] Send `/start` to bot in private chat
- [ ] Bot responds with verification prompt
- [ ] Enter valid email/phone number
- [ ] Bot shows "Verification request submitted" message
- [ ] Admin receives notification in admin group

### ✅ **User Verification (Admin)**
- [ ] Admin uses `/verify` command in admin group
- [ ] Admin selects user from pending list
- [ ] User receives "You are now verified!" message
- [ ] User gets main menu with 4 buttons
- [ ] Systeme.io contact created (if configured)

### ✅ **Verified User Access**
- [ ] Verified user gets main menu buttons:
  - [ ] 📝 Submit Assignment
  - [ ] 🏆 Share Win
  - [ ] 📊 View Grades
  - [ ] 📊 Check Status
  - [ ] ❓ Ask Question

### ✅ **Unverified User Restrictions**
- [ ] Unverified user cannot access main features
- [ ] Buttons show "You must be verified" message
- [ ] User is directed to `/start` for verification

---

## 📝 **2. ASSIGNMENT SUBMISSION SYSTEM**

### ✅ **Assignment Submission Process**
- [ ] Click "📝 Submit Assignment"
- [ ] Select module (1-12)
- [ ] Choose submission type:
  - [ ] 📝 Text submission
  - [ ] 🎤 Audio submission
  - [ ] 🎥 Video submission
- [ ] Submit content
- [ ] Receive "Assignment Submitted Successfully!" message

### ✅ **Assignment Forwarding**
- [ ] Assignment appears in assignment group
- [ ] Shows student info: username, telegram ID, module, type
- [ ] **CRITICAL**: Grade inline buttons appear:
  - [ ] 📝 GRADE button
  - [ ] ❌ Cancel button

### ✅ **Assignment Grading (Admin)**
- [ ] Admin clicks "📝 GRADE" button
- [ ] Grade selection buttons appear (1-10)
- [ ] Admin selects grade
- [ ] Comment option appears
- [ ] Student receives grade notification
- [ ] Grade appears in "View Grades"

---

## 🏆 **3. WIN SHARING SYSTEM**

### ✅ **Win Sharing Process**
- [ ] Click "🏆 Share Win"
- [ ] Choose win type:
  - [ ] 📝 Text win
  - [ ] 🎤 Audio win
- [ ] Submit win content
- [ ] Receive "Win Shared Successfully!" message

### ✅ **Win Forwarding**
- [ ] Win appears in support group
- [ ] Shows student info and win content
- [ ] Win is saved to Google Sheets

### ✅ **Status Update Verification**
- [ ] Click "📊 Check Status"
- [ ] Win count updates correctly
- [ ] Badge status updates (New Student → Active Student → Top Student)
- [ ] Progress tracking works

---

## ❓ **4. QUESTION & ANSWER SYSTEM**

### ✅ **Question Submission**
- [ ] Click "❓ Ask Question"
- [ ] Submit question (text/audio/video)
- [ ] Receive "Question Submitted!" message
- [ ] **CRITICAL**: No NameError crashes

### ✅ **Question Forwarding**
- [ ] Question appears in **QUESTIONS GROUP** (not assignment group)
- [ ] Shows student info and question content
- [ ] **💬 Answer** button appears for admins

### ✅ **Question Answering (Admin)**
- [ ] Admin clicks "💬 Answer" button
- [ ] Answer conversation starts
- [ ] Admin can provide text/audio/video answer
- [ ] Student receives answer notification
- [ ] Answer is saved to system

### ✅ **Support Group Questions**
- [ ] Use `/ask <question>` in support group
- [ ] Question forwards to questions group
- [ ] Admin can answer via button

---

## 📊 **5. STATUS & GRADES SYSTEM**

### ✅ **Status Check**
- [ ] Click "📊 Check Status"
- [ ] Shows current progress:
  - [ ] Badge status (New/Active/Top Student)
  - [ ] Assignment count
  - [ ] Win count
  - [ ] Question count
  - [ ] Module progress
- [ ] **CRITICAL**: Win count updates after sharing wins

### ✅ **View Grades**
- [ ] Click "📊 View Grades"
- [ ] Shows graded assignments
- [ ] Displays grades and comments
- [ ] Shows "No graded assignments" if none

---

## 👥 **6. STUDENT MATCHING SYSTEM**

### ✅ **Match Feature**
- [ ] Use `/match` command
- [ ] Bot adds user to matching queue
- [ ] If another user uses `/match`, both get matched
- [ ] Both users receive match notification
- [ ] Users can start chatting

---

## 🔧 **7. ADMIN FEATURES**

### ✅ **Admin Commands**
- [ ] `/verify` - Verify pending users
- [ ] `/grade` - Grade assignments
- [ ] `/answer` - Answer questions
- [ ] `/broadcast` - Send messages to all users
- [ ] `/stats` - View system statistics

### ✅ **Admin Tools**
- [ ] User management
- [ ] Assignment grading
- [ ] Question answering
- [ ] System monitoring

---

## 🚨 **8. ERROR HANDLING & EDGE CASES**

### ✅ **Memory Management**
- [ ] Bot runs stable at ~105-120MB
- [ ] No memory watchdog restarts
- [ ] No "coroutine was never awaited" warnings
- [ ] No NameError exceptions

### ✅ **Network Issues**
- [ ] Google Sheets fallback to CSV works
- [ ] Supabase connection recovery
- [ ] Telegram API rate limiting handled

### ✅ **Data Consistency**
- [ ] Wins saved to `wins_new` worksheet
- [ ] Status reads from `wins_new` worksheet
- [ ] Questions forward to questions group
- [ ] Assignments forward to assignment group

---

## 📱 **9. USER INTERFACE TESTING**

### ✅ **Button Functionality**
- [ ] All 4 main buttons work for verified users
- [ ] Buttons restricted for unverified users
- [ ] Inline buttons work (grade, answer)
- [ ] Conversation handlers work properly

### ✅ **Message Formatting**
- [ ] Markdown formatting works
- [ ] Emojis display correctly
- [ ] Error messages are clear
- [ ] Success messages are informative

---

## 🔄 **10. INTEGRATION TESTING**

### ✅ **End-to-End Workflows**
- [ ] **Complete Student Journey**:
  1. Register → Verify → Submit Assignment → Share Win → Ask Question → Check Status
- [ ] **Complete Admin Journey**:
  1. Verify User → Grade Assignment → Answer Question → Check Stats
- [ ] **Data Flow**:
  1. Student submits → Admin grades → Student views grade
  2. Student asks → Admin answers → Student receives answer

---

## 🎯 **CRITICAL SUCCESS CRITERIA**

### ✅ **Must Work 100%**
- [ ] **Grade Inline Buttons**: Must appear in assignment group
- [ ] **Question Forwarding**: Must go to questions group
- [ ] **Status Updates**: Must show correct win count
- [ ] **No Crashes**: No NameError or async/await errors
- [ ] **Memory Stability**: No restart loops

### ✅ **Performance Benchmarks**
- [ ] Memory usage: <150MB
- [ ] Response time: <3 seconds
- [ ] No timeout errors
- [ ] Stable operation for 24+ hours

---

## 📝 **TESTING NOTES**

### **Test Environment**
- Use test Telegram accounts
- Test in private chats and groups
- Verify admin permissions
- Check Google Sheets data

### **Common Issues to Watch**
- Memory spikes during AI operations
- Worksheet name mismatches
- Async/await errors
- Variable name errors

### **Success Indicators**
- All features work without errors
- Data persists correctly
- Users get proper feedback
- Admins can manage system

---

## 🎉 **COMPLETION CHECKLIST**

- [ ] All 10 test categories completed
- [ ] All critical success criteria met
- [ ] No errors or crashes
- [ ] Data consistency verified
- [ ] User experience smooth
- [ ] Admin workflow functional
- [ ] System stable and performant

**✅ BOT IS READY FOR PRODUCTION!**
