# avap_bot/services/systeme_service.py
import os
import logging
import time
import requests
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger("avap_bot.systeme")

# Config / env parsing & normalization
BASE = os.environ.get("SYSTEME_BASE_URL", "https://api.systeme.io")

# Get API key and strip any whitespace/newlines
API_KEY = (os.environ.get("SYSTEME_API_KEY") or "").strip()

# Use X-API-Key header as required by Systeme.io API
HEADERS = {
    "X-API-Key": API_KEY if API_KEY else "",
    "Content-Type": "application/json",
}

# Default limit for API calls (Systeme.io requires 10-100 range)
DEFAULT_LIMIT = 10

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
    
    # Log request details (but mask the API key)
    logger.info("Systeme.io request to: %s", url)
    logger.info("Request headers: %s", {k: v for k, v in HEADERS.items() if k != "X-API-Key"})
    logger.info("Request payload: %s", payload)
    
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=timeout)
            last_resp = resp
            
            # Log response details
            logger.info("Systeme.io response status: %s", resp.status_code)
            logger.info("Systeme.io response body: %s", resp.text[:500])  # Limit body length
            
        except requests.RequestException as e:
            logger.warning("Network error posting to %s (attempt %d): %s", url, attempt, e)
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
                continue
            return None, str(e)

        # Authentication failure => stop and report
        if resp.status_code == 401:
            logger.error("Systeme API authentication failed (401) - Invalid or expired API key")
            logger.error("Please check SYSTEME_API_KEY environment variable")
            logger.error("API key format: %s... (length: %s)", API_KEY[:10] if API_KEY else "None", len(API_KEY) if API_KEY else 0)
            return resp, resp.text

        # Client error (not rate limit) => don't retry
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            logger.warning("Client error %s for %s: %s", resp.status_code, url, resp.text)
            return resp, resp.text

        # Success
        if 200 <= resp.status_code < 300:
            logger.info("Systeme.io request successful")
            return resp, resp.text

        # 429 or 5xx => retry
        logger.info("Transient status %s for %s; retrying (attempt %d)", resp.status_code, url, attempt)
        if attempt < max_attempts:
            time.sleep(backoff)
            backoff *= 2

    return last_resp, (last_resp.text if last_resp is not None else "No response")

# --- Public API functions ---
def validate_api_key() -> bool:
    """Lightweight startup validation for the API key with proper error handling."""
    if not API_KEY:
        logger.error("SYSTEME_API_KEY not set or empty.")
        return False
    
    # Log API key format for debugging (first 10 chars only for security)
    logger.info("SYSTEME_API_KEY format: %s... (length: %s)", API_KEY[:10], len(API_KEY))
    
    try:
        # Use safe limit parameter (10-100 range required by API)
        logger.info("Validating Systeme.io API key...")
        r = requests.get(f"{BASE}/api/contacts?limit={DEFAULT_LIMIT}", headers=HEADERS, timeout=10)
        logger.info("Systeme API validation response: %s", r.status_code)
        logger.info("Systeme API validation body: %s", r.text[:200])
        
        # Handle authentication errors
        if r.status_code in (401, 403):
            logger.error("Systeme API authentication failed (%s) - Invalid or expired API key", r.status_code)
            logger.error("Please check your SYSTEME_API_KEY in environment variables")
            logger.error("Make sure the key is correct and not expired")
            return False
        
        # Handle validation errors (422) - check if it's a limit issue
        if r.status_code == 422:
            try:
                response_json = r.json()
                violations = response_json.get("violations", [])
                logger.warning("Systeme API returned validation error (422). Violations: %s", violations)
                
                # Check if violation is only about limit parameter
                limit_violations = [v for v in violations if v.get("propertyPath") == "limit"]
                if limit_violations:
                    logger.info("Retrying validation with safe limit=%s due to limit violation", DEFAULT_LIMIT)
                    # Retry with explicit safe limit
                    r2 = requests.get(f"{BASE}/api/contacts?limit={DEFAULT_LIMIT}", headers=HEADERS, timeout=10)
                    if r2.status_code in (401, 403):
                        logger.error("Systeme auth error on retry (status=%s)", r2.status_code)
                        return False
                    elif r2.ok:
                        logger.info("Systeme API key validated on corrected request (status=%s)", r2.status_code)
                        return True
                    else:
                        logger.warning("Systeme retry returned status=%s body=%s", r2.status_code, r2.text[:200])
                        return False
                else:
                    # Other validation errors (not limit) -> fail validation
                    logger.error("Systeme API validation failed due to request errors: %s", violations)
                    return False
            except Exception as e:
                logger.warning("Systeme API returned 422 and response body isn't JSON: %s", e)
                return False
        
        # Handle successful responses
        if r.ok:
            logger.info("Systeme API key validation successful (status=%s)", r.status_code)
            return True
        
        # Handle other errors
        logger.warning("Unexpected Systeme validation status=%s body=%s", r.status_code, r.text[:200])
        return False
        
    except Exception as e:
        logger.exception("Systeme API validation request failed: %s", e)
        logger.error("This might be due to network issues or invalid API key")
        return False

