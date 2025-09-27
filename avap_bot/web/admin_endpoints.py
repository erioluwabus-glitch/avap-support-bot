"""
Admin endpoints for bot management
"""
import os
import logging
from typing import Dict, Any

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from avap_bot.services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter()

ADMIN_RESET_TOKEN = os.getenv("ADMIN_RESET_TOKEN")


@router.post("/admin/purge/email")
async def purge_single_email(request: Request) -> Dict[str, Any]:
    """Purge single email from pending verifications"""
    token = request.headers.get("X-Admin-Reset-Token")
    if not ADMIN_RESET_TOKEN or token != ADMIN_RESET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        data = await request.json()
        email = data.get("email", "").strip()
        
        if not email:
            raise HTTPException(status_code=400, detail="Email required")
        
        # Delete from Supabase
        client = get_supabase()
        result = client.table("pending_verifications").delete().eq("email", email).execute()
        
        deleted_count = len(result.data) if result.data else 0
        
        logger.info("Purged email from pending verifications: %s (deleted: %d)", email, deleted_count)
        
        return {
            "status": "ok",
            "email_deleted": email,
            "deleted_count": deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Admin purge email failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/purge/pending")
async def purge_all_pending(request: Request) -> Dict[str, Any]:
    """Purge all pending verifications"""
    token = request.headers.get("X-Admin-Reset-Token")
    if not ADMIN_RESET_TOKEN or token != ADMIN_RESET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        # Delete all from Supabase
        client = get_supabase()
        result = client.table("pending_verifications").delete().neq("id", 0).execute()
        
        deleted_count = len(result.data) if result.data else 0
        
        logger.info("Purged all pending verifications (deleted: %d)", deleted_count)
        
        return {
            "status": "ok",
            "pending_cleared": True,
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        logger.exception("Admin purge pending failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/remove/verified_by_email")
async def remove_verified_by_email(request: Request) -> Dict[str, Any]:
    """Remove verified user by email"""
    token = request.headers.get("X-Admin-Reset-Token")
    if not ADMIN_RESET_TOKEN or token != ADMIN_RESET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        data = await request.json()
        email = data.get("email", "").strip()
        reason = data.get("reason", "admin_remove_by_email").strip()
        
        if not email:
            raise HTTPException(status_code=400, detail="Email required")
        
        # Soft delete in Supabase
        client = get_supabase()
        result = client.table("verified_users").update({
            "status": "removed",
            "removed_at": "now()",
            "removal_reason": reason
        }).eq("email", email).execute()
        
        updated_count = len(result.data) if result.data else 0
        
        logger.info("Removed verified user by email: %s (updated: %d)", email, updated_count)
        
        return {
            "status": "ok",
            "email": email,
            "soft_deleted": True,
            "updated_count": updated_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Admin remove by email failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/remove/verified_by_telegram")
async def remove_verified_by_telegram(request: Request) -> Dict[str, Any]:
    """Remove verified user by telegram ID"""
    token = request.headers.get("X-Admin-Reset-Token")
    if not ADMIN_RESET_TOKEN or token != ADMIN_RESET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        data = await request.json()
        telegram_id = data.get("telegram_id")
        reason = data.get("reason", "admin_remove_by_telegram").strip()
        
        if not telegram_id:
            raise HTTPException(status_code=400, detail="telegram_id required")
        
        # Soft delete in Supabase
        client = get_supabase()
        result = client.table("verified_users").update({
            "status": "removed",
            "removed_at": "now()",
            "removal_reason": reason
        }).eq("telegram_id", telegram_id).execute()
        
        updated_count = len(result.data) if result.data else 0
        
        logger.info("Removed verified user by telegram ID: %s (updated: %d)", telegram_id, updated_count)
        
        return {
            "status": "ok",
            "telegram_id": telegram_id,
            "soft_deleted": True,
            "updated_count": updated_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Admin remove by telegram failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/stats")
async def get_admin_stats(request: Request) -> Dict[str, Any]:
    """Get admin statistics"""
    token = request.headers.get("X-Admin-Reset-Token")
    if not ADMIN_RESET_TOKEN or token != ADMIN_RESET_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        client = get_supabase()
        
        # Get counts
        pending_result = client.table("pending_verifications").select("id", count="exact").execute()
        verified_result = client.table("verified_users").select("id", count="exact").eq("status", "verified").execute()
        removed_result = client.table("verified_users").select("id", count="exact").eq("status", "removed").execute()
        
        return {
            "status": "ok",
            "stats": {
                "pending_verifications": pending_result.count or 0,
                "verified_users": verified_result.count or 0,
                "removed_users": removed_result.count or 0
            }
        }
        
    except Exception as e:
        logger.exception("Admin stats failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
