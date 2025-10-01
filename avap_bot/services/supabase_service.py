"""
Supabase service for verification operations - Complete CRUD implementation
"""
import os
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from supabase import create_client, Client
from postgrest.exceptions import APIError

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client: Optional[Client] = None


def validate_supabase_url(url: str) -> str:
    """Validate and clean Supabase URL format"""
    if not url:
        raise ValueError("Supabase URL cannot be empty")
    
    # Strip any trailing slashes
    cleaned_url = url.rstrip('/')
    
    if not cleaned_url.startswith('https://'):
        raise ValueError("Supabase URL must start with https://")
    
    if not cleaned_url.endswith('.supabase.co'):
        raise ValueError("Supabase URL must end with .supabase.co")
        
    return cleaned_url

def validate_supabase_credentials() -> None:
    """Validate Supabase credentials"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        
    if not SUPABASE_KEY.startswith('eyJ'):
        raise ValueError("Invalid SUPABASE_KEY format - should start with 'eyJ'")
        
    if len(SUPABASE_KEY) < 100:
        raise ValueError("SUPABASE_KEY appears too short - check key format")

def check_required_tables(client: Client) -> None:
    """Check if all required tables exist"""
    required_tables = ['verified_users', 'pending_verifications', 'match_requests']
    
    for table in required_tables:
        try:
            # Test query to check if table exists
            client.table(table).select('count', count='exact').limit(1).execute()
            logger.info(f"✅ Table '{table}' exists")
        except Exception as e:
            logger.error(f"❌ Table '{table}' not found or inaccessible")
            raise RuntimeError(f"Required table '{table}' not found in database. Please create the table first.")

def init_supabase() -> Client:
    """Initialize Supabase client with optimized startup"""
    global supabase_client
    
    if supabase_client:
        return supabase_client
        
    try:
        validate_supabase_credentials()
        
        logger.info("🚀 Initializing Supabase connection...")
        test_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Quick connection test
        test_client.table('verified_users').select('count', count='exact').limit(1).execute()
        
        supabase_client = test_client
        logger.info("✅ Supabase connected successfully")
        return supabase_client
            
    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {str(e)}")
        raise


def get_supabase() -> Client:
    """Get or initialize Supabase client with connection check"""
    global supabase_client
    if supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.error("❌ Missing Supabase credentials")
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
            
        try:
            logger.info("🔄 Initializing Supabase connection...")
            supabase_client = create_client(SUPABASE_URL.rstrip('/'), SUPABASE_KEY)
            # Test connection
            supabase_client.table('verified_users').select('count', count='exact').limit(1).execute()
            logger.info("✅ Supabase connection successful")
        except Exception as e:
            logger.error(f"❌ Supabase connection failed: {str(e)}")
            raise
            
    return supabase_client


def add_pending_verification(record: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a row into pending_verifications"""
    client = get_supabase()
    try:
        logger.info(f"➡️ Adding pending verification for: {record.get('name', 'Unknown')}")
        
        # Sanitize payload
        payload = {
            'name': record.get('name'),
            'email': record.get('email'),
            'phone': record.get('phone'),
            'telegram_id': record.get('telegram_id'),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        result = client.table('pending_verifications').insert(payload).execute()
        
        if result.data:
            logger.info(f"✅ Added pending verification with ID: {result.data[0].get('id')}")
            return result.data[0]
        else:
            logger.error("❌ No data returned from verification insert")
            raise RuntimeError("Failed to insert verification")
            
    except Exception as e:
        logger.error(f"❌ Error adding pending verification: {str(e)}")
        raise


def find_verified_by_telegram(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Find verified user by telegram ID"""
    client = get_supabase()
    res = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.exception("Supabase find_verified_by_telegram error: %s", e)
        return None


def find_pending_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search pending_verifications by email or phone"""
    client = get_supabase()
    results = []
    
    if email:
        res = client.table("pending_verifications").select("*").eq("email", email).execute()
        if res.data:
            results.extend(res.data)
    
    if phone:
        res = client.table("pending_verifications").select("*").eq("phone", phone).execute()
        if res.data:
            results.extend(res.data)
    
    return results


def find_verified_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search verified_users by email or phone"""
    client = get_supabase()
    results = []
    
    if email:
        res = client.table("verified_users").select("*").eq("email", email).eq("status", "verified").execute()
        if res.data:
            results.extend(res.data)
    
    if phone:
        res = client.table("verified_users").select("*").eq("phone", phone).eq("status", "verified").execute()
        if res.data:
            results.extend(res.data)
    
    return results

def find_verified_by_name(name: str) -> List[Dict[str, Any]]:
    """Search verified_users by name (case-insensitive)"""
    client = get_supabase()
    res = client.table("verified_users").select("*").ilike("name", f"%{name}%").eq("status", "verified").execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("Supabase find_verified_by_name error: %s", e)
        return []


def promote_pending_to_verified(pending_id: Any, telegram_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Promote pending verification to verified user"""
    client = get_supabase()
    # Fetch pending row
    r = client.table("pending_verifications").select("*").eq("id", pending_id).execute()
    if not r.data:
        logger.error("pending row not found: %s", pending_id)
        return None
    row = r.data[0]
    verified_payload = {
        "name": row.get("name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "telegram_id": telegram_id or row.get("telegram_id"),  # may be None until student provides DM
        "status": "verified",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    ins = client.table("verified_users").insert(verified_payload).execute()
    try:
        if ins.data and len(ins.data) > 0:
            # Optionally delete pending row:
            client.table("pending_verifications").delete().eq("id", pending_id).execute()
            return ins.data[0]
        return None
    except Exception as e:
        logger.error("Failed to promote pending to verified: %s", e)
        return None


def remove_verified_by_identifier(identifier: str) -> bool:
    """Identifier may be email, phone, or full name. Return True if deleted."""
    client = get_supabase()
    try:
        # Try email exact match
        res = client.table("verified_users").delete().eq("email", identifier).execute()
        if res.data:
            return True
        
        # Try phone
        res = client.table("verified_users").delete().eq("phone", identifier).execute()
        if res.data:
            return True
        
        # Try name (less exact)
        res = client.table("verified_users").delete().eq("name", identifier).execute()
        return bool(res.data)
    except Exception as e:
        logger.debug("remove by identifier error: %s", e)
        return False


def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users"""
    client = get_supabase()
    res = client.table("verified_users").select("*").eq("status", "verified").execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("get_all_verified_users error: %s", e)
        return []


def add_match_request(telegram_id: int) -> str:
    """Add match request and return match_id"""
    client = get_supabase()
    match_id = str(uuid.uuid4())
    payload = {
        "telegram_id": telegram_id,
        "match_id": match_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending"
    }
    res = client.table("match_requests").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        raise RuntimeError("Match request failed: No data returned")
    except Exception as e:
        logger.error("Failed to add match request: %s", e)
        raise RuntimeError(f"Match request failed: {e}")

def pop_match_request(exclude_id: int) -> Optional[Dict[str, Any]]:
    """Pop a match request excluding the given telegram_id"""
    client = get_supabase()
    # Get a random pending request that's not from the same user
    res = client.table("match_requests").select("*").neq("telegram_id", exclude_id).eq("status", "pending").limit(1).execute()
    if not res.data:
        return None
    
    match_request = res.data[0]
    # Mark as matched
    client.table("match_requests").update({"status": "matched"}).eq("match_id", match_request["match_id"]).execute()
    return match_request

def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified by telegram_id"""
    try:
        supabase = get_supabase()
        res = supabase.table('verified_users').select('*').eq('telegram_id', telegram_id).eq('status', 'verified').execute()
        
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
        
    except Exception as e:
        logger.exception("Supabase check_verified_user error: %s", e)
        return None


# Assignment functions
def add_assignment(assignment_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new assignment submission"""
    client = get_supabase()
    payload = assignment_data.copy()
    if 'submitted_at' in payload and isinstance(payload['submitted_at'], datetime):
        payload['submitted_at'] = payload['submitted_at'].isoformat()
    
    res = client.table("assignments").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("Assignment insert failed: No data returned")
    except Exception as e:
        logger.error("Failed to add assignment: %s", e)
        raise RuntimeError(f"Assignment insert failed: {e}")


def get_student_assignments(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all assignments for a student"""
    client = get_supabase()
    res = client.table("assignments").select("*").eq("telegram_id", telegram_id).order("submitted_at", desc=True).execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("Failed to get student assignments: %s", e)
        return []


def update_assignment_grade(assignment_id: str, grade: int, comments: str = None) -> bool:
    """Update assignment with grade and comments"""
    client = get_supabase()
    update_data = {
        "grade": grade,
        "status": "graded",
        "graded_at": datetime.now(timezone.utc).isoformat()
    }
    if comments:
        update_data["comments"] = comments
    
    res = client.table("assignments").update(update_data).eq("id", assignment_id).execute()
    try:
        return res.data is not None
    except Exception as e:
        logger.error("Failed to update assignment grade: %s", e)
        return False


# Win functions
def add_win(win_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new win"""
    client = get_supabase()
    payload = win_data.copy()
    if 'shared_at' in payload and isinstance(payload['shared_at'], datetime):
        payload['shared_at'] = payload['shared_at'].isoformat()
    
    res = client.table("wins").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("Win insert failed: No data returned")
    except Exception as e:
        logger.error("Failed to add win: %s", e)
        raise RuntimeError(f"Win insert failed: {e}")


def get_student_wins(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all wins for a student"""
    client = get_supabase()
    res = client.table("wins").select("*").eq("telegram_id", telegram_id).order("shared_at", desc=True).execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("Failed to get student wins: %s", e)
        return []


# Question functions
def add_question(question_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add a new question"""
    client = get_supabase()
    payload = question_data.copy()
    if 'asked_at' in payload and isinstance(payload['asked_at'], datetime):
        payload['asked_at'] = payload['asked_at'].isoformat()
    
    res = client.table("questions").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("Question insert failed: No data returned")
    except Exception as e:
        logger.error("Failed to add question: %s", e)
        raise RuntimeError(f"Question insert failed: {e}")


def get_student_questions(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all questions for a student"""
    client = get_supabase()
    res = client.table("questions").select("*").eq("telegram_id", telegram_id).order("asked_at", desc=True).execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("Failed to get student questions: %s", e)
        return []


def update_question_answer(question_id: str, answer: str) -> bool:
    """Update question with answer"""
    client = get_supabase()
    update_data = {
        "answer": answer,
        "status": "answered",
        "answered_at": datetime.now(timezone.utc).isoformat()
    }
    
    res = client.table("questions").update(update_data).eq("id", question_id).execute()
    try:
        return res.data is not None
    except Exception as e:
        logger.error("Failed to update question answer: %s", e)
        return False


# FAQ functions
def get_faqs() -> List[Dict[str, Any]]:
    """Get all FAQs for AI matching"""
    client = get_supabase()
    res = client.table("faqs").select("*").execute()
    try:
        return res.data or []
    except Exception as e:
        logger.exception("Failed to get FAQs: %s", e)
        return []


def add_faq(question: str, answer: str, category: str = "general") -> Dict[str, Any]:
    """Add a new FAQ"""
    client = get_supabase()
    payload = {
        "question": question,
        "answer": answer,
        "category": category
    }
    
    res = client.table("faqs").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("FAQ insert failed: No data returned")
    except Exception as e:
        logger.error("Failed to add FAQ: %s", e)
        raise RuntimeError(f"FAQ insert failed: {e}")


# Tips functions
def get_tip_for_day(day_of_week: int) -> Optional[Dict[str, Any]]:
    """Get tip for specific day of week"""
    client = get_supabase()
    res = client.table("tips").select("*").eq("day_of_week", day_of_week).order("is_manual", desc=True).limit(1).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to get tip: %s", e)
        return None


def add_manual_tip(tip_text: str, day_of_week: int) -> Dict[str, Any]:
    """Add a manual tip for specific day"""
    client = get_supabase()
    payload = {
        "tip_text": tip_text,
        "day_of_week": day_of_week,
        "is_manual": True
    }
    
    res = client.table("tips").insert(payload).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        raise RuntimeError("Manual tip insert failed: No data returned")
    except Exception as e:
        logger.error("Failed to add manual tip: %s", e)
        raise RuntimeError(f"Manual tip insert failed: {e}")


# Admin functions
def get_top_students() -> List[Dict[str, Any]]:
    """Get students with 3+ assignments and 3+ wins"""
    client = get_supabase()
    
    # Get all verified users
    users_res = client.table("verified_users").select("*").eq("status", "verified").execute()
    try:
        users = users_res.data or []
    except Exception as e:
        logger.exception("Failed to get verified users: %s", e)
        return []
    
    top_students = []
    for user in users:
        telegram_id = user.get('telegram_id')
        if not telegram_id:
            continue
            
        # Count assignments
        assignments_res = client.table("assignments").select("id").eq("telegram_id", telegram_id).execute()
        assignment_count = len(assignments_res.data or [])
        
        # Count wins
        wins_res = client.table("wins").select("id").eq("telegram_id", telegram_id).execute()
        wins_count = len(wins_res.data or [])
        
        if assignment_count >= 3 and wins_count >= 3:
            user['assignment_count'] = assignment_count
            user['wins_count'] = wins_count
            top_students.append(user)
    
    return top_students


def get_all_verified_telegram_ids() -> List[int]:
    """Get all verified user telegram IDs for broadcasting"""
    client = get_supabase()
    res = client.table("verified_users").select("telegram_id").eq("status", "verified").not_.is_("telegram_id", "null").execute()
    try:
        return [user['telegram_id'] for user in res.data or [] if user.get('telegram_id')]
    except Exception as e:
        logger.exception("Failed to get verified telegram IDs: %s", e)
        return []


# Update user badge
def update_user_badge(telegram_id: int, badge: str) -> bool:
    """Update user badge"""
    client = get_supabase()
    res = client.table("verified_users").update({"badge": badge}).eq("telegram_id", telegram_id).execute()
    try:
        return res.data is not None
    except Exception as e:
        logger.error("Failed to update user badge: %s", e)
        return False


def get_assignment_by_id(assignment_id: str) -> Optional[Dict[str, Any]]:
    """Get assignment by ID"""
    client = get_supabase()
    res = client.table("assignments").select("*").eq("id", assignment_id).execute()
    try:
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to get assignment: %s", e)
        return None