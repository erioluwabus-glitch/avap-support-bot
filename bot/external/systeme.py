"""
Handles all interactions with the Systeme.io API.
"""
from typing import Optional
import requests

from ..config import SYSTEME_API_KEY, SYSTEME_VERIFIED_STUDENT_TAG_ID, logger

def create_contact(first_name: str, last_name: str, email: str, phone: str) -> Optional[int]:
    """
    Creates a new contact in Systeme.io and applies a tag if configured.
    Returns the created contact's ID, or None if it fails.
    """
    if not SYSTEME_API_KEY:
        logger.info("SYSTEME_API_KEY not set, skipping contact creation.")
        return None

    try:
        # Create the contact
        create_url = "https://api.systeme.io/api/contacts"
        payload = {"first_name": first_name, "last_name": last_name, "email": email, "phone": phone}
        headers = {"Content-Type": "application/json", "X-Auth-Token": SYSTEME_API_KEY}

        r = requests.post(create_url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        contact_id = data.get("id") or data.get("contact_id")

        if not contact_id:
            logger.error(f"Systeme.io contact creation for {email} did not return an ID.")
            return None

        logger.info(f"Successfully created Systeme.io contact for {email} with ID {contact_id}.")

        # If a tag ID is provided, apply it to the new contact
        if SYSTEME_VERIFIED_STUDENT_TAG_ID:
            tag_url = f"https://api.systeme.io/api/contacts/{contact_id}/tags"
            tag_payload = {"tag_id": int(SYSTEME_VERIFIED_STUDENT_TAG_ID)}

            tag_r = requests.post(tag_url, json=tag_payload, headers=headers, timeout=10)
            tag_r.raise_for_status()
            logger.info(f"Successfully applied tag {SYSTEME_VERIFIED_STUDENT_TAG_ID} to contact {contact_id}.")

        return contact_id

    except requests.exceptions.RequestException as e:
        logger.exception(f"Systeme.io API request failed for email {email}: {e}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during Systeme.io contact creation for {email}: {e}")
        return None
