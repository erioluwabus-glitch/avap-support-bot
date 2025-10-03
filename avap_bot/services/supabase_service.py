"""
Supabase service for database operations
"""
import os
import logging
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Global client instance
supabase_client: Optional[Client] = None


def _clean_supabase_url(url: str) -> str:
    """Validate and clean Supabase URL format"""
    if not url:
        raise ValueError("SUPABASE_URL is required")
    
    # Strip any trailing slashes
    cleaned_url = url.rstrip('/')
    
    if not cleaned_url.startswith('https://'):
        cleaned_url = f"https://{cleaned_url}"
    
    if not cleaned_url.endswith('.supabase.co'):
        raise ValueError("Invalid Supabase URL format")
    
    return cleaned_url


def validate_supabase_credentials():
    """Validate Supabase credentials"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    
    if not SUPABASE_KEY.startswith('eyJ'):
        raise ValueError("Invalid Supabase key format")
    
    if len(SUPABASE_KEY) < 100:
        raise ValueError("Supabase key appears to be too short")


def check_tables_exist():
    """Check if all required tables exist"""
    required_tables = ['verified_users', 'pending_verifications', 'match_requests']
    
    for table in required_tables:
        try:
            client = get_supabase()
            client.table(table).select('*').limit(1).execute()
        except Exception as e:
            logger.warning(f"Table {table} may not exist: {e}")


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
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return supabase_client


def add_pending_verification(data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a row into pending_verifications"""
    client = get_supabase()
    try:
        res = client.table("pending_verifications").insert(data).execute()
        if res.data:
            logger.info(f"Added pending verification: {data.get('name', 'Unknown')}")
            return res.data[0]
        else:
            raise Exception("No data returned from insert")
    except Exception as e:
        logger.error(f"❌ Error adding pending verification: {str(e)}")
        raise


def find_verified_by_telegram(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Find verified user by telegram ID"""
    try:
        client = get_supabase()
        res = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.exception("Supabase find_verified_by_telegram error: %s", e)
        return None


def find_pending_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search pending_verifications by email or phone"""
    try:
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
    except Exception as e:
        logger.exception("Supabase find_pending_by_email_or_phone error: %s", e)
        return []


def find_verified_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search verified_users by email or phone"""
    try:
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
    except Exception as e:
        logger.exception("Supabase find_verified_by_email_or_phone error: %s", e)
        return []


def find_verified_by_name(name: str) -> List[Dict[str, Any]]:
    """Search verified_users by name (case-insensitive)"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("*").ilike("name", f"%{name}%").eq("status", "verified").execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase find_verified_by_name error: %s", e)
        return []


def promote_pending_to_verified(pending_id: int, telegram_id: int) -> Dict[str, Any]:
    """Promote pending verification to verified user"""
    client = get_supabase()
    try:
        # Fetch pending row
        r = client.table("pending_verifications").select("*").eq("id", pending_id).execute()
        if not r.data:
            raise Exception("Pending verification not found")
        
        row = r.data[0]
        verified_payload = {
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "telegram_id": telegram_id,
            "status": "verified",
            "verified_at": datetime.now(timezone.utc).isoformat()
        }
        ins = client.table("verified_users").insert(verified_payload).execute()
        
        # Optionally delete pending row:
        client.table("pending_verifications").delete().eq("id", pending_id).execute()
        
        return ins.data[0]
    except Exception as e:
        logger.exception("Supabase promote_pending_to_verified error: %s", e)
        raise


def remove_verified_user(identifier: str) -> bool:
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
        logger.exception("Supabase remove_verified_user error: %s", e)
        return False


def remove_verified_by_identifier(identifier: str) -> bool:
    """Alias for remove_verified_user for backward compatibility"""
    return remove_verified_user(identifier)


def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("*").eq("status", "verified").execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase get_all_verified_users error: %s", e)
        return []


