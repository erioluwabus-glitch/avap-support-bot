# AVAP Support Bot - Technical Architecture Guide

## 🏗️ **SYSTEM ARCHITECTURE**

### **Core Components**
```
┌─────────────────────────────────────────────────────────────┐
│                    AVAP Support Bot                        │
├─────────────────────────────────────────────────────────────┤
│  Frontend: Telegram Bot API                                │
│  Backend: FastAPI + Python                                │
│  Database: Supabase (PostgreSQL)                          │
│  Storage: Google Sheets                                   │
│  CRM: Systeme.io API                                      │
│  Deployment: Render (Free Tier)                           │
│  Monitoring: Custom + External Pingers                    │
└─────────────────────────────────────────────────────────────┘
```

### **Data Flow**
```
User → Telegram → Bot → FastAPI → Supabase → Google Sheets
                    ↓
                Systeme.io API
                    ↓
                Admin Groups
```

---

## 🔧 **TECHNICAL STACK**

### **Backend Technologies**
- **Python 3.11**: Core language
- **FastAPI**: Web framework
- **python-telegram-bot**: Telegram integration
- **asyncio**: Asynchronous programming
- **httpx**: HTTP client
- **psutil**: System monitoring

### **Database & Storage**
- **Supabase**: Primary database (PostgreSQL)
- **Google Sheets**: Data backup and reporting
- **Systeme.io**: Contact management and CRM

### **External Services**
- **Telegram Bot API**: Bot communication
- **Render**: Hosting platform
- **External Pingers**: Uptime monitoring
- **Google APIs**: Sheets integration

---

## 📁 **CODEBASE STRUCTURE**

### **Main Directories**
```
avap_bot/
├── handlers/          # Telegram command handlers
├── services/          # External service integrations
├── utils/             # Utility functions
├── features/          # Feature modules
├── web/              # Web endpoints
├── tests/            # Test files
└── bot.py            # Main application
```

### **Handler Modules**
```
handlers/
├── student.py        # Student features
├── admin.py          # Admin management
├── admin_tools.py    # Admin tools
├── questions.py       # Question handling
├── grading.py        # Assignment grading
├── answer.py         # Answer questions
├── tips.py           # Daily tips
├── matching.py       # Student matching
└── webhook.py        # Webhook handling
```

### **Service Modules**
```
services/
├── supabase_service.py    # Database operations
├── sheets_service.py      # Google Sheets integration
├── systeme_service.py     # Systeme.io API
├── notifier.py            # Admin notifications
└── systeme_worker.py      # Background tasks
```

### **Utility Modules**
```
utils/
├── chat_utils.py          # Chat type detection
├── validators.py          # Input validation
├── memory_monitor.py      # Memory monitoring
├── distributed_lock.py    # Distributed locking
├── cooldown_manager.py    # Rate limiting
├── http_client.py         # HTTP utilities
└── run_blocking.py        # Async utilities
```

---

## 🗄️ **DATABASE SCHEMA**

### **Core Tables**
```sql
-- User Management
verified_users (
    id, telegram_id, name, email, phone, 
    status, created_at, updated_at
)

pending_verifications (
    id, telegram_id, name, email, phone,
    status, created_at, updated_at
)

-- Content Management
submissions (
    id, telegram_id, module, type, content,
    file_id, created_at, status
)

wins (
    id, telegram_id, type, content, file_id,
    created_at, status
)

questions (
    id, telegram_id, type, content, file_id,
    created_at, status, answered
)

-- System Management
locks (
    key, token, expires_at, created_at
)

cooldown_states (
    key, cooldown_until, created_at, updated_at
)

broadcasts (
    id, content, type, sent_count, created_at
)
```

### **Indexes**
```sql
-- Performance indexes
CREATE INDEX idx_verified_users_telegram_id ON verified_users(telegram_id);
CREATE INDEX idx_pending_verifications_email ON pending_verifications(email);
CREATE INDEX idx_submissions_telegram_id ON submissions(telegram_id);
CREATE INDEX idx_locks_expires_at ON locks(expires_at);
CREATE INDEX idx_cooldown_states_cooldown_until ON cooldown_states(cooldown_until);
```

---

## 🔄 **CONVERSATION FLOWS**

### **Student Verification Flow**
```
1. User sends /start
2. Bot requests email/phone
3. User provides identifier
4. Bot searches pending_verifications
5. Admin verifies in verification group
6. Bot promotes to verified_users
7. User gets main menu access
```

### **Assignment Submission Flow**
```
1. User clicks "📝 Submit Assignment"
2. Bot requests module selection
3. User selects module
4. Bot requests submission type
5. User chooses text/audio/video
6. User submits content
7. Bot forwards to assignment group
8. Admin grades via /grade command
```

### **Question Answering Flow**
```
1. User clicks "❓ Ask Question"
2. User submits question
3. Bot forwards to questions group
4. Admin answers via /answer command
5. Bot sends answer to user
```

---

## 🔒 **SECURITY IMPLEMENTATION**

### **Authentication**
```python
# Admin verification
def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_USER_ID

# Group-specific commands
filters.Chat(chat_id=VERIFICATION_GROUP_ID)

# Token-based authentication
ADMIN_RESET_TOKEN = os.getenv("ADMIN_RESET_TOKEN")
```

### **Data Protection**
```python
# No sensitive data in logs
logger.info(f"User {user_id} submitted assignment")

# Secure environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Input validation
def validate_email(email: str) -> bool:
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email)
```

