# 📚 REMOVE STUDENT FEATURE DOCUMENTATION

## **Feature Overview**
The Remove Student feature allows admins to remove verified students from the system. Currently, it requires a Telegram ID, but the requested improvement is to allow removal by student name or email for better usability.

## **How It Works**

### **1. Current Flow**
```
Admin → /remove_student [telegram_id] → Student Removed → Confirmation
```

### **2. Current Process**
- **Input**: Telegram ID (numeric)
- **Database**: Removes from `verified_users`, updates `pending_verifications`
- **Google Sheets**: Updates status to "Removed"
- **Systeme.io**: NOT integrated (missing)

### **3. Integration Points**
- ✅ **SQLite Database**: Updates both tables
- ✅ **Google Sheets**: Updates verification status
- ❌ **Systeme.io**: NOT integrated (should remove contact/tag)
- ❌ **User-Friendly Input**: Requires Telegram ID instead of name/email

## **Current Implementation**

### **Command Structure**
```python
async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin authorization check
    # Validate telegram_id input
    # Find student by telegram_id
    # Remove from verified_users
    # Update pending_verifications status
    # Update Google Sheets
    # Send confirmation
```

### **Current Code**
```python
async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_student [telegram_id]")
        return
    
    try:
        t_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid telegram_id.")
        return
    
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT email, name FROM verified_users WHERE telegram_id = ?", (t_id,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text(f"No verified student found with Telegram ID {t_id}.")
            return
        
        email, name = row
        cur.execute("DELETE FROM verified_users WHERE telegram_id = ?", (t_id,))
        cur.execute("UPDATE pending_verifications SET status = ?, telegram_id = ? WHERE email = ?", ("Removed", 0, email))
        db_conn.commit()
    
    # Update Google Sheets
    try:
        if gs_sheet:
            try:
                sheet = gs_sheet.worksheet("Verifications")
                cells = sheet.findall(email)
                for c in cells:
                    row_idx = c.row
                    sheet.update_cell(row_idx, 5, "Removed")
                    sheet.update_cell(row_idx, 4, "")
            except Exception:
                pass
    except Exception:
        logger.exception("Sheets update failed")
    
    await update.message.reply_text(f"Student {name} ({t_id}) removed. They must re-verify to regain access.")
```

## **Issues Identified**

### **1. User-Unfriendly Input**
**Problem**: Requires Telegram ID instead of name or email
**Impact**: Admins need to look up Telegram IDs manually

**Current Usage**:
```
/remove_student 123456789  # ❌ Hard to remember/type
```

**Should Be**:
```
/remove_student john@example.com  # ✅ Easy to use
/remove_student "John Doe"        # ✅ Easy to use
```

### **2. Systeme.io Integration Missing**
**Problem**: Doesn't remove contact from Systeme.io
**Impact**: Student remains in Systeme.io even after removal

### **3. No Confirmation for Removal**
**Problem**: No confirmation step before removal
**Impact**: Accidental removals possible

### **4. No Batch Removal**
**Problem**: Can only remove one student at a time
**Impact**: Inefficient for bulk operations

## **Testing Steps**

### **To Test Current Functionality**
1. Admin sends: `/remove_student 123456789`
2. **Expected**: "Student John Doe (123456789) removed. They must re-verify to regain access."

### **To Test Improved Functionality (After Fix)**
1. Admin sends: `/remove_student john@example.com`
2. **Expected**: Confirmation prompt → Admin confirms → Student removed from all systems

## **Recommended Fixes**

### **Fix 1: Enhanced Input Handling**
```python
async def remove_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_student [email|name|telegram_id]")
        return
    
    identifier = " ".join(context.args).strip()
    
    # Determine identifier type and find student
    student_info = await find_student_by_identifier(identifier)
    if not student_info:
        await update.message.reply_text(f"No verified student found with identifier: {identifier}")
        return
    
    # Show confirmation
    confirmation_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Removal", callback_data=f"confirm_remove_{student_info['telegram_id']}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")]
    ])
    
    await update.message.reply_text(
        f"⚠️ Confirm removal of student:\n\n"
        f"Name: {student_info['name']}\n"
        f"Email: {student_info['email']}\n"
        f"Telegram ID: {student_info['telegram_id']}\n\n"
        f"This will remove them from all systems and revoke access.",
        reply_markup=confirmation_keyboard
    )

async def find_student_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """Find student by email, name, or telegram_id"""
    async with db_lock:
        cur = db_conn.cursor()
        
        # Try as email first
        if "@" in identifier:
            cur.execute("SELECT name, email, phone, telegram_id, systeme_contact_id FROM verified_users WHERE email = ?", (identifier,))
            row = cur.fetchone()
            if row:
                return {
                    'name': row[0],
                    'email': row[1],
                    'phone': row[2],
                    'telegram_id': row[3],
                    'systeme_contact_id': row[4]
                }
        
        # Try as telegram_id
        try:
            t_id = int(identifier)
            cur.execute("SELECT name, email, phone, telegram_id, systeme_contact_id FROM verified_users WHERE telegram_id = ?", (t_id,))
            row = cur.fetchone()
            if row:
                return {
                    'name': row[0],
                    'email': row[1],
                    'phone': row[2],
                    'telegram_id': row[3],
                    'systeme_contact_id': row[4]
                }
        except ValueError:
            pass
        
        # Try as name (partial match)
        cur.execute("SELECT name, email, phone, telegram_id, systeme_contact_id FROM verified_users WHERE name LIKE ?", (f"%{identifier}%",))
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
            return {
                'name': row[0],
                'email': row[1],
                'phone': row[2],
                'telegram_id': row[3],
                'systeme_contact_id': row[4]
            }
        elif len(rows) > 1:
            # Multiple matches - return list for admin to choose
            return {'multiple_matches': rows}
    
    return None
```