def add_match_request(telegram_id: int, username: str) -> str:
    """Add match request and return match_id"""
    client = get_supabase()
    match_id = str(uuid.uuid4())
    payload = {
        "match_id": match_id,
        "telegram_id": telegram_id,
        "username": username,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    res = client.table("match_requests").insert(payload).execute()
    try:
        return match_id
    except Exception as e:
        logger.exception("Supabase add_match_request error: %s", e)
        raise


def pop_match_request(exclude_id: int) -> Optional[Dict[str, Any]]:
    """Pop a match request excluding the given telegram_id"""
    client = get_supabase()
    try:
        # Get a random pending request that's not from the same user
        res = client.table("match_requests").select("*").neq("telegram_id", exclude_id).eq("status", "pending").limit(1).execute()
        if not res.data:
            return None
        
        match_request = res.data[0]
        # Mark as matched
        client.table("match_requests").update({"status": "matched"}).eq("match_id", match_request["match_id"]).execute()
        return match_request
    except Exception as e:
        logger.exception("Supabase pop_match_request error: %s", e)
        return None


def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified by telegram_id"""
    try:
        client = get_supabase()
        res = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        logger.exception("Supabase check_verified_user error: %s", e)
        return None


def add_assignment_submission(telegram_id: int, username: str, module: str, file_id: str, file_name: str, submission_type: str) -> Dict[str, Any]:
    """Add a new assignment submission"""
    client = get_supabase()
    try:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "module": module,
            "file_id": file_id,
            "file_name": file_name,
            "submission_type": submission_type,
            "status": "submitted",
            "submitted_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("assignments").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.exception("Supabase add_assignment_submission error: %s", e)
        raise


def get_student_assignments(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all assignments for a student"""
    client = get_supabase()
    try:
        res = client.table("assignments").select("*").eq("telegram_id", telegram_id).execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase get_student_assignments error: %s", e)
        return []


def update_assignment_grade(submission_id: int, grade: int, comment: Optional[str] = None) -> bool:
    """Update assignment with grade and comments"""
    client = get_supabase()
    try:
        update_data = {
            "grade": grade,
            "status": "graded",
            "graded_at": datetime.now(timezone.utc).isoformat()
        }
        if comment:
            update_data["comment"] = comment
        
        res = client.table("assignments").update(update_data).eq("id", submission_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.exception("Supabase update_assignment_grade error: %s", e)
        return False


def add_win(telegram_id: int, username: str, file_id: str, file_name: str, win_type: str) -> Dict[str, Any]:
    """Add a new win"""
    client = get_supabase()
    try:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "file_id": file_id,
            "file_name": file_name,
            "win_type": win_type,
            "shared_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("wins").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.exception("Supabase add_win error: %s", e)
        raise


def get_student_wins(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all wins for a student"""
    client = get_supabase()
    try:
        res = client.table("wins").select("*").eq("telegram_id", telegram_id).execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase get_student_wins error: %s", e)
        return []


def add_question(telegram_id: int, username: str, question_text: str, file_id: Optional[str] = None, file_name: Optional[str] = None) -> Dict[str, Any]:
    """Add a new question"""
    client = get_supabase()
    try:
        payload = {
            "telegram_id": telegram_id,
            "username": username,
            "question_text": question_text,
            "file_id": file_id,
            "file_name": file_name,
            "status": "pending",
            "asked_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("questions").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.exception("Supabase add_question error: %s", e)
        raise


def get_student_questions(telegram_id: int) -> List[Dict[str, Any]]:
    """Get all questions for a student"""
    client = get_supabase()
    try:
        res = client.table("questions").select("*").eq("telegram_id", telegram_id).execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase get_student_questions error: %s", e)
        return []


def update_question_answer(question_id: int, answer: str) -> bool:
    """Update question with answer"""
    client = get_supabase()
    try:
        update_data = {
            "answer": answer,
            "status": "answered",
            "answered_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("questions").update(update_data).eq("id", question_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.exception("Supabase update_question_answer error: %s", e)
        return False


def get_faqs() -> List[Dict[str, Any]]:
    """Get all FAQs for AI matching"""
    client = get_supabase()
    try:
        res = client.table("faqs").select("*").execute()
        return res.data or []
    except Exception as e:
        logger.exception("Supabase get_faqs error: %s", e)
        return []


def add_faq(question: str, answer: str) -> Dict[str, Any]:
    """Add a new FAQ"""
    client = get_supabase()
    try:
        payload = {
            "question": question,
            "answer": answer,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("faqs").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.exception("Supabase add_faq error: %s", e)
        raise


def get_tip_for_day(day_of_week: int) -> Optional[Dict[str, Any]]:
    """Get tip for specific day of week"""
    client = get_supabase()
    try:
        res = client.table("tips").select("*").eq("day_of_week", day_of_week).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception("Supabase get_tip_for_day error: %s", e)
        return None


def add_manual_tip(content: str, day_of_week: int) -> Dict[str, Any]:
    """Add a manual tip for specific day"""
    client = get_supabase()
    try:
        payload = {
            "content": content,
            "day_of_week": day_of_week,
            "tip_type": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res = client.table("tips").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        logger.exception("Supabase add_manual_tip error: %s", e)
        raise


def get_top_students() -> List[Dict[str, Any]]:
    """Get students with 3+ assignments and 3+ wins"""
    client = get_supabase()
    
    # Get all verified users
    users_res = client.table("verified_users").select("*").eq("status", "verified").execute()
    try:
        users = users_res.data or []
    except Exception as e:
        logger.exception("Supabase get_top_students error: %s", e)
        return []
    
    top_students = []
    for user in users:
        telegram_id = user.get("telegram_id")
        if not telegram_id:
            continue
        
        # Count assignments
        assignments_res = client.table("assignments").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        assignment_count = assignments_res.count or 0
        
        # Count wins
        wins_res = client.table("wins").select("id", count="exact").eq("telegram_id", telegram_id).execute()
        wins_count = wins_res.count or 0
        
        if assignment_count >= 3 and wins_count >= 3:
            top_students.append({
                "telegram_id": telegram_id,
                "username": user.get("username", "unknown"),
                "name": user.get("name", "Unknown"),
                "assignments": assignment_count,
                "wins": wins_count,
                "joined_at": user.get("verified_at", "Unknown")
            })
    
    return top_students


def get_all_verified_telegram_ids() -> List[int]:
    """Get all verified user telegram IDs for broadcasting"""
    client = get_supabase()
    try:
        res = client.table("verified_users").select("telegram_id").eq("status", "verified").execute()
        return [user["telegram_id"] for user in (res.data or []) if user.get("telegram_id")]
    except Exception as e:
        logger.exception("Supabase get_all_verified_telegram_ids error: %s", e)
        return []


def update_user_badge(telegram_id: int, badge: str) -> bool:
    """Update user badge"""
    client = get_supabase()
    try:
        res = client.table("verified_users").update({"badge": badge}).eq("telegram_id", telegram_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.exception("Supabase update_user_badge error: %s", e)
        return False


def get_assignment_by_id(assignment_id: int) -> Optional[Dict[str, Any]]:
    """Get assignment by ID"""
    client = get_supabase()
    try:
        res = client.table("assignments").select("*").eq("id", assignment_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.exception("Supabase get_assignment_by_id error: %s", e)
        return None