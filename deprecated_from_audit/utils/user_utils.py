"""
User-related shared utilities to avoid circular imports.
Supabase implementation for verification-only operations.
"""
from typing import Optional, Dict, Any
from avap_bot.utils.supabase_client import check_verified_user


async def user_verified_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Return verified user record by Telegram ID or None if not verified/removed.

    Structure: {"name", "email", "phone", "telegram_id", "status"}
    """
    user_data = await check_verified_user(telegram_id)
    if user_data and user_data.get("status") != "removed":
        return {
            "name": user_data.get("name"),
            "email": user_data.get("email"),
            "phone": user_data.get("phone"),
            "telegram_id": user_data.get("telegram_id"),
            "status": user_data.get("status", "verified"),
        }
    return None


