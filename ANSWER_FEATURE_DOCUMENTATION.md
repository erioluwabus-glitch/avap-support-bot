# 📚 ANSWER FEATURE DOCUMENTATION

## **Feature Overview**
The Answer feature allows admins to respond to student questions. When a student asks a question, it's forwarded to the questions group with an "Answer" button. Admins can click this button to provide an answer, which is then sent back to the student and optionally recorded as an FAQ.

## **How It Works**

### **1. Question Flow**
```
Student → Ask Question → Questions Group → Admin Clicks "Answer" → Admin Types Answer → Student Receives Answer
```

### **2. FAQ System**
- **Purpose**: Automatically record Q&A pairs for future reference
- **Storage**: Google Sheets "FAQ" worksheet
- **Format**: Question | Answer | Created At

### **3. Integration Points**
- ✅ **SQLite Database**: Stores questions and answers
- ✅ **Student Notification**: Sends answer back to student
- ❌ **FAQ Auto-Response**: NOT implemented (similar questions don't get auto-answered)

## **Current Implementation**

### **Question Submission**
```python
async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Store question in database
    # Forward to questions group with Answer button
    # End conversation

async def ask_start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle /ask command in groups
    # Forward to questions group
    # End conversation
```

### **Answer Process**
```python
async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin clicks "Answer" button
    # Store question_id in context
    # Prompt for answer
    return ANSWER_QUESTION

async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Process admin's answer
    # Send to student
    # Record in FAQ (Google Sheets)
    # End conversation
```

### **Handler Registration**
```python
# Ask questions conversation
ask_conv = ConversationHandler(
    entry_points=[
        CommandHandler("ask", ask_start_cmd), 
        MessageHandler(filters.Regex("^❓ Ask a Question$") & filters.ChatType.PRIVATE, ask_button_handler)
    ],
    states={ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)]},
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)

# Answer conversation
answer_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(answer_callback, pattern="^answer_")],
    states={ANSWER_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_receive)]},
    fallbacks=[CommandHandler("cancel", cancel_handler)],
    per_message=False
)
```

## **Issues Identified**

### **1. FAQ Auto-Response Not Implemented**
**Problem**: Similar questions don't get automatic answers from FAQ
**Impact**: Admins have to manually answer repetitive questions

**Current Code**:
```python
# In answer_receive - FAQ is only recorded, not used for auto-response
try:
    if gs_sheet:
        try:
            sheet = gs_sheet.worksheet("FAQ")
        except Exception:
            sheet = gs_sheet.add_worksheet("FAQ", rows=100, cols=10)
            sheet.append_row(["question", "answer", "created_at"])
        sheet.append_row([question_text, ans, datetime.utcnow().isoformat()])
        logger.info("FAQ recorded in Google Sheets")
except Exception as e:
    logger.exception("Failed to record FAQ in Google Sheets: %s", e)
```

**Missing**: No logic to check existing FAQs before forwarding to admin

### **2. FAQ Search Logic Missing**
**Problem**: No similarity matching for questions
**Impact**: Can't identify similar questions to provide auto-answers

### **3. Google Sheets Integration Issues**
**Problem**: FAQ recording may fail silently
**Impact**: FAQs not recorded, no auto-response capability

## **Testing Steps**

### **To Test Current Functionality**
1. Student asks question: "What is the deadline for Module 1?"
2. Question forwarded to questions group with "Answer" button
3. Admin clicks "Answer" button
4. Admin types: "The deadline is next Friday"
5. **Expected**: Student receives answer, FAQ recorded in Google Sheets

### **To Test FAQ Auto-Response (After Fix)**
1. Student asks: "What is the deadline for Module 1?"
2. Admin answers and FAQ is recorded
3. Another student asks: "When is Module 1 due?"
4. **Expected**: Bot should auto-respond with FAQ answer

## **Recommended Fixes**

### **Fix 1: Implement FAQ Auto-Response**
```python
async def ask_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text or len(update.message.text.strip()) == 0:
        await update.message.reply_text("Empty question. Try again.")
        return ASK_QUESTION
    
    question_text = update.message.text.strip()
    
    # Check for similar questions in FAQ
    similar_answer = await check_faq_for_similar_question(question_text)
    if similar_answer:
        await update.message.reply_text(f"Here's a similar question I found:\n\nQ: {similar_answer['question']}\nA: {similar_answer['answer']}", 
                                      reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END
    
    # No similar question found, proceed with normal flow
    qid = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("INSERT INTO questions (question_id, username, telegram_id, question, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (qid, update.effective_user.username or update.effective_user.full_name, update.effective_user.id, question_text, "Open", timestamp))
        db_conn.commit()
    
    # Forward to questions group with Answer button
    if QUESTIONS_GROUP_ID:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Answer", callback_data=f"answer_{qid}")]])
        try:
            await telegram_app.bot.send_message(chat_id=QUESTIONS_GROUP_ID, text=f"Question from {update.effective_user.full_name}: {question_text}", reply_markup=kb)
        except Exception:
            logger.exception("Failed to forward question to questions group")
    
    await update.message.reply_text("Question sent! We'll get back to you.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END
```

### **Fix 2: FAQ Similarity Check Function**
```python
async def check_faq_for_similar_question(question_text: str, similarity_threshold: float = 0.7) -> Optional[Dict[str, str]]:
    """Check if a similar question exists in FAQ"""
    try:
        if not gs_sheet:
            return None
        
        # Get FAQ sheet
        try:
            sheet = gs_sheet.worksheet("FAQ")
        except Exception:
            return None
        
        # Get all FAQ entries
        faq_records = sheet.get_all_records()
        
        # Simple similarity check (can be enhanced with NLP)
        question_lower = question_text.lower()
        for record in faq_records:
            if 'question' in record and 'answer' in record:
                faq_question = record['question'].lower()
                
                # Calculate similarity (simple word overlap)
                similarity = calculate_similarity(question_lower, faq_question)
                if similarity >= similarity_threshold:
                    logger.info(f"Found similar FAQ: {record['question']} (similarity: {similarity})")
                    return {
                        'question': record['question'],
                        'answer': record['answer']
                    }
        
        return None
    except Exception as e:
        logger.exception("Error checking FAQ for similar questions: %s", e)
        return None

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts (simple word overlap)"""
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union) if union else 0.0
```

### **Fix 3: Enhanced FAQ Recording**
```python
async def record_faq_in_sheets(question_text: str, answer_text: str) -> bool:
    """Record FAQ in Google Sheets with error handling"""
    try:
        if not gs_sheet:
            logger.warning("Google Sheets not configured - FAQ not recorded")
            return False
        
        # Get or create FAQ sheet
        try:
            sheet = gs_sheet.worksheet("FAQ")
        except Exception:
            sheet = gs_sheet.add_worksheet("FAQ", rows=100, cols=10)
            sheet.append_row(["question", "answer", "created_at"])
            logger.info("Created new FAQ worksheet")
        
        # Record FAQ
        sheet.append_row([question_text, answer_text, datetime.utcnow().isoformat()])
        logger.info("FAQ recorded in Google Sheets")
        return True
        
    except Exception as e:
        logger.exception("Failed to record FAQ in Google Sheets: %s", e)
        return False

# Update answer_receive function
async def answer_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qid = context.user_data.get('answer_question_id')
    if not qid:
        await update.message.reply_text("No question in progress.")
        return ConversationHandler.END
    
    # Get question info
    async with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT telegram_id, question FROM questions WHERE question_id = ?", (qid,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Question not found.")
            return ConversationHandler.END
        student_tg, question_text = row
        # Save answer as text for simplicity
        ans = update.message.text or "[non-text answer]"
        cur.execute("UPDATE questions SET answer = ?, answered_by = ?, answered_at = ?, status = ? WHERE question_id = ?", 
                   (ans, update.effective_user.id, datetime.utcnow().isoformat(), "Answered", qid))
        db_conn.commit()
    
    # Send answer to student
    try:
        await telegram_app.bot.send_message(chat_id=student_tg, text=f"Answer to your question: {ans}")
    except Exception:
        logger.exception("Failed to send answer to student")
    
    # Record FAQ in Google Sheets with enhanced error handling
    faq_recorded = await record_faq_in_sheets(question_text, ans)
    
    if faq_recorded:
        await update.message.reply_text("Answer sent and FAQ recorded!")
    else:
        await update.message.reply_text("Answer sent! (FAQ recording failed)")
    
    context.user_data.pop('answer_question_id', None)
    return ConversationHandler.END
```

### **Fix 4: Admin FAQ Management Commands**
```python
async def list_faqs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List recent FAQs for admin"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to perform this action.")
        return
    
    try:
        if not gs_sheet:
            await update.message.reply_text("Google Sheets not configured.")
            return
        
        sheet = gs_sheet.worksheet("FAQ")
        faq_records = sheet.get_all_records()
        
        if not faq_records:
            await update.message.reply_text("No FAQs found.")
            return
        
        # Show last 10 FAQs
        recent_faqs = faq_records[-10:]
        message = "📚 Recent FAQs:\n\n"
        
        for i, faq in enumerate(recent_faqs, 1):
            message += f"{i}. Q: {faq.get('question', 'N/A')[:50]}...\n"
            message += f"   A: {faq.get('answer', 'N/A')[:50]}...\n\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.exception("Error listing FAQs: %s", e)
        await update.message.reply_text("Error retrieving FAQs.")

# Add to handler registration
app_obj.add_handler(CommandHandler("list_faqs", list_faqs_cmd))
```

## **Environment Variables**
```bash
# Required
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_CREDENTIALS_JSON=your_credentials_json

# Optional (for FAQ similarity)
FAQ_SIMILARITY_THRESHOLD=0.7
```

## **Benefits of Fixes**
1. **Reduced Admin Workload**: Auto-respond to similar questions
2. **Better User Experience**: Students get instant answers for common questions
3. **FAQ Management**: Admins can view and manage FAQs
4. **Reliable Recording**: Enhanced error handling for FAQ storage

## **Testing After Fixes**
1. **FAQ Auto-Response**: Test with similar questions
2. **FAQ Recording**: Test FAQ storage in Google Sheets
3. **Admin Commands**: Test `/list_faqs` command
4. **Error Handling**: Test with Google Sheets unavailable
5. **Similarity Matching**: Test with various question phrasings

---
**Last Updated**: $(date)
**Status**: Needs FAQ auto-response implementation
**Priority**: Medium (improves admin efficiency)
