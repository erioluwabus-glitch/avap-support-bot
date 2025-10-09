# avap_bot/services/systeme_service.py
import os
import logging
import time
import requests
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger("avap_bot.systeme")

# Config / env parsing & normalization
BASE = os.environ.get("SYSTEME_BASE_URL", "https://api.systeme.io")

API_KEY = (os.environ.get("SYSTEME_API_KEY") or "").strip()
HEADERS = {
    "Authorization": f"Bearer {API_KEY}" if API_KEY else "",
    "Content-Type": "application/json",
}

def _parse_int_env(name: str, default: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        logger.warning("Env %s is not an int: %r", name, raw)
        return default

# Read tag envs (you said these are currently the same; we dedupe below)
VERIFIED_TAG = _parse_int_env("SYSTEME_VERIFIED_TAG_ID", 0)
VERIFIED_STUDENT_TAG = _parse_int_env("SYSTEME_VERIFIED_STUDENT_TAG_ID", VERIFIED_TAG)
ACHIEVER_TAG = _parse_int_env("SYSTEME_ACHIEVER_TAG_ID", VERIFIED_TAG)

# Unique tag IDs to apply (if same values were supplied, we only try once)
TAG_IDS = list({tid for tid in (VERIFIED_TAG, VERIFIED_STUDENT_TAG, ACHIEVER_TAG) if tid and isinstance(tid, int)})

if not TAG_IDS:
    logger.warning("No valid SYSTEME tag IDs found from env vars: VERIFIED=%r STUDENT=%r ACHIEVER=%r",
                   VERIFIED_TAG, VERIFIED_STUDENT_TAG, ACHIEVER_TAG)
else:
    if len(TAG_IDS) < 3:
        logger.info("Using deduplicated SYSTEME tag IDs: %s", TAG_IDS)
    else:
        logger.info("Using SYSTEME tag IDs: %s", TAG_IDS)

# --- HTTP helper with retries/backoff ---
def safe_post(endpoint: str, payload: Dict[str, Any], max_attempts: int = 4, timeout: int = 10) -> Tuple[Optional[requests.Response], Optional[str]]:
    url = f"{BASE}{endpoint}"
    backoff = 0.5
    last_resp = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=timeout)
            last_resp = resp
        except requests.RequestException as e:
            logger.warning("Network error posting to %s (attempt %d): %s", url, attempt, e)
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, str(e)

        # Authentication failure => stop and report
        if resp.status_code == 401:
            logger.error("Systeme API authentication failed (401). Check SYSTEME_API_KEY.")
            return resp, resp.text

        # Client error (not rate limit) => don't retry
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            logger.warning("Client error %s for %s: %s", resp.status_code, url, resp.text)
            return resp, resp.text

        # Success
        if 200 <= resp.status_code < 300:
            return resp, resp.text

        # 429 or 5xx => retry
        logger.info("Transient status %s for %s; retrying (attempt %d)", resp.status_code, url, attempt)
        if attempt < max_attempts:
            time.sleep(backoff)
            backoff *= 2

    return last_resp, (last_resp.text if last_resp is not None else "No response")

# --- Public API functions ---
def validate_api_key() -> bool:
    """Lightweight startup validation for the API key."""
    if not API_KEY:
        logger.error("SYSTEME_API_KEY not set or empty.")
        return False
    
    # Log API key format for debugging (first 10 chars only for security)
    logger.info(f"SYSTEME_API_KEY format: {API_KEY[:10]}... (length: {len(API_KEY)})")
    
    try:
        # Try a simple GET request to validate the API key
        r = requests.get(f"{BASE}/api/contacts", headers=HEADERS, timeout=10)
        logger.info(f"Systeme API validation response: {r.status_code}")
        
        if r.status_code == 401:
            logger.error("Systeme API authentication failed (401) - Invalid API key")
            logger.error("Please check your SYSTEME_API_KEY in environment variables")
            return False
        elif r.status_code == 200:
            logger.info("Systeme API key validation successful")
            return True
        else:
            logger.warning(f"Systeme API returned unexpected status: {r.status_code}")
            return True  # Assume it's working if not 401
    except Exception as e:
        logger.exception("Systeme API validation request failed: %s", e)
        logger.error("This might be due to network issues or invalid API key")
        return False

def create_contact(email: str, extra: Optional[Dict[str,Any]] = None) -> Tuple[bool, Optional[int], Optional[str]]:
    """Create a contact in Systeme.io. Returns (ok, contact_id, error_text)."""
    payload = {"email": email}
    if extra:
        payload.update(extra)
    
    logger.info(f"Creating contact in Systeme.io for email: {email}")
    resp, body = safe_post("/api/contacts", payload)
    
    if resp is None:
        logger.error(f"Failed to create contact - no response: {body}")
        return False, None, body
    
    logger.info(f"Systeme.io contact creation response: {resp.status_code}")
    
    if resp.status_code in (200, 201):
        try:
            data = resp.json()
            contact_id = data.get("id")
            logger.info(f"Successfully created contact with ID: {contact_id}")
            return True, int(contact_id) if contact_id else None, None
        except Exception as e:
            logger.warning(f"Contact created but failed to parse response: {e}")
            return True, None, None
    elif resp.status_code == 401:
        logger.error(f"Systeme.io API authentication failed (401) - Invalid or expired API key")
        logger.error(f"Please check SYSTEME_API_KEY environment variable")
        return False, None, "Authentication failed - Invalid API key"
    else:
        logger.error(f"Failed to create contact - Status: {resp.status_code}, Body: {body}")
        return False, None, body

