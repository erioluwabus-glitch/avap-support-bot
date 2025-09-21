# 📚 STUDENT BADGING SYSTEM DOCUMENTATION

## **Feature Overview**
The Student Badging System automatically awards the "AVAP Achiever Badge" to students who meet specific criteria. Currently, it checks for 3 wins shared and 6 graded assignments, but the requested improvement is to check for 3 wins and 3 assignments submitted.

## **How It Works**

### **1. Badge Criteria**
```
Current: 3 wins + 6 graded assignments = 🏆 AVAP Achiever Badge
Requested: 3 wins + 3 assignments submitted = 🏆 AVAP Achiever Badge
```

### **2. Badge Display**
- **Location**: Check Status feature
- **Trigger**: Automatic check when student views status
- **Display**: "🏆 AVAP Achiever Badge earned!"

### **3. Integration Points**
- ✅ **SQLite Database**: Queries wins and submissions tables
- ✅ **Status Display**: Shows badge in check status
- ❌ **Systeme.io**: NOT integrated (could tag as "Achiever")
- ❌ **Notification**: No automatic notification when badge is earned

## **Current Implementation**

### **Badge Check Logic**
```python
# In check_status_handler function
async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... gather assignments and wins count ...
    
    # Check for Achiever badge
    if wins_count >= ACHIEVER_WINS and graded_count >= ACHIEVER_MODULES:
        msg += "\n\n🏆 AVAP Achiever Badge earned!"
```

### **Environment Variables**
```python
ACHIEVER_MODULES = int(os.getenv("ACHIEVER_MODULES", "6"))  # Current: 6 graded
ACHIEVER_WINS = int(os.getenv("ACHIEVER_WING", "3"))       # Current: 3 wins
```

### **Database Queries**
```python
# Count wins
cur.execute("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,))
wins_count = cur.fetchone()[0]

# Count graded assignments
cur.execute("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Graded"))
graded_count = cur.fetchone()[0]
```

## **Issues Identified**

### **1. Wrong Criteria**
**Problem**: Checks for 6 graded assignments instead of 3 submitted assignments
**Impact**: Students need more assignments graded to earn badge

**Current Logic**:
```python
# ❌ WRONG: Only counts graded assignments
cur.execute("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Graded"))
graded_count = cur.fetchone()[0]

if wins_count >= ACHIEVER_WINS and graded_count >= ACHIEVER_MODULES:  # ACHIEVER_MODULES = 6
```

**Should Be**:
```python
# ✅ CORRECT: Count all submitted assignments
cur.execute("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Submitted"))
submitted_count = cur.fetchone()[0]

if wins_count >= ACHIEVER_WINS and submitted_count >= ACHIEVER_MODULES:  # ACHIEVER_MODULES = 3
```

### **2. No Badge Tracking**
**Problem**: No database table to track who has earned badges
**Impact**: Can't track badge history, prevent duplicate notifications

### **3. No Systeme.io Integration**
**Problem**: Badge not reflected in Systeme.io
**Impact**: Can't segment achievers in email marketing

### **4. No Badge Notification**
**Problem**: No automatic notification when badge is earned
**Impact**: Students might not know they earned the badge

### **5. Environment Variable Typo**
**Problem**: `ACHIEVER_WING` instead of `ACHIEVER_WINS`
**Impact**: Potential configuration issues

## **Testing Steps**

### **To Test Current Functionality**
1. Student submits 3 assignments (wait for grading)
2. Student shares 3 wins
3. Student checks status: `/status`
4. **Expected**: "🏆 AVAP Achiever Badge earned!" (if 6 assignments are graded)

### **To Test Improved Functionality (After Fix)**
1. Student submits 3 assignments (no need to wait for grading)
2. Student shares 3 wins
3. Student checks status: `/status`
4. **Expected**: "🏆 AVAP Achiever Badge earned!" + notification

## **Recommended Fixes**

