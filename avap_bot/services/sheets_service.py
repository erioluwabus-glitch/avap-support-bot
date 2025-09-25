"""
Google Sheets service for data storage
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

logger = logging.getLogger(__name__)

# Google Sheets IDs
VERIFICATION_SHEET_ID = os.getenv("GOOGLE_SHEET_ID_VERIFICATION")
ASSIGNMENTS_SHEET_ID = os.getenv("GOOGLE_SHEET_ID_ASSIGNMENTS")
WINS_SHEET_ID = os.getenv("GOOGLE_SHEET_ID_WINS")
QUESTIONS_SHEET_ID = os.getenv("GOOGLE_SHEET_ID_FAQ")

# Google credentials
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

_sheets_client = None


def _get_sheets_client():
    """Get Google Sheets client"""
    global _sheets_client
    if not GSPREAD_AVAILABLE:
        raise RuntimeError("gspread not available")
    
    if _sheets_client is None:
        if GOOGLE_CREDENTIALS_JSON:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            creds = Credentials.from_service_account_info(creds_dict)
        else:
            creds = Credentials.from_service_account_file("credentials.json")
        
        _sheets_client = gspread.authorize(creds)
    
    return _sheets_client


def append_pending_verification(record: Dict[str, Any]) -> bool:
    """Append pending verification to Google Sheets"""
    try:
        if not VERIFICATION_SHEET_ID:
            logger.warning("VERIFICATION_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(VERIFICATION_SHEET_ID).worksheet("Verification")
        
        row = [
            record.get("name", ""),
            record.get("email", ""),
            record.get("phone", ""),
            record.get("status", "Pending"),
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        sheet.append_row(row)
        logger.info("Added pending verification to sheets: %s", record.get('email'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append pending verification to sheets: %s", e)
        return False


def update_verification_status(email: str, status: str) -> bool:
    """Update verification status in Google Sheets"""
    try:
        if not VERIFICATION_SHEET_ID:
            logger.warning("VERIFICATION_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(VERIFICATION_SHEET_ID).worksheet("Verification")
        
        # Find row by email
        try:
            cell = sheet.find(email)
            sheet.update_cell(cell.row, 4, status)  # Status column
            logger.info("Updated verification status: %s -> %s", email, status)
            return True
        except gspread.exceptions.CellNotFound:
            logger.warning("Email not found in verification sheet: %s", email)
            return False
        
    except Exception as e:
        logger.exception("Failed to update verification status: %s", e)
        return False


def append_submission(record: Dict[str, Any]) -> bool:
    """Append assignment submission to Google Sheets"""
    try:
        if not ASSIGNMENTS_SHEET_ID:
            logger.warning("ASSIGNMENTS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(ASSIGNMENTS_SHEET_ID).worksheet("Assignments")
        
        row = [
            record.get("username", ""),
            record.get("telegram_id", ""),
            record.get("module", ""),
            record.get("type", ""),
            record.get("file_id", ""),
            record.get("file_name", ""),
            record.get("submitted_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            record.get("status", "Pending"),
            "",  # Grade column
            ""   # Comments column
        ]
        
        sheet.append_row(row)
        logger.info("Added submission to sheets: %s - Module %s", record.get('username'), record.get('module'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append submission to sheets: %s", e)
        return False


def update_submission_grade(username: str, module: str, grade: int) -> bool:
    """Update submission grade in Google Sheets"""
    try:
        if not ASSIGNMENTS_SHEET_ID:
            logger.warning("ASSIGNMENTS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(ASSIGNMENTS_SHEET_ID).worksheet("Assignments")
        
        # Find row by username and module
        try:
            cell = sheet.find(username)
            # Check if module matches (assuming module is in column 3)
            if sheet.cell(cell.row, 3).value == module:
                sheet.update_cell(cell.row, 8, grade)  # Grade column
                sheet.update_cell(cell.row, 7, "Graded")  # Status column
                logger.info("Updated submission grade: %s - Module %s - Grade %s", username, module, grade)
                return True
        except gspread.exceptions.CellNotFound:
            logger.warning("Submission not found: %s - Module %s", username, module)
            return False
        
    except Exception as e:
        logger.exception("Failed to update submission grade: %s", e)
        return False


def add_grade_comment(username: str, module: str, comment: str) -> bool:
    """Add grade comment to Google Sheets"""
    try:
        if not ASSIGNMENTS_SHEET_ID:
            logger.warning("ASSIGNMENTS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(ASSIGNMENTS_SHEET_ID).worksheet("Assignments")
        
        # Find row by username and module
        try:
            cell = sheet.find(username)
            if sheet.cell(cell.row, 3).value == module:
                sheet.update_cell(cell.row, 9, comment)  # Comments column
                logger.info("Added grade comment: %s - Module %s", username, module)
                return True
        except gspread.exceptions.CellNotFound:
            logger.warning("Submission not found for comment: %s - Module %s", username, module)
            return False
        
    except Exception as e:
        logger.exception("Failed to add grade comment: %s", e)
        return False


def append_win(record: Dict[str, Any]) -> bool:
    """Append win to Google Sheets"""
    try:
        if not WINS_SHEET_ID:
            logger.warning("WINS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(WINS_SHEET_ID).worksheet("Wins")
        
        row = [
            record.get("username", ""),
            record.get("telegram_id", ""),
            record.get("type", ""),
            record.get("file_id", ""),
            record.get("file_name", ""),
            record.get("shared_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        sheet.append_row(row)
        logger.info("Added win to sheets: %s - %s", record.get('username'), record.get('type'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append win to sheets: %s", e)
        return False


def append_question(record: Dict[str, Any]) -> bool:
    """Append question to Google Sheets"""
    try:
        if not QUESTIONS_SHEET_ID:
            logger.warning("QUESTIONS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(QUESTIONS_SHEET_ID).worksheet("Questions")
        
        row = [
            record.get("username", ""),
            record.get("telegram_id", ""),
            record.get("question_text", ""),
            record.get("file_id", ""),
            record.get("file_name", ""),
            record.get("asked_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            record.get("status", "Pending"),
            ""  # Answer column
        ]
        
        sheet.append_row(row)
        logger.info("Added question to sheets: %s", record.get('username'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append question to sheets: %s", e)
        return False


def get_student_submissions(username: str) -> List[Dict[str, Any]]:
    """Get student submissions from Google Sheets"""
    try:
        if not ASSIGNMENTS_SHEET_ID:
            return []
        
        client = _get_sheets_client()
        sheet = client.open_by_key(ASSIGNMENTS_SHEET_ID).worksheet("Assignments")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter by username
        student_submissions = [record for record in records if record.get("username") == username]
        
        return student_submissions
        
    except Exception as e:
        logger.exception("Failed to get student submissions: %s", e)
        return []


def get_student_wins(username: str) -> List[Dict[str, Any]]:
    """Get student wins from Google Sheets"""
    try:
        if not WINS_SHEET_ID:
            return []
        
        client = _get_sheets_client()
        sheet = client.open_by_key(WINS_SHEET_ID).worksheet("Wins")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter by username
        student_wins = [record for record in records if record.get("username") == username]
        
        return student_wins
        
    except Exception as e:
        logger.exception("Failed to get student wins: %s", e)
        return []


def get_student_questions(username: str) -> List[Dict[str, Any]]:
    """Get student questions from Google Sheets"""
    try:
        if not QUESTIONS_SHEET_ID:
            return []
        
        client = _get_sheets_client()
        sheet = client.open_by_key(QUESTIONS_SHEET_ID).worksheet("Questions")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter by username
        student_questions = [record for record in records if record.get("username") == username]
        
        return student_questions
        
    except Exception as e:
        logger.exception("Failed to get student questions: %s", e)
        return []


def list_achievers() -> List[Dict[str, Any]]:
    """List students with 3+ assignments and 3+ wins"""
    try:
        if not ASSIGNMENTS_SHEET_ID or not WINS_SHEET_ID:
            return []
        
        client = _get_sheets_client()
        
        # Get assignments
        assignments_sheet = client.open_by_key(ASSIGNMENTS_SHEET_ID).worksheet("Assignments")
        assignments = assignments_sheet.get_all_records()
        
        # Get wins
        wins_sheet = client.open_by_key(WINS_SHEET_ID).worksheet("Wins")
        wins = wins_sheet.get_all_records()
        
        # Count submissions and wins per student
        student_stats = {}
        
        for assignment in assignments:
            username = assignment.get("username")
            if username:
                if username not in student_stats:
                    student_stats[username] = {"assignments": 0, "wins": 0}
                student_stats[username]["assignments"] += 1
        
        for win in wins:
            username = win.get("username")
            if username:
                if username not in student_stats:
                    student_stats[username] = {"assignments": 0, "wins": 0}
                student_stats[username]["wins"] += 1
        
        # Filter achievers (3+ assignments and 3+ wins)
        achievers = [
            {"username": username, "assignments": stats["assignments"], "wins": stats["wins"]}
            for username, stats in student_stats.items()
            if stats["assignments"] >= 3 and stats["wins"] >= 3
        ]
        
        return achievers
        
    except Exception as e:
        logger.exception("Failed to list achievers: %s", e)
        return []


def append_tip(tip_data: Dict[str, Any]) -> bool:
    """Append tip to Google Sheets"""
    try:
        if not QUESTIONS_SHEET_ID:
            logger.warning("QUESTIONS_SHEET_ID not set")
            return False
        
        client = _get_sheets_client()
        sheet = client.open_by_key(QUESTIONS_SHEET_ID).worksheet("Tips")
        
        row = [
            tip_data.get("content", ""),
            tip_data.get("type", "manual"),
            tip_data.get("added_by", ""),
            tip_data.get("added_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        sheet.append_row(row)
        logger.info("Added tip to sheets: %s", tip_data.get('type'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append tip to sheets: %s", e)
        return False


def get_manual_tips() -> List[Dict[str, Any]]:
    """Get manual tips from Google Sheets"""
    try:
        if not QUESTIONS_SHEET_ID:
            return []
        
        client = _get_sheets_client()
        sheet = client.open_by_key(QUESTIONS_SHEET_ID).worksheet("Tips")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter manual tips
        manual_tips = [record for record in records if record.get("type") == "manual"]
        
        return manual_tips
        
    except Exception as e:
        logger.exception("Failed to get manual tips: %s", e)
        return []
