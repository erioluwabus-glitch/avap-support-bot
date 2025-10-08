"""
Systeme.io service for contact management - Async implementation with httpx
"""
import os
import logging
from typing import Optional, Dict, Any, List
import httpx

logger = logging.getLogger(__name__)

SYSTEME_API_KEY = os.getenv("SYSTEME_API_KEY")
SYSTEME_VERIFIED_TAG_ID = os.getenv("SYSTEME_VERIFIED_TAG_ID")
SYSTEME_ACHIEVER_TAG_ID = os.getenv("SYSTEME_ACHIEVER_TAG_ID")
SYSTEME_BASE_URL = os.getenv("SYSTEME_BASE_URL", "https://api.systeme.io")


def validate_systeme_configuration() -> bool:
    """Validate Systeme.io configuration and provide helpful error messages"""
    issues = []

    if not SYSTEME_API_KEY:
        issues.append("SYSTEME_API_KEY environment variable not set")
    elif len(SYSTEME_API_KEY) < 10:
        issues.append("SYSTEME_API_KEY appears to be invalid (too short)")

    # Validate tag IDs more thoroughly
    if not SYSTEME_VERIFIED_TAG_ID:
        issues.append("SYSTEME_VERIFIED_TAG_ID environment variable not set")
    elif not SYSTEME_VERIFIED_TAG_ID.strip():
        issues.append("SYSTEME_VERIFIED_TAG_ID is empty")
    elif not SYSTEME_VERIFIED_TAG_ID.isdigit():
        issues.append(f"SYSTEME_VERIFIED_TAG_ID should be numeric, got: {SYSTEME_VERIFIED_TAG_ID}")
    elif len(SYSTEME_VERIFIED_TAG_ID) < 3:
        issues.append(f"SYSTEME_VERIFIED_TAG_ID too short: {SYSTEME_VERIFIED_TAG_ID}")

    if not SYSTEME_ACHIEVER_TAG_ID:
        issues.append("SYSTEME_ACHIEVER_TAG_ID environment variable not set")
    elif not SYSTEME_ACHIEVER_TAG_ID.strip():
        issues.append("SYSTEME_ACHIEVER_TAG_ID is empty")
    elif not SYSTEME_ACHIEVER_TAG_ID.isdigit():
        issues.append(f"SYSTEME_ACHIEVER_TAG_ID should be numeric, got: {SYSTEME_ACHIEVER_TAG_ID}")
    elif len(SYSTEME_ACHIEVER_TAG_ID) < 3:
        issues.append(f"SYSTEME_ACHIEVER_TAG_ID too short: {SYSTEME_ACHIEVER_TAG_ID}")

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


