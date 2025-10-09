"""
Distributed lock implementation using Supabase
"""
import time
import logging
from typing import Optional
from avap_bot.services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

def acquire_lock(lock_key: str, ttl_seconds: int = 120) -> Optional[str]:
    """
    Acquire a distributed lock using Supabase.
    
    Args:
        lock_key: Unique key for the lock
        ttl_seconds: Time to live in seconds
        
    Returns:
        Lock token if acquired, None if already locked
    """
    try:
        client = get_supabase()
        lock_token = f"{lock_key}_{int(time.time())}_{id(time)}"
        expires_at = time.time() + ttl_seconds
        
        # Try to insert the lock (will fail if already exists)
        result = client.table("distributed_locks").insert({
            "lock_key": lock_key,
            "lock_token": lock_token,
            "expires_at": expires_at,
            "created_at": time.time()
        }).execute()
        
        if result.data:
            logger.info("Acquired distributed lock: %s", lock_key)
            return lock_token
        else:
            logger.info("Lock already exists: %s", lock_key)
            return None
            
    except Exception as e:
        # If insert fails, it might be because lock already exists
        logger.debug("Failed to acquire lock %s: %s", lock_key, e)
        return None

def release_lock(lock_key: str, lock_token: str) -> bool:
    """
    Release a distributed lock.
    
    Args:
        lock_key: Lock key
        lock_token: Lock token returned by acquire_lock
        
    Returns:
        True if released successfully
    """
    try:
        client = get_supabase()
        
        # Delete only if token matches (atomic operation)
        result = client.table("distributed_locks").delete().eq("lock_key", lock_key).eq("lock_token", lock_token).execute()
        
        if result.data:
            logger.info("Released distributed lock: %s", lock_key)
            return True
        else:
            logger.warning("Failed to release lock %s - token mismatch or already released", lock_key)
            return False
            
    except Exception as e:
        logger.error("Error releasing lock %s: %s", lock_key, e)
        return False

def cleanup_expired_locks():
    """
    Clean up expired locks (should be called periodically).
    """
    try:
        client = get_supabase()
        current_time = time.time()
        
        # Delete expired locks
        result = client.table("distributed_locks").delete().lt("expires_at", current_time).execute()
        
        if result.data:
            logger.info("Cleaned up %d expired locks", len(result.data))
            
    except Exception as e:
        logger.error("Error cleaning up expired locks: %s", e)

def is_lock_acquired(lock_key: str) -> bool:
    """
    Check if a lock is currently acquired.
    
    Args:
        lock_key: Lock key to check
        
    Returns:
        True if lock is acquired and not expired
    """
    try:
        client = get_supabase()
        current_time = time.time()
        
        result = client.table("distributed_locks").select("*").eq("lock_key", lock_key).gt("expires_at", current_time).execute()
        
        return len(result.data) > 0
        
    except Exception as e:
        logger.error("Error checking lock %s: %s", lock_key, e)
        return False
