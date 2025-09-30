"""
Google Sheets service for data storage - Single spreadsheet with CSV fallback
"""
import os
import json
import csv
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import base64

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

logger = logging.getLogger(__name__)

# Single spreadsheet configuration
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

_sheets_client = None
_spreadsheet = None

# CSV fallback directory
# IMPORTANT: /tmp/ is ephemeral on many hosting platforms like Render.
# For persistent backups, set the STABLE_BACKUP_DIR environment variable.
CSV_DIR = os.getenv("STABLE_BACKUP_DIR", "/tmp/avap_sheets")
os.makedirs(CSV_DIR, exist_ok=True)


def _get_sheets_client():
    """Get Google Sheets client"""
    global _sheets_client
    if not GSPREAD_AVAILABLE:
        raise RuntimeError("gspread not available")
    
    if _sheets_client is None:
        if GOOGLE_CREDENTIALS_JSON:
            try:
                # Try base64 decode first
                try:
                    creds_json = base64.b64decode(GOOGLE_CREDENTIALS_JSON).decode('utf-8')
                except:
                    # If not base64, use as raw JSON
                    creds_json = GOOGLE_CREDENTIALS_JSON
                
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict)
            except Exception as e:
                logger.warning("Failed to parse GOOGLE_CREDENTIALS_JSON: %s", e)
                raise RuntimeError("Invalid Google credentials")
        else:
            creds = Credentials.from_service_account_file("credentials.json")
        
        _sheets_client = gspread.authorize(creds)
    
    return _sheets_client


def _get_spreadsheet():
    """Get the main spreadsheet"""
    global _spreadsheet
    if _spreadsheet is None:
        client = _get_sheets_client()
        
        if GOOGLE_SHEET_ID:
            _spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        elif GOOGLE_SHEET_URL:
            _spreadsheet = client.open_by_url(GOOGLE_SHEET_URL)
        else:
            raise RuntimeError("GOOGLE_SHEET_ID or GOOGLE_SHEET_URL must be set")
        
        # Ensure all required worksheets exist
        _ensure_worksheets()
    
    return _spreadsheet


def _ensure_worksheets():
    """Ensure all required worksheets exist"""
    spreadsheet = _get_spreadsheet()
    required_sheets = [
        "verification", "submissions", "submissions_updates", 
        "wins", "questions", "tips_manual"
    ]
    
    existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
    
    for sheet_name in required_sheets:
        if sheet_name not in existing_sheets:
            try:
                spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
                logger.info("Created worksheet: %s", sheet_name)
            except Exception as e:
                logger.warning("Failed to create worksheet %s: %s", sheet_name, e)


def _csv_fallback(filename: str, data: List[List[str]]):
    """Fallback to CSV when Sheets is not available"""
    # IMPORTANT: /tmp/ is ephemeral on many hosting platforms like Render.
    # For persistent backups, set the STABLE_BACKUP_DIR environment variable.
    if not os.getenv("STABLE_BACKUP_DIR"):
        logger.warning("Using ephemeral /tmp/ directory for CSV fallback. Set STABLE_BACKUP_DIR for persistent storage.")
    
    filepath = os.path.join(CSV_DIR, filename)
    try:
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(data)
        logger.info("CSV fallback: wrote to %s", filepath)
        return True
    except Exception as e:
        logger.exception("CSV fallback failed: %s", e)
        return False