def create_contact(email: str, extra: Optional[Dict[str,Any]] = None) -> Tuple[bool, Optional[int], Optional[str]]:
    """Create a contact in Systeme.io. Returns (ok, contact_id, error_text)."""
    payload = {"email": email}
    if extra:
        payload.update(extra)
    
    logger.info("Creating contact in Systeme.io for email: %s", email)
    logger.info("Contact payload: %s", payload)
    
    resp, body = safe_post("/api/contacts", payload)
    
    if resp is None:
        logger.error("Failed to create contact - no response: %s", body)
        return False, None, body
    
    logger.info("Systeme.io contact creation response: %s", resp.status_code)
    
    if resp.status_code in (200, 201):
        try:
            data = resp.json()
            contact_id = data.get("id")
            logger.info("Successfully created contact with ID: %s", contact_id)
            return True, int(contact_id) if contact_id else None, None
        except Exception as e:
            logger.warning("Contact created but failed to parse response: %s", e)
            logger.warning("Response body: %s", body)
            return True, None, None
    elif resp.status_code == 401:
        logger.error("Systeme.io API authentication failed (401) - Invalid or expired API key")
        logger.error("Please check SYSTEME_API_KEY environment variable")
        logger.error("API key format: %s... (length: %s)", API_KEY[:10] if API_KEY else "None", len(API_KEY) if API_KEY else 0)
        return False, None, "Authentication failed - Invalid API key"
    elif resp.status_code == 422:
        # Handle duplicate email error
        try:
            error_data = resp.json()
            violations = error_data.get("violations", [])
            email_violations = [v for v in violations if v.get("propertyPath") == "email"]
            if email_violations and "already used" in email_violations[0].get("message", ""):
                logger.info("Contact already exists in Systeme.io for email: %s", email)
                return True, None, "Contact already exists"  # Return success since contact exists
        except Exception as e:
            logger.warning("Failed to parse 422 error response: %s", e)
        
        logger.warning("Systeme.io validation error (422) for email: %s", email)
        return False, None, "Validation error - Contact may already exist"
    else:
        logger.error("Failed to create contact - Status: %s, Body: %s", resp.status_code, body)
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
        logger.info("Using headers: %s", {k: v for k, v in HEADERS.items() if k != "X-API-Key"})
        logger.info("API key format: %s... (length: %s)", API_KEY[:10], len(API_KEY))
        
        r = requests.get(f"{BASE}/api/contacts?limit={DEFAULT_LIMIT}", headers=HEADERS, timeout=10)
        
        logger.info("Systeme.io test response status: %s", r.status_code)
        logger.info("Systeme.io test response body: %s", r.text[:200])
        
        if r.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed (401) - Invalid or expired API key",
                "suggestion": "Check if SYSTEME_API_KEY is correct and not expired",
                "api_key_format": f"{API_KEY[:10]}... (length: {len(API_KEY)})"
            }
        elif r.status_code == 200:
            try:
                data = r.json()
                contacts_count = len(data.get('data', []))
                return {
                    "status": "success",
                    "message": "Systeme.io connection successful",
                    "contacts_count": contacts_count,
                    "api_key_format": f"{API_KEY[:10]}... (length: {len(API_KEY)})"
                }
            except Exception as e:
                return {
                    "status": "warning",
                    "message": f"Connection successful but failed to parse response: {e}",
                    "suggestion": "API is working but response format unexpected"
                }
        else:
            return {
                "status": "warning",
                "message": f"Unexpected status code: {r.status_code}",
                "suggestion": "API might be working but with different response",
                "response_body": r.text[:200]
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Connection failed: {str(e)}",
            "suggestion": "Check network connection and API key"
        }