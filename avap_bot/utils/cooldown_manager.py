"""
Cooldown state manager to prevent immediate retries on restart
"""
import time
import logging
from typing import Optional
from avap_bot.services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

# Fallback in-memory cooldown states if database fails
_in_memory_cooldowns = {}

def get_cooldown_state(key: str) -> Optional[float]:
    """
    Get the next allowed time for a given key.
    
    Args:
        key: Cooldown key
        
    Returns:
        Timestamp when next attempt is allowed, or None if no cooldown
    """
    try:
        client = get_supabase()
        result = client.table("cooldown_states").select("next_allowed_time").eq("key", key).execute()
        
        if result.data:
            return result.data[0]["next_allowed_time"]
        return None
        
    except Exception as e:
        logger.error("Error getting cooldown state for %s: %s", key, e)
        logger.info("Falling back to in-memory cooldown state")
        # Fallback to in-memory state
        return _in_memory_cooldowns.get(key)

def set_cooldown_state(key: str, next_allowed_time: float) -> bool:
    """
    Set the next allowed time for a given key.
    
    Args:
        key: Cooldown key
        next_allowed_time: Timestamp when next attempt is allowed
        
    Returns:
        True if set successfully
    """
    try:
        client = get_supabase()
        
        # Upsert the cooldown state
        result = client.table("cooldown_states").upsert({
            "key": key,
            "next_allowed_time": next_allowed_time,
            "updated_at": time.time()
        }).execute()
        
        if result.data:
            logger.info("Set cooldown for %s until %s", key, time.ctime(next_allowed_time))
            return True
        return False
        
    except Exception as e:
        logger.error("Error setting cooldown state for %s: %s", key, e)
        logger.info("Falling back to in-memory cooldown state")
        # Fallback to in-memory state
        _in_memory_cooldowns[key] = next_allowed_time
        return True

def is_cooldown_active(key: str) -> bool:
    """
    Check if a cooldown is currently active.
    
    Args:
        key: Cooldown key
        
    Returns:
        True if cooldown is active
    """
    next_allowed = get_cooldown_state(key)
    if next_allowed is None:
        return False
    
    current_time = time.time()
    if current_time < next_allowed:
        logger.info("Cooldown active for %s until %s", key, time.ctime(next_allowed))
        return True
    
    return False

def clear_cooldown(key: str) -> bool:
    """
    Clear a cooldown state.
    
    Args:
        key: Cooldown key
        
    Returns:
        True if cleared successfully
    """
    try:
        client = get_supabase()
        result = client.table("cooldown_states").delete().eq("key", key).execute()
        
        if result.data:
            logger.info("Cleared cooldown for %s", key)
            return True
        return False
        
    except Exception as e:
        logger.error("Error clearing cooldown for %s: %s", key, e)
        return False
