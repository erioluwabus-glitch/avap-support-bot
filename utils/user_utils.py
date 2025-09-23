"""
User-related shared utilities to avoid circular imports.
PostgreSQL implementation via async db helpers.
"""
from typing import Optional, Dict, Any
from utils.db_async import db_fetchone


async def user_verified_by_telegram_id(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Return verified user record by Telegram ID or None if not verified/removed.

    Structure: {"name", "email", "phone", "telegram_id", "status"}
    """
    row = await db_fetchone(
        """
        SELECT name, email, phone, telegram_id, status
        FROM verified_users
        WHERE telegram_id = ? AND removed_at IS NULL
        """,
        (telegram_id,),
    )
    if row:
        return {
            "name": row[0],
            "email": row[1],
            "phone": row[2],
            "telegram_id": row[3],
            "status": row[4],
        }
    return None


