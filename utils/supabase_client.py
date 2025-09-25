"""
Supabase client for verification-only database operations.
Handles verified_users and pending_verifications tables.
"""
import os
import logging
from typing import Optional, List, Dict, Any
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Supabase client
supabase_client: Optional[Client] = None

def init_supabase() -> Client:
    """Initialize and return Supabase client."""
    global supabase_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
    
    if supabase_client is None:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
    
    return supabase_client

def get_supabase() -> Client:
    """Get initialized Supabase client."""
    if supabase_client is None:
        return init_supabase()
    return supabase_client

# Verification operations
async def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified by telegram_id."""
    try:
        client = get_supabase()
        result = client.table("verified_users").select("*").eq("telegram_id", telegram_id).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.exception(f"Error checking verified user: {e}")
        return None

async def add_verified_user(name: str, email: str, phone: str, telegram_id: int) -> bool:
    """Add a verified user to the database."""
    try:
        client = get_supabase()
        result = client.table("verified_users").insert({
            "name": name,
            "email": email,
            "phone": phone,
            "telegram_id": telegram_id,
            "status": "verified"
        }).execute()
        
        logger.info(f"Added verified user: {name} ({email})")
        return True
    except Exception as e:
        logger.exception(f"Error adding verified user: {e}")
        return False

async def check_pending_verification(email: str) -> Optional[Dict[str, Any]]:
    """Check if there's a pending verification for this email."""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").select("*").eq("email", email).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.exception(f"Error checking pending verification: {e}")
        return None

async def add_pending_verification(name: str, email: str, phone: str, telegram_id: int = 0) -> bool:
    """Add a pending verification."""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").insert({
            "name": name,
            "email": email,
            "phone": phone,
            "telegram_id": telegram_id
        }).execute()
        
        logger.info(f"Added pending verification: {name} ({email})")
        return True
    except Exception as e:
        logger.exception(f"Error adding pending verification: {e}")
        return False

async def remove_pending_verification(email: str) -> bool:
    """Remove a pending verification by email."""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").delete().eq("email", email).execute()
        
        logger.info(f"Removed pending verification for: {email}")
        return True
    except Exception as e:
        logger.exception(f"Error removing pending verification: {e}")
        return False

async def get_all_pending_verifications() -> List[Dict[str, Any]]:
    """Get all pending verifications."""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").select("*").execute()
        return result.data or []
    except Exception as e:
        logger.exception(f"Error getting pending verifications: {e}")
        return []

async def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users."""
    try:
        client = get_supabase()
        result = client.table("verified_users").select("*").execute()
        return result.data or []
    except Exception as e:
        logger.exception(f"Error getting verified users: {e}")
        return []

async def soft_delete_verified_user(telegram_id: int) -> bool:
    """Soft delete a verified user by setting status to 'removed'."""
    try:
        client = get_supabase()
        result = client.table("verified_users").update({
            "status": "removed"
        }).eq("telegram_id", telegram_id).execute()
        
        logger.info(f"Soft deleted verified user: {telegram_id}")
        return True
    except Exception as e:
        logger.exception(f"Error soft deleting verified user: {e}")
        return False

async def soft_delete_verified_user_by_email(email: str) -> bool:
    """Soft delete a verified user by email."""
    try:
        client = get_supabase()
        result = client.table("verified_users").update({
            "status": "removed"
        }).eq("email", email).execute()
        
        logger.info(f"Soft deleted verified user by email: {email}")
        return True
    except Exception as e:
        logger.exception(f"Error soft deleting verified user by email: {e}")
        return False