async def create_contact_and_tag(contact_data: Dict[str, Any]) -> Optional[str]:
    """Create contact in Systeme.io and apply tag"""
    try:
        # Validate configuration first
        if not validate_systeme_configuration():
            logger.error("Systeme.io configuration validation failed - cannot proceed with contact creation")
            return None

        logger.info(f"Systeme.io configuration validated successfully, BASE_URL: {SYSTEME_BASE_URL}")

        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact creation")
            logger.warning("Please set SYSTEME_API_KEY environment variable with your Systeme.io API key")
            logger.warning("Get your API key from: https://systeme.io/account/api")
            return None


        headers = {
            "X-API-Key": SYSTEME_API_KEY,
            "Content-Type": "application/json"
        }
        
        logger.info(f"Using API key format: {SYSTEME_API_KEY[:10]}... (length: {len(SYSTEME_API_KEY)})")

        # Create contact - try different payload formats for Systeme.io
        name_parts = contact_data.get("name", "").split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        # Try multiple payload formats based on current Systeme.io API
        contact_payloads = [
            # Format 1: Current Systeme.io API format with fields array
            {
                "email": contact_data.get("email"),
                "fields": [
                    {"slug": "first_name", "value": first_name},
                    {"slug": "last_name", "value": last_name},
                    {"slug": "phone_number", "value": contact_data.get("phone", "")}
                ],
                "tags": [SYSTEME_VERIFIED_TAG_ID] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 2: Standard format
            {
                "email": contact_data.get("email"),
                "firstName": first_name,
                "lastName": last_name,
                "phoneNumber": contact_data.get("phone", ""),
                "tags": [SYSTEME_VERIFIED_TAG_ID] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 3: Alternative format
            {
                "email": contact_data.get("email"),
                "first_name": first_name,
                "last_name": last_name,
                "phone": contact_data.get("phone", ""),
                "tags": [SYSTEME_VERIFIED_TAG_ID] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 4: Minimal format
            {
                "email": contact_data.get("email"),
                "name": contact_data.get("name", ""),
                "phone": contact_data.get("phone", ""),
                "tags": [SYSTEME_VERIFIED_TAG_ID] if contact_data.get("status") == "verified" else ["pending"]
            },
            # Format 5: Basic format
            {
                "email": contact_data.get("email"),
                "firstName": first_name,
                "lastName": last_name,
                "phoneNumber": contact_data.get("phone", "")
            }
        ]

        async with httpx.AsyncClient() as client:
            logger.info("Attempting to create Systeme.io contact for: %s", contact_data.get("email"))
            
            # Try different endpoint formats and payload formats
            # Updated endpoints based on current Systeme.io API documentation
            endpoints_to_try = [
                f"{SYSTEME_BASE_URL}/contacts",
                f"{SYSTEME_BASE_URL}/api/contacts",
                f"{SYSTEME_BASE_URL}/api/v1/contacts",
                f"{SYSTEME_BASE_URL}/api/v2/contacts",
                f"{SYSTEME_BASE_URL}/api/v3/contacts",
                f"https://api.systeme.io/contacts",  # Direct API URL
                f"https://api.systeme.io/api/contacts"  # Direct API URL with /api
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
                logger.warning("Common issues: Invalid API key, changed API endpoints, or API rate limits")
                return None
            
            logger.info("✅ Successful endpoint: %s with payload format %s", successful_endpoint, successful_payload)

            # Log response details for debugging
            logger.info("Systeme.io API response: %s", response.status_code)
            if response.status_code >= 400:
                logger.warning("Systeme.io API error response: %s", response.text[:500])  # Limit response text for logs
            else:
                logger.info("Systeme.io API success response: %s", response.text[:200])  # Limit response text for logs

            if response.status_code == 404:
                logger.warning("Systeme.io API endpoint not found (404) - API may have changed")
                logger.warning("Trying webhook-based integration as fallback...")
                return await _try_webhook_integration(contact_data)
            elif response.status_code == 401:
                logger.warning("Systeme.io API authentication failed (401) - check API key")
                logger.warning("Please verify your API key at: https://systeme.io/account/api")
                logger.warning("Make sure you're using the correct API key format (X-API-Key header)")
                logger.warning("Student verification will continue without Systeme.io integration")
                return None
            elif response.status_code == 201:
                result = response.json()
                contact_id = result.get("id")
                logger.info("✅ Created/Updated Systeme.io contact: %s (ID: %s)", contact_data.get("email"), contact_id)

                # Apply verified tag if applicable and verified
                logger.info(f"Checking tag conditions - contact_id: {contact_id}, status: {contact_data.get('status')}")

                if contact_id and SYSTEME_VERIFIED_TAG_ID and contact_data.get("status") == "verified":
                    logger.info(f"Applying verified tag to contact {contact_id}")
                    tag_success = await _apply_verified_tag(contact_id, client, headers)
                    if tag_success:
                        logger.info("✅ Successfully applied verified tag to contact %s", contact_id)
                    else:
                        logger.error("❌ Failed to apply verified tag to contact %s - contact created but not tagged", contact_id)

                if contact_id and SYSTEME_ACHIEVER_TAG_ID and contact_data.get("status") == "verified":
                    logger.info(f"Applying achiever tag to contact {contact_id}")
                    tag_success = await _apply_achiever_tag(contact_id, client, headers)
                    if tag_success:
                        logger.info("✅ Successfully applied achiever tag to contact %s", contact_id)
                    else:
                        logger.error("❌ Failed to apply achiever tag to contact %s - contact created but not tagged", contact_id)

                return contact_id
            elif response.status_code == 409:
                # Contact already exists - this is expected for verification updates
                logger.info("Contact already exists in Systeme.io: %s", contact_data.get("email"))
                # Try to find the existing contact and apply tags
                existing_contact_id = await _find_existing_contact_and_update_tags(contact_data, client, headers)
                return existing_contact_id if existing_contact_id else "existing"
            elif response.status_code == 422 and "already used" in str(response.text):
                # Contact already exists - try to find and update it with verified tag
                logger.info("Contact already exists in Systeme.io: %s - attempting to find and update", contact_data.get("email"))
                existing_contact_id = await _find_existing_contact_and_update_tags(contact_data, client, headers)
                return existing_contact_id
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


async def _apply_tag_to_contact(contact_id: str, tag_id: str, tag_type: str, client: httpx.AsyncClient, headers: Dict[str, str]) -> bool:
    """Apply tag to contact using correct Systeme.io API (unified function for verified and achiever tags)"""
    try:
        logger.info(f"Applying {tag_type} tag '{tag_id}' to contact {contact_id}")

        # Systeme.io API v4 format for applying tags
        tag_endpoints = [
            f"https://api.systeme.io/api/contacts/{contact_id}/tags",  # Primary API v4 endpoint
            f"{SYSTEME_BASE_URL}/api/contacts/{contact_id}/tags",
            f"https://api.systeme.io/contacts/{contact_id}/tags",
            f"{SYSTEME_BASE_URL}/contacts/{contact_id}/tags"
        ]

        # Try different payload formats for Systeme.io API
        tag_payloads = [
            {"tagId": tag_id},  # Systeme.io format
            {"tagIds": [tag_id]},  # Alternative format
            {"tag_id": tag_id},  # Legacy format
            tag_id  # Simple format
        ]

        for endpoint in tag_endpoints:
            for payload in tag_payloads:
                try:
                    logger.debug("Trying %s tag endpoint: %s with payload: %s", tag_type, endpoint, payload)
                    response = await client.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=15.0
                    )

                    logger.info("%s tag endpoint %s returned: %s", tag_type, endpoint, response.status_code)

                    if response.status_code in [200, 201]:
                        logger.info("✅ Applied %s tag to contact %s using endpoint: %s with payload: %s", tag_type, contact_id, endpoint, payload)
                        return True
                    elif response.status_code == 404:
                        logger.debug("%s tag endpoint %s returned 404, trying next payload", tag_type, endpoint)
                        continue
                    elif response.status_code == 422:
                        logger.warning("%s tag endpoint %s returned 422: %s", tag_type, endpoint, response.text[:300])
                        # This payload didn't work, try next one
                        continue
                    else:
                        logger.warning("%s tag endpoint %s returned %s: %s", tag_type, endpoint, response.status_code, response.text[:300])

                except Exception as e:
                    logger.debug("%s tag endpoint %s with payload %s failed: %s", tag_type, endpoint, payload, e)
                    continue

        # If all direct tagging endpoints failed, try alternative methods
        logger.warning("All %s tag endpoints failed, trying alternative tagging methods", tag_type)
        return await _apply_tag_alternative(contact_id, tag_id, client, headers)

    except Exception as e:
        logger.exception("Failed to apply %s tag to contact %s: %s", tag_type, contact_id, e)
        return False


async def _apply_verified_tag(contact_id: str, client: httpx.AsyncClient, headers: Dict[str, str]) -> bool:
    """Apply verified tag to contact"""
    return await _apply_tag_to_contact(contact_id, SYSTEME_VERIFIED_TAG_ID, "verified", client, headers)


async def _apply_tag_alternative(contact_id: str, tag_id: str, client: httpx.AsyncClient, headers: Dict[str, str]) -> bool:
    """Try alternative methods to apply tags when standard endpoints fail"""
    try:
        logger.info("Trying alternative tag application methods for contact %s with tag %s", contact_id, tag_id)

        # Method 1: Try to update the contact with tags using correct Systeme.io API format
        update_payloads = [
            {"tagId": tag_id},  # Systeme.io format
            {"tagIds": [tag_id]},  # Alternative format
            {"tag_id": tag_id},  # Legacy format
            {"tags": [tag_id]}  # Another format
        ]

        update_endpoints = [
            f"https://api.systeme.io/api/contacts/{contact_id}",  # Primary API v4 endpoint
            f"{SYSTEME_BASE_URL}/api/contacts/{contact_id}",
            f"https://api.systeme.io/contacts/{contact_id}"
        ]

        for endpoint in update_endpoints:
            for payload in update_payloads:
                try:
                    logger.debug("Trying alternative update endpoint: %s with payload: %s", endpoint, payload)
                    response = await client.put(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=15.0
                    )

                    if response.status_code in [200, 201, 204]:
                        logger.info("✅ Applied tag via contact update at %s for contact %s with payload: %s", endpoint, contact_id, payload)
                        return True
                    elif response.status_code == 404:
                        logger.debug("Update endpoint %s returned 404, trying next payload", endpoint)
                        continue

                except Exception as e:
                    logger.debug("Update endpoint %s with payload %s failed: %s", endpoint, payload, e)
                    continue

        # Method 2: Try webhook as last resort (if configured)
        webhook_url = os.getenv("SYSTEME_WEBHOOK_URL")
        if webhook_url:
            logger.info("Trying webhook for tag application as last resort")
            webhook_payload = {
                "contact_id": contact_id,
                "tag_id": tag_id,
                "action": "apply_tag",
                "source": "avap_bot_fallback"
            }

            try:
                response = await client.post(
                    webhook_url,
                    json=webhook_payload,
                    timeout=15.0
                )

                if response.status_code == 200:
                    logger.info("✅ Applied tag via webhook for contact %s", contact_id)
                    return True

            except Exception as e:
                logger.debug("Webhook tag application failed: %s", e)

        logger.warning("All alternative tag application methods failed for contact %s", contact_id)
        logger.warning("This indicates API permission issues or incorrect tag ID")
        return False

    except Exception as e:
        logger.exception("Alternative tag application failed for contact %s: %s", contact_id, e)
        return False


async def _apply_achiever_tag(contact_id: str, client: httpx.AsyncClient, headers: Dict[str, str]) -> bool:
    """Apply achiever tag to contact"""
    return await _apply_tag_to_contact(contact_id, SYSTEME_ACHIEVER_TAG_ID, "achiever", client, headers)


async def _find_existing_contact_and_update_tags(contact_data: Dict[str, Any], client: httpx.AsyncClient, headers: Dict[str, str]) -> Optional[str]:
    """Find existing contact and update tags"""
    try:
        email = contact_data.get("email")
        logger.info(f"Finding existing contact for: {email}")

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
                logger.info(f"Found existing contact: {email} (ID: {contact_id})")

                # Apply verified tag if applicable and verified
                if SYSTEME_VERIFIED_TAG_ID and contact_data.get("status") == "verified":
                    logger.info(f"Applying verified tag to existing contact {contact_id}")
                    tag_success = await _apply_verified_tag(contact_id, client, headers)
                    if tag_success:
                        logger.info("✅ Successfully applied verified tag to existing contact %s", contact_id)
                    else:
                        logger.error("❌ Failed to apply verified tag to existing contact %s", contact_id)

                if SYSTEME_ACHIEVER_TAG_ID and contact_data.get("status") == "verified":
                    logger.info(f"Applying achiever tag to existing contact {contact_id}")
                    tag_success = await _apply_achiever_tag(contact_id, client, headers)
                    if tag_success:
                        logger.info("✅ Successfully applied achiever tag to existing contact %s", contact_id)
                    else:
                        logger.error("❌ Failed to apply achiever tag to existing contact %s", contact_id)

                return contact_id
            else:
                logger.warning(f"No existing contact found for: {email}")
                return None
        else:
            logger.warning(f"Failed to find existing contact: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.exception(f"Failed to find and update existing contact: {e}")
        return None


async def remove_contact_by_email(email: str) -> bool:
    """Remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact removal")
            return False
        
        headers = {
            "X-API-Key": SYSTEME_API_KEY,
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
    """Add achiever tag to contact using correct Systeme.io API"""
    try:
        if not SYSTEME_API_KEY or not SYSTEME_ACHIEVER_TAG_ID:
            logger.warning("SYSTEME_API_KEY or SYSTEME_ACHIEVER_TAG_ID not set, skipping achiever tagging")
            return False

        headers = {
            "X-API-Key": SYSTEME_API_KEY,
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            return await _apply_tag_to_contact(contact_id, SYSTEME_ACHIEVER_TAG_ID, "achiever", client, headers)

    except Exception as e:
        logger.exception("Failed to tag achiever for contact %s: %s", contact_id, e)
        return False


async def untag_or_remove_contact(email: str, action: str = "untag") -> bool:
    """Untag or remove contact from Systeme.io by email"""
    try:
        if not SYSTEME_API_KEY:
            logger.warning("SYSTEME_API_KEY not set, skipping contact action")
            return False
        
        headers = {
            "X-API-Key": SYSTEME_API_KEY,
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




async def _try_webhook_integration(contact_data: Dict[str, Any]) -> Optional[str]:
    """Try webhook-based integration as fallback when API fails"""
    try:
        logger.info("Attempting webhook-based Systeme.io integration for: %s", contact_data.get("email"))
        
        # Check if webhook URL is configured
        webhook_url = os.getenv("SYSTEME_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("SYSTEME_WEBHOOK_URL not configured - skipping webhook integration")
            return None
        
        # Prepare webhook payload
        webhook_payload = {
            "email": contact_data.get("email"),
            "name": contact_data.get("name", ""),
            "phone": contact_data.get("phone", ""),
            "status": contact_data.get("status", "verified"),
            "source": "avap_bot",
            "timestamp": contact_data.get("timestamp", "")
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=webhook_payload,
                timeout=10.0
            )
            
            if response.status_code == 200:
                logger.info("✅ Webhook integration successful for: %s", contact_data.get("email"))
                return "webhook_success"
            else:
                logger.warning("Webhook integration failed: %s - %s", response.status_code, response.text)
                return None
                
    except Exception as e:
        logger.exception("Webhook integration failed: %s", e)
        return None