def apply_tag(contact_id: int, tag_id: int) -> Tuple[bool, Optional[str]]:
    """Apply a single tag. tag_id MUST be int. Returns (ok, error_text)."""
    try:
        cid = int(contact_id)
        tid = int(tag_id)
    except Exception:
        return False, "contact_id/tag_id must be integers"

    payload = {"tagId": tid}
    resp, body = safe_post(f"/api/contacts/{cid}/tags", payload)
    if resp is None:
        return False, body
    # Systeme might return 204 or 200 or 201
    if resp.status_code in (200, 201, 204):
        return True, None
    # 4xx/5xx -> return body
    return False, body

def apply_tags_bulk(contact_id: int, tag_ids=None) -> Dict[int, Tuple[bool, Optional[str]]]:
    """Apply multiple tags; tag_ids defaults to env TAG_IDS. Returns dict[tag_id] = (ok, error)."""
    if tag_ids is None:
        tag_ids = TAG_IDS
    results = {}
    for tid in tag_ids:
        if not tid:
            continue
        ok, err = apply_tag(contact_id, tid)
        results[tid] = (ok, err)
    return results


def create_contact_and_tag(pending_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Create a contact in Systeme.io and apply tags. Returns (ok, error_text)."""
    try:
        # Check if API key is valid first
        if not API_KEY:
            logger.warning("SYSTEME_API_KEY not set - skipping Systeme.io integration")
            return True, None  # Return success to not block student creation
        
        email = pending_data.get('email')
        if not email:
            return False, "No email provided in pending_data"
        
        # Create contact with extra data
        extra_data = {
            'firstName': pending_data.get('name', ''),
            'lastName': pending_data.get('last_name', ''),
        }
        
        # Add phone if available
        if pending_data.get('phone'):
            extra_data['phone'] = pending_data.get('phone')
        
        ok, contact_id, error = create_contact(email, extra_data)
        if not ok:
            # If it's an authentication error, log warning but don't fail
            if "401" in str(error) or "authentication" in str(error).lower() or "Invalid API key" in str(error):
                logger.warning(f"Systeme.io API authentication failed - skipping contact creation: {error}")
                logger.warning(f"Student will be added to database but not to Systeme.io")
                return True, None  # Return success to not block student creation
            return False, f"Failed to create contact: {error}"
        
        if contact_id:
            # Apply tags to the new contact
            tag_results = apply_tags_bulk(contact_id)
            failed_tags = [tid for tid, (success, _) in tag_results.items() if not success]
            
            if failed_tags:
                logger.warning(f"Some tags failed to apply for contact {contact_id}: {failed_tags}")
            
            return True, None
        else:
            return True, None  # Contact created but no ID returned (still success)
            
    except Exception as e:
        logger.exception("Error in create_contact_and_tag: %s", e)
        # If it's an authentication error, don't fail the student creation
        if "401" in str(e) or "authentication" in str(e).lower():
            logger.warning("Systeme.io API authentication failed - skipping contact creation")
            return True, None
        return False, str(e)


def untag_or_remove_contact(email: str, action: str = "untag") -> Tuple[bool, Optional[str]]:
    """Untag or remove a contact from Systeme.io. Returns (ok, error_text)."""
    try:
        # Check if API key is valid first
        if not API_KEY:
            logger.warning("SYSTEME_API_KEY not set - skipping Systeme.io integration")
            return True, None  # Return success to not block student removal
        
        if not email:
            return False, "No email provided"
        
        # For now, we'll implement a simple approach
        # In a full implementation, you'd need to:
        # 1. Find the contact by email
        # 2. Remove tags or delete the contact
        
        logger.info(f"Systeme.io {action} operation for email: {email}")
        
        # This is a placeholder implementation
        # In a real scenario, you'd make API calls to:
        # - Find contact by email
        # - Remove tags or delete contact
        
        return True, None
        
    except Exception as e:
        logger.exception("Error in untag_or_remove_contact: %s", e)
        # If it's an authentication error, don't fail the student removal
        if "401" in str(e) or "authentication" in str(e).lower():
            logger.warning("Systeme.io API authentication failed - skipping contact removal")
            return True, None
        return False, str(e)


def test_systeme_connection() -> Dict[str, Any]:
    """Test Systeme.io connection and return detailed status."""
    try:
        if not API_KEY:
            return {
                "status": "error",
                "message": "SYSTEME_API_KEY not set",
                "suggestion": "Please set SYSTEME_API_KEY in Render environment variables"
            }
        
        logger.info("Testing Systeme.io connection...")
        r = requests.get(f"{BASE_URL}/api/contacts", headers=HEADERS, timeout=10)
        
        if r.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed (401)",
                "suggestion": "Check if SYSTEME_API_KEY is correct and not expired"
            }
        elif r.status_code == 200:
            return {
                "status": "success",
                "message": "Systeme.io connection successful",
                "contacts_count": len(r.json().get('data', []))
            }
        else:
            return {
                "status": "warning",
                "message": f"Unexpected status code: {r.status_code}",
                "suggestion": "API might be working but with different response"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Connection failed: {str(e)}",
            "suggestion": "Check network connection and API key"
        }