### **Fix 1: Correct Badge Criteria**
```python
async def check_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.message.reply_text("Please DM me to use this feature. Use /ask in group to ask a question to the support team.")
        return
    
    vid = await user_verified_by_telegram_id(update.effective_user.id)
    if not vid:
        await update.message.reply_text("Please verify first!")
        return
    
    # Gather assignments and wins count
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT module, status, score, comment FROM submissions WHERE telegram_id = ?", (update.effective_user.id,))
        subs = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (update.effective_user.id,))
        wins_count = cur.fetchone()[0]
        
        # ✅ FIXED: Count submitted assignments (not just graded)
        cur.execute("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Submitted"))
        submitted_count = cur.fetchone()[0]
        
        # Also count graded for display
        cur.execute("SELECT COUNT(*) FROM submissions WHERE telegram_id = ? AND status = ?", (update.effective_user.id, "Graded"))
        graded_count = cur.fetchone()[0]
    
    # Format submissions with comments
    completed = []
    for r in subs:
        module_info = f"M{r[0]}: {r[1]} (score={r[2]})"
        if r[3]:  # If there's a comment
            module_info += f"\n  💬 Comment: {r[3]}"
        completed.append(module_info)
    
    msg = f"📊 Your Status:\n\n"
    msg += f"Completed modules:\n{chr(10).join(completed) if completed else 'None'}\n\n"
    msg += f"🎉 Wins shared: {wins_count}\n"
    msg += f"📝 Assignments submitted: {submitted_count}\n"
    msg += f"✅ Assignments graded: {graded_count}"
    
    # ✅ FIXED: Check for Achiever badge with correct criteria
    badge_earned = await check_and_award_achiever_badge(update.effective_user.id, wins_count, submitted_count)
    if badge_earned:
        msg += "\n\n🏆 AVAP Achiever Badge earned!"
    
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard())
    return
```

### **Fix 2: Badge Tracking System**
```python
# Add badge tracking table
def init_db():
    # ... existing tables ...
    
    # Badge tracking table
    cur.execute(
        """CREATE TABLE IF NOT EXISTS student_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            badge_type TEXT NOT NULL,
            earned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            notified BOOLEAN DEFAULT FALSE,
            systeme_tagged BOOLEAN DEFAULT FALSE,
            UNIQUE(telegram_id, badge_type)
        )"""
    )

async def check_and_award_achiever_badge(telegram_id: int, wins_count: int, submitted_count: int) -> bool:
    """Check if student qualifies for Achiever badge and award it"""
    try:
        # Check if already has badge
        async with db_lock:
            cur = db_conn.cursor()
            cur.execute("SELECT id FROM student_badges WHERE telegram_id = ? AND badge_type = ?", (telegram_id, "Achiever"))
            existing_badge = cur.fetchone()
            
            if existing_badge:
                return True  # Already has badge
            
            # Check criteria
            if wins_count >= ACHIEVER_WINS and submitted_count >= ACHIEVER_MODULES:
                # Award badge
                cur.execute("INSERT INTO student_badges (telegram_id, badge_type, earned_at) VALUES (?, ?, ?)",
                           (telegram_id, "Achiever", datetime.utcnow().isoformat()))
                db_conn.commit()
                
                # Send notification
                await notify_badge_earned(telegram_id, "Achiever")
                
                # Tag in Systeme.io
                await tag_achiever_in_systeme(telegram_id)
                
                logger.info(f"Student {telegram_id} earned Achiever badge")
                return True
        
        return False
        
    except Exception as e:
        logger.exception(f"Error checking/awarding badge for {telegram_id}: %s", e)
        return False

async def notify_badge_earned(telegram_id: int, badge_type: str):
    """Notify student when they earn a badge"""
    try:
        if badge_type == "Achiever":
            message = "🎉 Congratulations! You've earned the 🏆 AVAP Achiever Badge!\n\n"
            message += "You've shared 3 wins and submitted 3 assignments. Keep up the great work!"
        
        await telegram_app.bot.send_message(chat_id=telegram_id, text=message)
        logger.info(f"Badge notification sent to {telegram_id}")
        
    except Exception as e:
        logger.exception(f"Failed to send badge notification to {telegram_id}: %s", e)
```