### **Rate Limiting**
```python
# Cooldown management
def is_cooldown_active(key: str) -> bool:
    cooldown_until = get_cooldown_state(key)
    return cooldown_until and cooldown_until > datetime.now(timezone.utc)

# Distributed locking
def acquire_lock(lock_name: str, ttl_seconds: int = 300) -> Optional[str]:
    # Prevent multiple instances from running same task
```

---

## 🚀 **DEPLOYMENT ARCHITECTURE**

### **Render Configuration**
```yaml
# Build command
pip install -r requirements.txt

# Start command
python -m avap_bot.bot

# Environment variables
BOT_TOKEN: <telegram_bot_token>
SUPABASE_URL: <supabase_url>
SUPABASE_KEY: <supabase_key>
ADMIN_USER_ID: <admin_telegram_id>
ASSIGNMENT_GROUP_ID: <assignment_group_id>
SUPPORT_GROUP_ID: <support_group_id>
QUESTIONS_GROUP_ID: <questions_group_id>
VERIFICATION_GROUP_ID: <verification_group_id>
```

### **Keep-Alive System**
```python
# Internal self-ping
async def background_keepalive():
    while True:
        await client.get(f"{render_url}/health")
        await asyncio.sleep(540)  # 9 minutes

# External pingers
# - Cron-Job.org: Every 10 minutes
# - Pulsetic: Every 10 minutes
# - Better Stack: Every 10 minutes
```

### **Monitoring**
```python
# Memory monitoring
def get_memory_usage() -> float:
    process = psutil.Process()
    return process.memory_info().rss / (1024 * 1024)

# Health checks
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "memory_usage_mb": get_memory_usage(),
        "database_connected": True
    }
```

---

## 🔧 **INTEGRATION ARCHITECTURE**

### **Google Sheets Integration**
```python
# Service class
class SheetsService:
    def __init__(self):
        self.client = gspread.service_account()
        self.spreadsheet = self.client.open("AVAPSupport")
    
    def append_submission(self, data: Dict[str, Any]):
        worksheet = self.spreadsheet.worksheet("submissions")
        worksheet.append_row(data)
```

### **Systeme.io Integration**
```python
# API client
class SystemeService:
    def __init__(self):
        self.api_key = os.getenv("SYSTEME_API_KEY")
        self.headers = {"X-API-Key": self.api_key}
    
    def create_contact(self, email: str, data: Dict[str, Any]):
        response = requests.post(
            f"{self.base_url}/api/contacts",
            headers=self.headers,
            json={"email": email, **data}
        )
```

### **Supabase Integration**
```python
# Database client
class SupabaseService:
    def __init__(self):
        self.client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
    
    def find_verified_by_telegram(self, telegram_id: int):
        return self.client.table("verified_users").select("*").eq("telegram_id", telegram_id).execute()
```

---

## 📊 **PERFORMANCE OPTIMIZATION**

### **Async Programming**
```python
# Async handlers
async def submit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Non-blocking operations
    await send_message_with_retry(bot, chat_id, text)
    await append_submission(data)
    await notify_admin_telegram(bot, message)
```

### **Connection Pooling**
```python
# HTTP client with connection reuse
async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.get(url)
```

### **Memory Management**
```python
# Memory monitoring
def cleanup_resources():
    gc.collect()
    # Clean up connections
    # Release memory
```

---

## 🔍 **ERROR HANDLING**

### **Exception Management**
```python
# Graceful error handling
try:
    await bot.send_message(chat_id, text)
except Exception as e:
    logger.error(f"Failed to send message: {e}")
    await notify_admin_telegram(bot, f"Error: {e}")
```

### **Retry Mechanisms**
```python
# Exponential backoff
async def send_message_with_retry(bot, chat_id: int, text: str, max_attempts: int = 3):
    for attempt in range(max_attempts):
        try:
            await bot.send_message(chat_id, text)
            return True
        except Exception as e:
            if "429" in str(e):
                await asyncio.sleep(2 ** attempt)
```

### **Logging**
```python
# Structured logging
logger.info(f"User {user_id} submitted assignment")
logger.warning(f"Rate limited: {error}")
logger.error(f"Database error: {error}")
```

---

## 🧪 **TESTING ARCHITECTURE**

### **Test Structure**
```
tests/
├── test_webhook.sh          # Webhook testing
├── check_admin_endpoints.sh # Admin endpoint testing
└── __init__.py
```

### **Testing Commands**
```bash
# Webhook test
curl -X POST https://your-bot.onrender.com/webhook/TOKEN \
  -H "Content-Type: application/json" \
  -d '{"update_id": 1, "message": {...}}'

# Health check
curl https://your-bot.onrender.com/health
```

---

## 📈 **SCALING CONSIDERATIONS**

### **Current Limitations**
- Render free tier: 750 hours/month
- Memory limit: 512MB
- Bandwidth: 100GB/month
- Single instance deployment

### **Scaling Strategies**
- External pingers for uptime
- Memory monitoring and cleanup
- Rate limiting and cooldowns
- Efficient database queries
- Connection pooling

### **Future Improvements**
- Multi-instance deployment
- Load balancing
- Database optimization
- Caching layer
- Microservices architecture

---

This technical architecture guide provides a comprehensive overview of the AVAP Support Bot's technical implementation, from database design to deployment strategies and performance optimization.
