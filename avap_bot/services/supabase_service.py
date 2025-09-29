"""
Supabase service for verification operations - Complete CRUD implementation
"""
import os
import logging
import uuid
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
    if res.error:
        logger.exception("Supabase find_verified_by_telegram error: %s", res.error)
        return None
    return (res.data or [None])[0]


def find_pending_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search pending_verifications by email or phone"""
    client = get_supabase()
    results = []
    
    if email:
        res = client.table("pending_verifications").select("*").eq("email", email).execute()
        if not res.error and res.data:
            results.extend(res.data)
    
    if phone:
        res = client.table("pending_verifications").select("*").eq("phone", phone).execute()
        if not res.error and res.data:
            results.extend(res.data)
    
    return results


def find_verified_by_email_or_phone(email: Optional[str] = None, phone: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search verified_users by email or phone"""
    client = get_supabase()
    results = []
    
    if email:
        res = client.table("verified_users").select("*").eq("email", email).eq("status", "verified").execute()
        if not res.error and res.data:
            results.extend(res.data)
    
    if phone:
        res = client.table("verified_users").select("*").eq("phone", phone).eq("status", "verified").execute()
        if not res.error and res.data:
            results.extend(res.data)
    
    return results

def find_verified_by_name(name: str) -> List[Dict[str, Any]]:
    """Search verified_users by name (case-insensitive)"""
    client = get_supabase()
    res = client.table("verified_users").select("*").ilike("name", f"%{name}%").eq("status", "verified").execute()
    if res.error:
        logger.exception("Supabase find_verified_by_name error: %s", res.error)
        return []
    return res.data or []


def promote_pending_to_verified(pending_id: Any, telegram_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Promote pending verification to verified user"""
    client = get_supabase()
    # Fetch pending row
    r = client.table("pending_verifications").select("*").eq("id", pending_id).execute()
    if r.error or not r.data:
        logger.error("pending row not found: %s %s", pending_id, r.error)
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
    if ins.error:
        logger.error("Failed to promote pending to verified: %s", ins.error)
        return None
    # Optionally delete pending row:
    client.table("pending_verifications").delete().eq("id", pending_id).execute()
    return (ins.data or [None])[0]


def remove_verified_by_identifier(identifier: str) -> bool:
    """Identifier may be email, phone, or full name. Return True if deleted."""
    client = get_supabase()
    # Try email exact match
    res = client.table("verified_users").delete().eq("email", identifier).execute()
    if res.error:
        logger.debug("remove by email error: %s", res.error)
    if res.data:
        return True
    # Try phone
    res = client.table("verified_users").delete().eq("phone", identifier).execute()
    if res.data:
        return True
    # Try name (less exact)
    res = client.table("verified_users").delete().eq("name", identifier).execute()
    return bool(res.data)


def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users"""
    client = get_supabase()
    res = client.table("verified_users").select("*").eq("status", "verified").execute()
    if res.error:
        logger.exception("get_all_verified_users error: %s", res.error)
        return []
    return res.data or []


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
    if res.error:
        logger.error("Failed to add match request: %s", res.error)
        raise RuntimeError(f"Match request failed: {res.error}")
    return match_id

def pop_match_request(exclude_id: int) -> Optional[Dict[str, Any]]:
    """Pop a match request excluding the given telegram_id"""
    client = get_supabase()
    # Get a random pending request that's not from the same user
    res = client.table("match_requests").select("*").neq("telegram_id", exclude_id).eq("status", "pending").limit(1).execute()
    if res.error or not res.data:
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