"""
Systeme.io service for contact management - Async implementation with httpx
"""
import os
import logging
from typing import Optional, Dict, Any, List
import httpx

logger = logging.getLogger(__name__)

SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_ACHIEVER_TAG_ID = os.getenv("SYSTEME_ACHIEVER_TAG_ID")
SYSTEME_BASE_URL = os.getenv("SYSTEME_BASE_URL", "https://api.systeme.io")


async def create_contact_and_tag(contact_data: Dict[str, Any]) -> Optional[str]:
    """Create contact in Systeme.io and apply tag"""
    try:
        logger.info(f"Systeme.io configuration - API_KEY: {'SET' if SYSTEME_API_KEY else 'NOT SET'}, BASE_URL: {SYSTEME_BASE_URL}")
        
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact creation")
            logger.warning("Please set SYSTEME_API_KEY environment variable with your Systeme.io API key")
            logger.warning("Get your API key from: https://systeme.io/account/api")
            return None

        # Systeme.io API keys can have various formats - check if it's a reasonable length and contains valid characters
        if not SYSTEME_API_KEY or len(SYSTEME_API_KEY) < 10:
            logger.error("SYSTEME_API_KEY appears to be invalid - too short")
            logger.warning("Please verify your Systeme.io API key from: https://systeme.io/account/api")
            logger.warning("Make sure you're using a valid API Key (Secret or Publishable)")
            return None

        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"Using API key format: {SYSTEME_API_KEY[:10]}... (length: {len(SYSTEME_API_KEY)})")

        # Create contact - try different payload formats for Systeme.io
        name_parts = contact_data.get("name", "").split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        # Try multiple payload formats
        contact_payloads = [
            # Format 1: Standard format
            {
                "email": contact_data.get("email"),
                "firstName": first_name,
                "lastName": last_name,
                "phoneNumber": contact_data.get("phone", ""),
                "tags": ["verified"] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 2: Alternative format
            {
                "email": contact_data.get("email"),
                "first_name": first_name,
                "last_name": last_name,
                "phone": contact_data.get("phone", ""),
                "tags": ["verified"] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 3: Minimal format
            {
                "email": contact_data.get("email"),
                "name": contact_data.get("name", ""),
                "phone": contact_data.get("phone", ""),
                "tags": ["verified"] if contact_data.get("status") == "verified" else ["pending"]
            }
        ]

        async with httpx.AsyncClient() as client:
            logger.info("Attempting to create Systeme.io contact for: %s", contact_data.get("email"))
            
            # Try different endpoint formats and payload formats
            endpoints_to_try = [
                f"{SYSTEME_BASE_URL}/api/contacts",
                f"{SYSTEME_BASE_URL}/contacts",
                f"{SYSTEME_BASE_URL}/api/v1/contacts",
                f"{SYSTEME_BASE_URL}/api/v2/contacts"
            ]
            
            logger.info(f"Trying {len(endpoints_to_try)} endpoints with {len(contact_payloads)} payload formats")
            for endpoint in endpoints_to_try:
                logger.info(f"  - {endpoint}")
            
            response = None
            successful_endpoint = None
            successful_payload = None
            
            for endpoint in endpoints_to_try:
                for i, contact_payload in enumerate(contact_payloads):
                    try:
                        logger.debug("Trying endpoint: %s with payload format %d", endpoint, i+1)
                        logger.debug("Payload: %s", contact_payload)
                        response = await client.post(
                            endpoint,
                            headers=headers,
                            json=contact_payload,
                            timeout=10.0
                        )
                        logger.info("Endpoint %s with payload format %d returned: %s", endpoint, i+1, response.status_code)
                        if response.status_code in [200, 201, 409]:
                            successful_endpoint = endpoint
                            successful_payload = i+1
                            break
                    except Exception as e:
                        logger.debug("Endpoint %s with payload format %d failed: %s", endpoint, i+1, e)
                        continue
                if response and response.status_code in [200, 201, 409]:
                    break
            
            if response is None:
                logger.warning("All Systeme.io endpoints and payload formats failed - this is not critical")
                logger.warning("Student verification will continue without Systeme.io integration")
                logger.warning("Please check your Systeme.io API configuration if this is important")
                return None
            
            logger.info("✅ Successful endpoint: %s with payload format %s", successful_endpoint, successful_payload)

            logger.info("Systeme.io API response: %s - %s", response.status_code, response.text)

            if response.status_code == 404:
                logger.warning("Systeme.io API endpoint not found (404) - API may have changed")
                logger.warning("Student verification will continue without Systeme.io integration")
                return None
            elif response.status_code == 401:
                logger.warning("Systeme.io API authentication failed (401) - check API key")
                logger.warning("Student verification will continue without Systeme.io integration")
                return None
            elif response.status_code == 201:
                result = response.json()
                contact_id = result.get("id")
                logger.info("✅ Created/Updated Systeme.io contact: %s (ID: %s)", contact_data.get("email"), contact_id)

                # Apply achiever tag if applicable and verified
                if contact_id and SYSTEME_ACHIEVER_TAG_ID and contact_data.get("status") == "verified":
                    await _apply_achiever_tag(contact_id, client, headers)

                return contact_id
            elif response.status_code == 409:
                # Contact already exists - this is expected for verification updates
                logger.info("Contact already exists in Systeme.io: %s", contact_data.get("email"))
                # Try to update the existing contact with new tag
                # Note: Systeme.io doesn't provide easy way to update tags on existing contacts
                # The tag update happens when the contact is processed by Systeme.io workflows
                return "existing"
            elif response.status_code == 401:
                logger.error("❌ Systeme.io API authentication failed - check your API key")
                logger.error("Response: %s", response.text)
                return None
            elif response.status_code == 403:
                logger.error("❌ Systeme.io API access forbidden - check API permissions")
                logger.error("Response: %s", response.text)
                return None
            else:
                logger.warning("❌ Failed to create Systeme.io contact: HTTP %s", response.status_code)
                logger.warning("Response: %s", response.text)
                return None

    except Exception as e:
        logger.exception("Failed to create Systeme.io contact: %s", e)
        return None


async def _apply_achiever_tag(contact_id: str, client: httpx.AsyncClient, headers: Dict[str, str]) -> bool:
    """Apply achiever tag to contact"""
    try:
        # Apply tag using Systeme.io API format
        tag_payload = [SYSTEME_ACHIEVER_TAG_ID]
        
        response = await client.post(
            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
            headers=headers,
            json=tag_payload,
            timeout=10.0
        )
        
        if response.status_code == 200:
            logger.info("Applied achiever tag to contact: %s", contact_id)
            return True
        else:
            logger.warning("Failed to apply achiever tag: %s", response.text)
            return False
            
    except Exception as e:
        logger.exception("Failed to apply achiever tag: %s", e)
        return False


async def remove_contact_by_email(email: str) -> bool:
    """Remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact removal")
            return False
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Find contact by email
            response = await client.get(
                f"{SYSTEME_BASE_URL}/contacts",
                headers=headers,
                params={"email": email},
                timeout=10.0
            )
            
            if response.status_code == 200:
                result = response.json()
                contacts = result.get("data", [])
                
                if contacts:
                    contact_id = contacts[0].get("id")
                    
                    # Remove tags
                    await client.delete(
                        f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
                        headers=headers,
                        timeout=10.0
                    )
                    
                    # Delete contact
                    delete_response = await client.delete(
                        f"{SYSTEME_BASE_URL}/contacts/{contact_id}",
                        headers=headers,
                        timeout=10.0
                    )
                    
                    if delete_response.status_code == 200:
                        logger.info("Removed Systeme.io contact: %s", email)
                        return True
                    else:
                        logger.warning("Failed to delete contact: %s", delete_response.text)
                        return False
                else:
                    logger.warning("Contact not found in Systeme.io: %s", email)
                    return False
            else:
                logger.warning("Failed to find contact: %s", response.text)
                return False
        
    except Exception as e:
        logger.exception("Failed to remove Systeme.io contact: %s", e)
        return False


async def tag_achiever(contact_id: str) -> bool:
    """Add achiever tag to contact"""
    try:
        if not SYSTEME_API_KEY or not SYSTEME_ACHIEVER_TAG_ID:
            logger.warning("SYSTEME_API_KEY or SYSTEME_ACHIEVER_TAG_ID not set, skipping achiever tagging")
            return False
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
                headers=headers,
                json=[SYSTEME_ACHIEVER_TAG_ID],
                timeout=10.0
            )
            
            if response.status_code == 200:
                logger.info("Added achiever tag to contact: %s", contact_id)
                return True
            else:
                logger.warning("Failed to add achiever tag: %s", response.text)
                return False
        
    except Exception as e:
        logger.exception("Failed to tag achiever: %s", e)
        return False


async def untag_or_remove_contact(email: str, action: str = "untag") -> bool:
    """Untag or remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact action")
            return False
        
        headers = {
            "Authorization": f"Bearer {SYSTEME_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Find contact by email
            response = await client.get(
                f"{SYSTEME_BASE_URL}/contacts",
                headers=headers,
                params={"email": email},
                timeout=10.0
            )
            
            if response.status_code == 200:
                result = response.json()
                contacts = result.get("data", [])
                
                if contacts:
                    contact_id = contacts[0].get("id")
                    
                    if action == "untag":
                        # Remove all tags
                        await client.delete(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
                            headers=headers,
                            timeout=10.0
                        )
                        logger.info("Untagged Systeme.io contact: %s", email)
                        return True
                    elif action == "remove":
                        # Remove tags first
                        await client.delete(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags",
                            headers=headers,
                            timeout=10.0
                        )
                        
                        # Delete contact
                        delete_response = await client.delete(
                            f"{SYSTEME_BASE_URL}/contacts/{contact_id}",
                            headers=headers,
                            timeout=10.0
                        )
                        
                        if delete_response.status_code == 200:
                            logger.info("Removed Systeme.io contact: %s", email)
                            return True
                        else:
                            logger.warning("Failed to delete contact: %s", delete_response.text)
                            return False
                else:
                    logger.warning("Contact not found in Systeme.io: %s", email)
                    return False
            else:
                logger.warning("Failed to find contact: %s", response.text)
                return False
        
    except Exception as e:
        logger.exception("Failed to untag/remove Systeme.io contact: %s", e)
        return False


def create_contact_and_tag_sync(payload: Dict[str, Any]) -> Optional[str]:
    """Synchronous wrapper for create_contact_and_tag"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(create_contact_and_tag(payload))
    except Exception as e:
        logger.exception("Sync wrapper failed: %s", e)
        return None


def remove_contact_by_email_sync(email: str) -> bool:
    """Synchronous wrapper for remove_contact_by_email"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(remove_contact_by_email(email))
    except Exception as e:
        logger.exception("Sync wrapper failed: %s", e)
        return False


def untag_or_remove_contact_sync(email: str, action: str = "untag") -> bool:
    """Synchronous wrapper for untag_or_remove_contact"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(untag_or_remove_contact(email, action))
    except Exception as e:
        logger.exception("Sync wrapper failed: %s", e)
        return False