### **Fix 3: Systeme.io Integration**
```python
async def tag_achiever_in_systeme(telegram_id: int):
    """Tag student as Achiever in Systeme.io"""
    try:
        # Get student's Systeme.io contact ID
        async with db_lock:
            cur = db_conn.cursor()
            cur.execute("SELECT systeme_contact_id FROM verified_users WHERE telegram_id = ?", (telegram_id,))
            row = cur.fetchone()
            if not row or not row[0]:
                logger.warning(f"No Systeme.io contact ID for student {telegram_id}")
                return False
            
            systeme_contact_id = row[0]
        
        # Add Achiever tag
        if SYSTEME_ACHIEVER_TAG_ID:
            url = f"https://api.systeme.io/api/contacts/{systeme_contact_id}/tags"
            payload = {"tag_id": int(SYSTEME_ACHIEVER_TAG_ID)}
            headers = {"Authorization": f"Bearer {SYSTEME_IO_API_KEY}", "Content-Type": "application/json"}
            
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            
            logger.info(f"Student {telegram_id} tagged as Achiever in Systeme.io")
            return True
        
    except Exception as e:
        logger.exception(f"Failed to tag student {telegram_id} as Achiever in Systeme.io: %s", e)
        return False
```

### **Fix 4: Admin Badge Management**
```python
async def list_achievers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all students who have earned the Achiever badge"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    try:
        async with db_lock:
            cur = db_conn.cursor()
            cur.execute("""
                SELECT sb.telegram_id, vu.name, vu.email, sb.earned_at, sb.notified, sb.systeme_tagged
                FROM student_badges sb
                JOIN verified_users vu ON sb.telegram_id = vu.telegram_id
                WHERE sb.badge_type = 'Achiever'
                ORDER BY sb.earned_at DESC
            """)
            achievers = cur.fetchall()
        
        if not achievers:
            await update.message.reply_text("No students have earned the Achiever badge yet.")
            return
        
        message = "🏆 AVAP Achievers:\n\n"
        for i, (tg_id, name, email, earned_at, notified, systeme_tagged) in enumerate(achievers, 1):
            status = "✅" if notified and systeme_tagged else "⚠️" if notified else "❌"
            message += f"{i}. {name} ({email})\n"
            message += f"   Earned: {earned_at}\n"
            message += f"   Status: {status}\n\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.exception("Error listing achievers: %s", e)
        await update.message.reply_text("Error retrieving achiever list.")

# Add to handler registration
app_obj.add_handler(CommandHandler("list_achievers", list_achievers_cmd))
```

### **Fix 5: Environment Variables**
```python
# Fix typo and add new variables
ACHIEVER_MODULES = int(os.getenv("ACHIEVER_MODULES", "3"))  # ✅ FIXED: 3 submitted assignments
ACHIEVER_WINS = int(os.getenv("ACHIEVER_WINS", "3"))       # ✅ FIXED: typo corrected
SYSTEME_ACHIEVER_TAG_ID = os.getenv("SYSTEME_ACHIEVER_TAG_ID")  # New: for achiever tagging
```

## **Environment Variables**
```bash
# Required (fix existing)
ACHIEVER_MODULES=3  # Changed from 6 to 3
ACHIEVER_WINS=3     # Fixed typo from ACHIEVER_WING

# Optional (for Systeme.io integration)
SYSTEME_ACHIEVER_TAG_ID=789
```

## **Benefits of Fixes**
1. **Correct Criteria**: Badge earned with 3 wins + 3 submitted assignments
2. **Badge Tracking**: Database tracking of badge history
3. **Automatic Notification**: Students notified when they earn badge
4. **Systeme.io Integration**: Achievers tagged for marketing segmentation
5. **Admin Management**: Admins can view all achievers

## **Testing After Fixes**
1. **Badge Criteria**: Test with 3 wins + 3 submitted assignments
2. **Badge Notification**: Verify automatic notification
3. **Badge Tracking**: Check database for badge records
4. **Systeme.io Tagging**: Verify achiever tag in Systeme.io
5. **Admin Commands**: Test `/list_achievers` command
6. **Duplicate Prevention**: Test that badge isn't awarded twice

---
**Last Updated**: $(date)
**Status**: Needs criteria fix and badge tracking system
**Priority**: Medium (improves student motivation and recognition)
