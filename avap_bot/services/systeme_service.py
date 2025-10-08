"""
Systeme.io service for contact management - Fixed implementation with proper error handling
"""
import os
import logging
import time
import asyncio
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)

# Convert environment variables to proper types on startup
SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_TAG_ID = int(os.getenv("SYSTEME_VERIFIED_TAG_ID", "0")) if os.getenv("SYSTEME_VERIFIED_TAG_ID") and os.getenv("SYSTEME_VERIFIED_TAG_ID").isdigit() else None
SYSTEME_ACHIEVER_TAG_ID = int(os.getenv("SYSTEME_ACHIEVER_TAG_ID", "0")) if os.getenv("SYSTEME_ACHIEVER_TAG_ID") and os.getenv("SYSTEME_ACHIEVER_TAG_ID").isdigit() else None
SYSTEME_BASE_URL = os.getenv("SYSTEME_BASE_URL", "https://api.systeme.io")

# Canonical API endpoints
BASE = "https://api.systeme.io/api"
HEADERS = {
    "Authorization": f"Bearer {SYSTEME_API_KEY}",
    "Content-Type": "application/json",
} if SYSTEME_API_KEY else {}


def validate_systeme_configuration() -> bool:
    """Validate Systeme.io configuration and provide helpful error messages"""
    issues = []

    if not SYSTEME_API_KEY:
        issues.append("SYSTEME_API_KEY environment variable not set")
    elif len(SYSTEME_API_KEY) < 10:
        issues.append("SYSTEME_API_KEY appears to be invalid (too short)")

    # Validate tag IDs - now they are integers
    if not SYSTEME_VERIFIED_TAG_ID:
        issues.append("SYSTEME_VERIFIED_TAG_ID environment variable not set or invalid")
    elif SYSTEME_VERIFIED_TAG_ID <= 0:
        issues.append(f"SYSTEME_VERIFIED_TAG_ID must be positive integer, got: {SYSTEME_VERIFIED_TAG_ID}")

    if not SYSTEME_ACHIEVER_TAG_ID:
        issues.append("SYSTEME_ACHIEVER_TAG_ID environment variable not set or invalid")
    elif SYSTEME_ACHIEVER_TAG_ID <= 0:
        issues.append(f"SYSTEME_ACHIEVER_TAG_ID must be positive integer, got: {SYSTEME_ACHIEVER_TAG_ID}")

    if issues:
        logger.error("❌ Systeme.io configuration issues detected:")
        for issue in issues:
            logger.error(f"  - {issue}")
        logger.error("Please fix these configuration issues to ensure proper tagging functionality")
        logger.error("Get your API key from: https://systeme.io/account/api")
        logger.error("Tag IDs should be the numeric IDs of your tags in Systeme.io (e.g., 1234567)")
        logger.error("You can find tag IDs in your Systeme.io dashboard under Contacts > Tags")
        return False

    logger.info("✅ Systeme.io configuration appears valid")
    logger.info(f"  - API Key: {SYSTEME_API_KEY[:10]}... (length: {len(SYSTEME_API_KEY)})")
    logger.info(f"  - Verified Tag ID: {SYSTEME_VERIFIED_TAG_ID}")
    logger.info(f"  - Achiever Tag ID: {SYSTEME_ACHIEVER_TAG_ID}")
    logger.info(f"  - Base URL: {SYSTEME_BASE_URL}")
    return True


