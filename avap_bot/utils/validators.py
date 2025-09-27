"""
Validation utilities for user input
"""
import re
from typing import Optional


def validate_email(email: str) -> bool:
    """Validate email address format"""
    if not email or not isinstance(email, str):
        return False
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def validate_phone(phone: str) -> bool:
    """Validate phone number format"""
    if not phone or not isinstance(phone, str):
        return False
    
    # Remove common phone number characters
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone.strip())
    
    # Check if it's a valid phone number (7-15 digits)
    if not re.match(r'^\d{7,15}$', cleaned):
        return False
    
    return True


def validate_name(name: str) -> bool:
    """Validate name format"""
    if not name or not isinstance(name, str):
        return False
    
    # Name should be 2-50 characters, letters and spaces only
    cleaned = name.strip()
    if len(cleaned) < 2 or len(cleaned) > 50:
        return False
    
    # Allow letters, spaces, hyphens, and apostrophes
    if not re.match(r"^[a-zA-Z\s\-']+$", cleaned):
        return False
    
    return True


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input"""
    if not text or not isinstance(text, str):
        return ""
    
    # Remove excessive whitespace
    cleaned = re.sub(r'\s+', ' ', text.strip())
    
    # Truncate if too long
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()
    
    return cleaned


def validate_telegram_id(telegram_id: str) -> bool:
    """Validate Telegram user ID format"""
    if not telegram_id or not isinstance(telegram_id, str):
        return False
    
    try:
        user_id = int(telegram_id)
        # Telegram user IDs are typically positive integers
        return user_id > 0
    except ValueError:
        return False


def valid_email(email: str) -> bool:
    """Alias for validate_email for compatibility"""
    return validate_email(email)


def valid_phone(phone: str) -> bool:
    """Alias for validate_phone for compatibility"""
    return validate_phone(phone)
