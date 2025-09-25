"""
Systeme.io service for contact management
"""
import os
import logging
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_ACHIEVER_TAG_ID = os.getenv("SYSTEME_ACHIEVER_TAG_ID")
SYSTEME_BASE_URL = "https://api.systeme.io/api/v1"


async def create_contact_and_tag(contact_data: Dict[str, Any]) -> Optional[str]:
    """Create contact in Systeme.io and apply tag"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact creation")
            return None
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Create contact
        contact_payload = {
            "email": contact_data.get("email"),
            "first_name": contact_data.get("name", "").split()[0] if contact_data.get("name") else "",
            "last_name": " ".join(contact_data.get("name", "").split()[1:]) if contact_data.get("name") and len(contact_data.get("name", "").split()) > 1 else "",
            "phone": contact_data.get("phone", ""),
            "tags": ["verified"] if contact_data.get("status") == "verified" else ["pending"]
        }
        
        async with aiohttp.ClientSession() as session:
            # Create contact
            async with session.post(
                f"{SYSTEME_BASE_URL}/contacts",
                headers=headers,
                json=contact_payload
            ) as response:
                if response.status == 201:
                    result = await response.json()
                    contact_id = result.get("id")
                    logger.info("Created Systeme.io contact: %s", contact_data.get("email"))
                    
                    # Apply achiever tag if applicable
                    if contact_id and SYSTEME_ACHIEVER_TAG_ID and contact_data.get("status") == "verified":
                        await _apply_achiever_tag(contact_id, session, headers)
                    
                    return contact_id
                else:
                    logger.warning("Failed to create Systeme.io contact: %s", await response.text())
                    return None
        
    except Exception as e:
        logger.exception("Failed to create Systeme.io contact: %s", e)
        return None


async def _apply_achiever_tag(contact_id: str, session: aiohttp.ClientSession, headers: Dict[str, str]) -> bool:
    """Apply achiever tag to contact"""
    try:
        tag_payload = {
            "contact_id": contact_id,
            "tag_id": SYSTEME_ACHIEVER_TAG_ID
        }
        
        async with session.post(
            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
            headers=headers,
            json=tag_payload
        ) as response:
            if response.status == 200:
                logger.info("Applied achiever tag to contact: %s", contact_id)
                return True
            else:
                logger.warning("Failed to apply achiever tag: %s", await response.text())
                return False
                
    except Exception as e:
        logger.exception("Failed to apply achiever tag: %s", e)
        return False


async def untag_or_remove_contact(contact_data: Dict[str, Any]) -> bool:
    """Remove tag or delete contact from Systeme.io"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact removal")
            return False
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        email = contact_data.get("email")
        if not email:
            return False
        
        async with aiohttp.ClientSession() as session:
            # Find contact by email
            async with session.get(
                f"{SYSTEME_BASE_URL}/contacts",
                headers=headers,
                params={"email": email}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    contacts = result.get("data", [])
                    
                    if contacts:
                        contact_id = contacts[0].get("id")
                        
                        # Remove tags
                        await session.delete(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
                            headers=headers
                        )
                        
                        # Delete contact
                        async with session.delete(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}",
                            headers=headers
                        ) as delete_response:
                            if delete_response.status == 200:
                                logger.info("Removed Systeme.io contact: %s", email)
                                return True
                            else:
                                logger.warning("Failed to delete contact: %s", await delete_response.text())
                                return False
                    else:
                        logger.warning("Contact not found in Systeme.io: %s", email)
                        return False
                else:
                    logger.warning("Failed to find contact: %s", await response.text())
                    return False
        
    except Exception as e:
        logger.exception("Failed to remove Systeme.io contact: %s", e)
        return False


async def update_contact_status(contact_data: Dict[str, Any], new_status: str) -> bool:
    """Update contact status in Systeme.io"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact update")
            return False
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        email = contact_data.get("email")
        if not email:
            return False
        
        async with aiohttp.ClientSession() as session:
            # Find contact by email
            async with session.get(
                f"{SYSTEME_BASE_URL}/contacts",
                headers=headers,
                params={"email": email}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    contacts = result.get("data", [])
                    
                    if contacts:
                        contact_id = contacts[0].get("id")
                        
                        # Update tags based on status
                        new_tags = ["verified"] if new_status == "verified" else ["pending"]
                        
                        update_payload = {
                            "tags": new_tags
                        }
                        
                        async with session.put(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}",
                            headers=headers,
                            json=update_payload
                        ) as update_response:
                            if update_response.status == 200:
                                logger.info("Updated Systeme.io contact status: %s -> %s", email, new_status)
                                return True
                            else:
                                logger.warning("Failed to update contact: %s", await update_response.text())
                                return False
                    else:
                        logger.warning("Contact not found for update: %s", email)
                        return False
                else:
                    logger.warning("Failed to find contact for update: %s", await response.text())
                    return False
        
    except Exception as e:
        logger.exception("Failed to update Systeme.io contact: %s", e)
        return False