async def apply_tag(contact_id: int, tag_id: int) -> Dict[str, Any]:
    """Apply tag to contact. Validate types, do limited retries with backoff."""
    try:
        # Validate tag_id and contact_id early
        if not isinstance(tag_id, int) or tag_id <= 0:
            raise ValueError(f"Invalid tag_id — must be positive int, got: {tag_id}")

        if not isinstance(contact_id, int) or contact_id <= 0:
            raise ValueError(f"Invalid contact_id — must be positive int, got: {contact_id}")

        url = f"{BASE}/contacts/{contact_id}/tags"
        payload = {"tagId": tag_id}

        logger.info(f"Applying tag {tag_id} to contact {contact_id} using endpoint: {url}")
        logger.debug(f"Payload: {payload}")

        # Limited retries with exponential backoff for transient failures
        max_attempts = 4
        backoff = 0.5
        
        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(
                        url, 
                        json=payload, 
                        headers=HEADERS, 
                        timeout=10.0
                    )
                    
                    logger.info(f"Attempt {attempt}: Status {response.status_code}")
                    
                    # 204 is success (no content) per your logs; 201 may appear elsewhere
                    if response.status_code in (200, 201, 204):
                        logger.info(f"✅ Successfully applied tag {tag_id} to contact {contact_id}")
                        return {"ok": True, "status": response.status_code, "body": response.text}
                    
                    # 4xx errors are client errors; don't keep retrying except maybe 429
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        logger.error(f"❌ Client error {response.status_code}: {response.text[:300]}")
                        return {"ok": False, "status": response.status_code, "error": response.text}
                    
                    # 429/5xx -> retry
                    if attempt < max_attempts:
                        logger.warning(f"Retrying in {backoff}s (attempt {attempt}/{max_attempts})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                    else:
                        logger.error(f"❌ All attempts failed. Final status: {response.status_code}")
                        return {"ok": False, "status": response.status_code, "error": response.text}
                        
                except Exception as e:
                    logger.error(f"Request attempt {attempt} failed: {e}")
                    if attempt < max_attempts:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                    else:
                        return {"ok": False, "status": 0, "error": str(e)}

    except Exception as e:
        logger.exception(f"Failed to apply tag {tag_id} to contact {contact_id}: {e}")
        return {"ok": False, "status": 0, "error": str(e)}


async def create_contact_and_tag(contact_data: Dict[str, Any]) -> Optional[str]:
    """Create contact in Systeme.io and apply tag using clean, single-endpoint approach"""
    try:
        # Validate configuration first
        if not validate_systeme_configuration():
            logger.error("Systeme.io configuration validation failed - cannot proceed with contact creation")
            return None

        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact creation")
            return None

        logger.info(f"Creating Systeme.io contact for: {contact_data.get('email')}")

        # Prepare contact data
        name_parts = contact_data.get("name", "").split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        # Single canonical payload format
        contact_payload = {
            "email": contact_data.get("email"),
            "firstName": first_name,
            "lastName": last_name,
            "phoneNumber": contact_data.get("phone", "")
        }

        # Single canonical endpoint
        url = f"{BASE}/contacts"
        
        logger.info(f"Using endpoint: {url}")
        logger.debug(f"Payload: {contact_payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=HEADERS,
                json=contact_payload,
                timeout=10.0
            )

            logger.info(f"Contact creation response: {response.status_code}")

            if response.status_code in [200, 201, 409]:
                # Parse response to get contact ID
                if response.status_code == 201:
                    result = response.json()
                    contact_id = result.get("id")
                    logger.info(f"✅ Created Systeme.io contact: {contact_data.get('email')} (ID: {contact_id})")
                elif response.status_code == 409:
                    # Contact already exists - find it
                    contact_id = await _find_contact_by_email(contact_data.get("email"))
                    if contact_id:
                        logger.info(f"Found existing contact: {contact_data.get('email')} (ID: {contact_id})")
                    else:
                        logger.warning(f"Contact exists but couldn't find ID for: {contact_data.get('email')}")
                        return "existing"

                # Apply tags if contact was created/found and status is verified
                if contact_id and contact_data.get("status") == "verified":
                    await _apply_verified_tag_to_contact(contact_id)
                    await _apply_achiever_tag_to_contact(contact_id)

                return str(contact_id) if contact_id else "existing"

            elif response.status_code == 401:
                logger.error("❌ Systeme.io API authentication failed - check your API key")
                logger.error("Response: %s", response.text[:300])
                return None
            elif response.status_code == 403:
                logger.error("❌ Systeme.io API access forbidden - check API permissions")
                logger.error("Response: %s", response.text[:300])
                return None
            else:
                logger.warning(f"❌ Failed to create Systeme.io contact: HTTP {response.status_code}")
                logger.warning("Response: %s", response.text[:300])
                return None

    except Exception as e:
        logger.exception(f"Failed to create Systeme.io contact: {e}")
        return None


async def _find_contact_by_email(email: str) -> Optional[int]:
    """Find contact by email and return contact ID"""
    try:
        if not SYSTEME_API_KEY:
            return None

        url = f"{BASE}/contacts"
        params = {"email": email}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=10.0
            )

            if response.status_code == 200:
                result = response.json()
                contacts = result.get("data", [])
                if contacts:
                    contact_id = contacts[0].get("id")
                    logger.info(f"Found contact {email} with ID: {contact_id}")
                    return int(contact_id) if contact_id else None
                else:
                    logger.warning(f"No contact found for email: {email}")
                    return None
            else:
                logger.warning(f"Failed to search for contact {email}: {response.status_code}")
                return None

    except Exception as e:
        logger.exception(f"Failed to find contact by email {email}: {e}")
        return None