def append_pending_verification(record: Dict[str, Any]) -> bool:
    """Append pending verification to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("verification")
        
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
        # CSV fallback
        return _csv_fallback("verification_pending.csv", [
            record.get("name", ""),
            record.get("email", ""),
            record.get("phone", ""),
            record.get("status", "Pending"),
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ])


def append_submission(payload: Dict[str, Any]) -> bool:
    """Append assignment submission to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        row = [
            payload.get("submission_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("module", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("submitted_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            "",  # Grade column
            ""   # Comments column
        ]
        
        sheet.append_row(row)
        logger.info("Added submission to sheets: %s - Module %s", payload.get('username'), payload.get('module'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append submission to sheets: %s", e)
        # CSV fallback
        return _csv_fallback("submissions.csv", [
            payload.get("submission_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("module", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("submitted_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            "",
            ""
        ])


def update_submission_status(submission_id: str, status: str, score: Optional[int] = None) -> bool:
    """Update submission status and grade in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Find row by submission_id
        try:
            cell = sheet.find(submission_id)
            sheet.update_cell(cell.row, 9, status)  # Status column
            if score is not None:
                sheet.update_cell(cell.row, 10, score)  # Grade column
            logger.info("Updated submission status: %s -> %s (score: %s)", submission_id, status, score)
            return True
        except Exception as e:
            logger.warning("Submission not found: %s", submission_id)
            return False
        
    except Exception as e:
        logger.exception("Failed to update submission status: %s", e)
        return False


def append_win(payload: Dict[str, Any]) -> bool:
    """Append win to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("wins")
        
        row = [
            payload.get("win_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("shared_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        sheet.append_row(row)
        logger.info("Added win to sheets: %s - %s", payload.get('username'), payload.get('type'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append win to sheets: %s", e)
        # CSV fallback
        return _csv_fallback("wins.csv", [
            payload.get("win_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("shared_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ])


def append_question(payload: Dict[str, Any]) -> bool:
    """Append question to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("questions")
        
        row = [
            payload.get("question_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("question_text", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("asked_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            ""  # Answer column
        ]
        
        sheet.append_row(row)
        logger.info("Added question to sheets: %s", payload.get('username'))
        return True
        
    except Exception as e:
        logger.exception("Failed to append question to sheets: %s", e)
        # CSV fallback
        return _csv_fallback("questions.csv", [
            payload.get("question_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("question_text", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("asked_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            ""
        ])


def get_student_submissions(username: str, module: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get student submissions from Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter by username and optionally module
        student_submissions = [record for record in records if record.get("username") == username]
        if module:
            student_submissions = [s for s in student_submissions if s.get("module") == module]
        
        return student_submissions
        
    except Exception as e:
        logger.exception("Failed to get student submissions: %s", e)
        return []


def list_achievers() -> List[Dict[str, Any]]:
    """List students with 3+ assignments and 3+ wins"""
    try:
        spreadsheet = _get_spreadsheet()

        # Get verified users for telegram_id lookup
        verification_sheet = spreadsheet.worksheet("verification")
        verified_users = verification_sheet.get_all_records()
        email_to_telegram_id = {
            user.get("email"): user.get("telegram_id")
            for user in verified_users if user.get("email") and user.get("telegram_id")
        }

        # Get submissions
        submissions_sheet = spreadsheet.worksheet("submissions")
        submissions = submissions_sheet.get_all_records()

        # Get wins
        wins_sheet = spreadsheet.worksheet("wins")
        wins = wins_sheet.get_all_records()

        # Count submissions and wins per student
        student_stats = {}

        for submission in submissions:
            username = submission.get("username")
            if not username:
                continue
            if username not in student_stats:
                student_stats[username] = {
                    "assignments": 0,
                    "wins": 0,
                    "telegram_id": submission.get("telegram_id"),
                    "email": submission.get("email")
                }
            student_stats[username]["assignments"] += 1
            if not student_stats[username].get("telegram_id") and submission.get("telegram_id"):
                student_stats[username]["telegram_id"] = submission.get("telegram_id")
            if not student_stats[username].get("email") and submission.get("email"):
                student_stats[username]["email"] = submission.get("email")

        for win in wins:
            username = win.get("username")
            if not username:
                continue
            if username not in student_stats:
                student_stats[username] = {
                    "assignments": 0,
                    "wins": 0,
                    "telegram_id": win.get("telegram_id"),
                    "email": win.get("email")
                }
            student_stats[username]["wins"] += 1
            if not student_stats[username].get("telegram_id") and win.get("telegram_id"):
                student_stats[username]["telegram_id"] = win.get("telegram_id")
            if not student_stats[username].get("email") and win.get("email"):
                student_stats[username]["email"] = win.get("email")

        # Filter achievers (3+ assignments and 3+ wins)
        achievers = []
        for username, stats in student_stats.items():
            if stats["assignments"] >= 3 and stats["wins"] >= 3:
                telegram_id = stats.get("telegram_id")
                if not telegram_id:
                    # Fallback to email lookup
                    email = stats.get("email")
                    if email in email_to_telegram_id:
                        telegram_id = email_to_telegram_id[email]

                achiever_data = {
                    "username": username,
                    "assignments": stats["assignments"],
                    "wins": stats["wins"],
                    "telegram_id": telegram_id,
                    "email": stats.get("email")
                }
                achievers.append(achiever_data)

        return achievers
        
    except Exception as e:
        logger.exception("Failed to list achievers: %s", e)
        return []


def append_tip(tip_data: Dict[str, Any]) -> bool:
    """Append tip to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("tips_manual")
        
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
        # CSV fallback
        return _csv_fallback("tips_manual.csv", [
            tip_data.get("content", ""),
            tip_data.get("type", "manual"),
            tip_data.get("added_by", ""),
            tip_data.get("added_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ])


def get_manual_tips() -> List[Dict[str, Any]]:
    """Get manual tips from Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("tips_manual")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter manual tips
        manual_tips = [record for record in records if record.get("type") == "manual"]
        
        return manual_tips
        
    except Exception as e:
        logger.exception("Failed to get manual tips: %s", e)
        return []


def update_submission_grade(submission_id: str, grade: int, comment: str = "") -> bool:
    """Update submission grade and comment in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Find row by submission_id
        try:
            cell = sheet.find(submission_id)
            sheet.update_cell(cell.row, 10, grade)  # Grade column
            if comment:
                sheet.update_cell(cell.row, 11, comment)  # Comments column
            logger.info("Updated submission grade: %s -> %s (comment: %s)", submission_id, grade, comment)
            return True
        except Exception as e:
            logger.warning("Submission not found: %s", submission_id)
            return False
        
    except Exception as e:
        logger.exception("Failed to update submission grade: %s", e)
        return False


def add_grade_comment(submission_id: str, comment: str) -> bool:
    """Add grade comment to submission in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Find row by submission_id
        try:
            cell = sheet.find(submission_id)
            sheet.update_cell(cell.row, 11, comment)  # Comments column
            logger.info("Added grade comment: %s -> %s", submission_id, comment)
            return True
        except Exception as e:
            logger.warning("Submission not found: %s", submission_id)
            return False
        
    except Exception as e:
        logger.exception("Failed to add grade comment: %s", e)
        return False


def get_all_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users from Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("verification")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter verified users
        verified_users = [record for record in records if record.get("status", "").lower() == "verified"]
        
        return verified_users
        
    except Exception as e:
        logger.exception("Failed to get verified users: %s", e)
        return []


def update_verification_status(email: str, status: str) -> bool:
    """Update verification status in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("verification")
        
        # Find row by email
        try:
            cell = sheet.find(email)
            sheet.update_cell(cell.row, 4, status)  # Status column
            logger.info("Updated verification status: %s -> %s", email, status)
            return True
        except Exception as e:
            logger.warning("Email not found: %s", email)
            return False
        
    except Exception as e:
        logger.exception("Failed to update verification status: %s", e)
        return False


def get_student_wins(username: str) -> List[Dict[str, Any]]:
    """Get student wins from Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("wins")
        
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
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("questions")
        
        # Get all data
        records = sheet.get_all_records()
        
        # Filter by username
        student_questions = [record for record in records if record.get("username") == username]
        
        return student_questions
        
    except Exception as e:
        logger.exception("Failed to get student questions: %s", e)
        return []
       return student_questions
        
    except Exception as e:
        logger.exception("Failed to get student questions: %s", e)
        return []
