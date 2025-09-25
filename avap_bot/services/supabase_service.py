"""
Supabase service for verification operations
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client: Optional[Client] = None


def init_supabase() -> Client:
    """Initialize Supabase client"""
    global supabase_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
    if supabase_client is None:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized successfully")
    return supabase_client


def get_supabase() -> Client:
    """Get Supabase client instance"""
    if supabase_client is None:
        return init_supabase()
    return supabase_client


async def add_pending_verification(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Add pending verification record"""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").insert(record).execute()
        if result.data:
            logger.info("Added pending verification: %s", record.get('email'))
            return result.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to add pending verification: %s", e)
        return None


async def find_pending_by_email_or_phone(email: str, phone: str) -> Optional[Dict[str, Any]]:
    """Find pending verification by email or phone"""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").select("*").or_(f"email.eq.{email},phone.eq.{phone}").execute()
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to find pending verification: %s", e)
        return None


async def check_verified_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Check if user is verified by telegram ID"""
    try:
        client = get_supabase()
        result = client.table("verified_users").select("*").eq("telegram_id", telegram_id).eq("status", "verified").execute()
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to check verified user: %s", e)
        return None


async def add_verified_user(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Add verified user record"""
    try:
        client = get_supabase()
        result = client.table("verified_users").insert(record).execute()
        if result.data:
            logger.info("Added verified user: %s", record.get('email'))
            return result.data[0]
        return None
    except Exception as e:
        logger.exception("Failed to add verified user: %s", e)
        return None


async def promote_pending_to_verified(pending_id: str) -> Optional[Dict[str, Any]]:
    """Promote pending verification to verified user"""
    try:
        client = get_supabase()
        
        # Get pending record
        pending_result = client.table("pending_verifications").select("*").eq("id", pending_id).execute()
        if not pending_result.data:
            return None
        
        pending_record = pending_result.data[0]
        
        # Create verified user record
        verified_record = {
            "name": pending_record["name"],
            "email": pending_record["email"],
            "phone": pending_record["phone"],
            "telegram_id": pending_record.get("telegram_id", 0),
            "status": "verified",
            "verified_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add to verified users
        verified_result = client.table("verified_users").insert(verified_record).execute()
        if not verified_result.data:
            return None
        
        # Remove from pending
        client.table("pending_verifications").delete().eq("id", pending_id).execute()
        
        logger.info("Promoted pending to verified: %s", pending_record.get('email'))
        return verified_result.data[0]
        
    except Exception as e:
        logger.exception("Failed to promote pending to verified: %s", e)
        return None


async def remove_verified_by_identifier(identifier: str) -> bool:
    """Remove verified user by email, phone, or telegram_id"""
    try:
        client = get_supabase()
        
        # Try to find by different identifiers
        result = client.table("verified_users").select("*").or_(
            f"email.eq.{identifier},phone.eq.{identifier},telegram_id.eq.{identifier}"
        ).execute()
        
        if not result.data:
            return False
        
        # Soft delete by updating status
        for user in result.data:
            client.table("verified_users").update({
                "status": "removed",
                "removed_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", user["id"]).execute()
        
        logger.info("Removed verified user: %s", identifier)
        return True
        
    except Exception as e:
        logger.exception("Failed to remove verified user: %s", e)
        return False


async def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users"""
    try:
        client = get_supabase()
        result = client.table("verified_users").select("*").eq("status", "verified").execute()
        return result.data or []
    except Exception as e:
        logger.exception("Failed to get verified users: %s", e)
        return []


async def get_all_pending_verifications() -> List[Dict[str, Any]]:
    """Get all pending verifications"""
    try:
        client = get_supabase()
        result = client.table("pending_verifications").select("*").execute()
        return result.data or []
    except Exception as e:
        logger.exception("Failed to get pending verifications: %s", e)
        return []