### **Fix 2: Confirmation Callback Handler**
```python
async def remove_student_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    
    if not await is_admin(query.from_user.id):
        await query.answer("You are not authorized to perform this action.", show_alert=True)
        return
    
    data = query.data
    
    if data == "cancel_remove":
        await query.edit_message_text("Student removal cancelled.")
        return
    
    if data.startswith("confirm_remove_"):
        telegram_id = int(data.split("_")[2])
        await query.answer()
        
        # Perform removal
        success = await remove_student_complete(telegram_id)
        
        if success:
            await query.edit_message_text("✅ Student removed successfully from all systems.")
        else:
            await query.edit_message_text("⚠️ Student removed from bot but some integrations may have failed. Check logs.")

async def remove_student_complete(telegram_id: int) -> bool:
    """Complete student removal from all systems"""
    try:
        # Get student info
        async with db_lock:
            cur = db_conn.cursor()
            cur.execute("SELECT name, email, phone, systeme_contact_id FROM verified_users WHERE telegram_id = ?", (telegram_id,))
            row = cur.fetchone()
            if not row:
                logger.error(f"Student not found for removal: {telegram_id}")
                return False
            
            name, email, phone, systeme_contact_id = row
            
            # Remove from verified_users
            cur.execute("DELETE FROM verified_users WHERE telegram_id = ?", (telegram_id,))
            
            # Update pending_verifications
            cur.execute("UPDATE pending_verifications SET status = ?, telegram_id = ? WHERE email = ?", ("Removed", 0, email))
            
            db_conn.commit()
        
        # Update Google Sheets
        sheets_success = await update_sheets_removal(email)
        
        # Remove from Systeme.io
        systeme_success = await remove_systeme_contact(systeme_contact_id)
        
        # Notify student (optional)
        try:
            await telegram_app.bot.send_message(
                chat_id=telegram_id,
                text="Your access to AVAP has been revoked. Please contact an admin if you believe this is an error."
            )
        except Exception:
            logger.warning(f"Could not notify student {telegram_id} of removal")
        
        logger.info(f"Student {name} ({email}) removed successfully")
        return sheets_success and systeme_success
        
    except Exception as e:
        logger.exception(f"Error removing student {telegram_id}: %s", e)
        return False
```

### **Fix 3: Systeme.io Integration**
```python
async def remove_systeme_contact(contact_id: str) -> bool:
    """Remove contact from Systeme.io"""
    if not contact_id or not SYSTEME_IO_API_KEY:
        logger.warning("No Systeme.io contact ID or API key - skipping removal")
        return True
    
    try:
        # Remove contact from Systeme.io
        url = f"https://api.systeme.io/api/contacts/{contact_id}"
        headers = {"Authorization": f"Bearer {SYSTEME_IO_API_KEY}"}
        
        r = requests.delete(url, headers=headers, timeout=15)
        
        if r.status_code == 404:
            logger.warning(f"Systeme.io contact {contact_id} not found (already removed)")
            return True
        
        r.raise_for_status()
        logger.info(f"Systeme.io contact {contact_id} removed successfully")
        return True
        
    except Exception as e:
        logger.exception(f"Failed to remove Systeme.io contact {contact_id}: %s", e)
        return False

async def update_sheets_removal(email: str) -> bool:
    """Update Google Sheets for student removal"""
    try:
        if not gs_sheet:
            logger.warning("Google Sheets not configured - skipping update")
            return True
        
        sheet = gs_sheet.worksheet("Verifications")
        cells = sheet.findall(email)
        
        for c in cells:
            row_idx = c.row
            sheet.update_cell(row_idx, 5, "Removed")  # status column
            sheet.update_cell(row_idx, 4, "")         # telegram_id column
        
        logger.info(f"Google Sheets updated for removed student: {email}")
        return True
        
    except Exception as e:
        logger.exception(f"Failed to update Google Sheets for removal: %s", e)
        return False
```

### **Fix 4: Multiple Matches Handler**
```python
async def handle_multiple_matches(update: Update, context: ContextTypes.DEFAULT_TYPE, matches: List[Tuple]):
    """Handle multiple student matches"""
    keyboard_buttons = []
    for i, (name, email, phone, telegram_id, systeme_contact_id) in enumerate(matches):
        keyboard_buttons.append([
            InlineKeyboardButton(
                f"{name} ({email})",
                callback_data=f"remove_specific_{telegram_id}"
            )
        ])
    
    keyboard_buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")])
    
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    await update.message.reply_text(
        "Multiple students found. Please select the one to remove:",
        reply_markup=keyboard
    )

# Add to handler registration
app_obj.add_handler(CallbackQueryHandler(remove_student_confirm_callback, pattern="^(confirm_remove_|cancel_remove|remove_specific_)"))
```

## **Benefits of Fixes**
1. **User-Friendly**: Remove by email or name instead of Telegram ID
2. **Complete Integration**: Remove from all systems (bot, Google Sheets, Systeme.io)
3. **Confirmation Step**: Prevent accidental removals
4. **Better Error Handling**: Clear feedback on removal status
5. **Student Notification**: Inform student of access revocation

## **Testing After Fixes**
1. **Email Removal**: `/remove_student john@example.com`
2. **Name Removal**: `/remove_student "John Doe"`
3. **Telegram ID**: `/remove_student 123456789` (still works)
4. **Multiple Matches**: Test with partial name matches
5. **Confirmation**: Test confirmation and cancellation
6. **Systeme.io**: Verify contact removal from Systeme.io
7. **Google Sheets**: Verify status update in sheets

---
**Last Updated**: $(date)
**Status**: Needs complete rewrite for better UX and integration
**Priority**: High (improves admin usability and system integration)