async def _apply_verified_tag_to_contact(contact_id: int) -> bool:
    """Apply verified tag to contact using the new apply_tag function"""
    try:
        if not SYSTEME_VERIFIED_TAG_ID:
            logger.warning("SYSTEME_VERIFIED_TAG_ID not set, skipping verified tag")
            return False

        result = await apply_tag(contact_id, SYSTEME_VERIFIED_TAG_ID)
        if result.get("ok"):
            logger.info(f"✅ Successfully applied verified tag to contact {contact_id}")
            return True
        else:
            logger.error(f"❌ Failed to apply verified tag to contact {contact_id}: {result.get('error', 'Unknown error')}")
            return False

    except Exception as e:
        logger.exception(f"Failed to apply verified tag to contact {contact_id}: {e}")
        return False


async def _apply_achiever_tag_to_contact(contact_id: int) -> bool:
    """Apply achiever tag to contact using the new apply_tag function"""
    try:
        if not SYSTEME_ACHIEVER_TAG_ID:
            logger.warning("SYSTEME_ACHIEVER_TAG_ID not set, skipping achiever tag")
            return False

        result = await apply_tag(contact_id, SYSTEME_ACHIEVER_TAG_ID)
        if result.get("ok"):
            logger.info(f"✅ Successfully applied achiever tag to contact {contact_id}")
            return True
        else:
            logger.error(f"❌ Failed to apply achiever tag to contact {contact_id}: {result.get('error', 'Unknown error')}")
            return False

    except Exception as e:
        logger.exception(f"Failed to apply achiever tag to contact {contact_id}: {e}")
        return False


async def remove_contact_by_email(email: str) -> bool:
    """Remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact removal")
            return False

        # Find contact by email
        contact_id = await _find_contact_by_email(email)
        if not contact_id:
            logger.warning(f"Contact not found in Systeme.io: {email}")
            return False

        # Delete contact
        url = f"{BASE}/contacts/{contact_id}"
        
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=HEADERS,
                timeout=10.0
            )

            if response.status_code in [200, 204]:
                logger.info(f"✅ Removed Systeme.io contact: {email}")
                return True
            else:
                logger.warning(f"Failed to delete contact {email}: {response.status_code} - {response.text[:300]}")
                return False

    except Exception as e:
        logger.exception(f"Failed to remove Systeme.io contact {email}: {e}")
        return False


async def tag_achiever(contact_id: int) -> bool:
    """Add achiever tag to contact using the new apply_tag function"""
    try:
        if not SYSTEME_ACHIEVER_TAG_ID:
            logger.warning("SYSTEME_ACHIEVER_TAG_ID not set, skipping achiever tagging")
            return False

        result = await apply_tag(contact_id, SYSTEME_ACHIEVER_TAG_ID)
        if result.get("ok"):
            logger.info(f"✅ Successfully applied achiever tag to contact {contact_id}")
            return True
        else:
            logger.error(f"❌ Failed to apply achiever tag to contact {contact_id}: {result.get('error', 'Unknown error')}")
            return False

    except Exception as e:
        logger.exception(f"Failed to tag achiever for contact {contact_id}: {e}")
        return False


async def untag_or_remove_contact(email: str, action: str = "untag") -> bool:
    """Untag or remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact action")
            return False

        # Find contact by email
        contact_id = await _find_contact_by_email(email)
        if not contact_id:
            logger.warning(f"Contact not found in Systeme.io: {email}")
            return False

        if action == "untag":
            # Remove all tags
            url = f"{BASE}/contacts/{contact_id}/tags"
            
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url,
                    headers=HEADERS,
                    timeout=10.0
                )

                if response.status_code in [200, 204]:
                    logger.info(f"✅ Untagged Systeme.io contact: {email}")
                    return True
                else:
                    logger.warning(f"Failed to untag contact {email}: {response.status_code}")
                    return False

        elif action == "remove":
            # Delete contact (this will also remove tags)
            return await remove_contact_by_email(email)

        return False

    except Exception as e:
        logger.exception(f"Failed to untag/remove Systeme.io contact {email}: {e}")
        return False
