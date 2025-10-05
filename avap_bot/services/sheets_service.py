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
            logger.info("Using provided Google credentials from environment variable")
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
            # Try to load credentials from file, but handle gracefully if not found
            try:
                creds = Credentials.from_service_account_file("credentials.json")
            except FileNotFoundError:
                logger.info("Using CSV fallback mode for production deployment (no local credentials.json found)")
                logger.info("CSV fallback active - all data stored locally")
                # Set a flag to indicate we're in fallback mode
                os.environ['_SHEETS_FALLBACK_MODE'] = 'true'
                return None  # Return None to indicate no client available
        
        _sheets_client = gspread.authorize(creds)
    
    return _sheets_client


def _get_spreadsheet():
    """Get the main spreadsheet"""
    global _spreadsheet
    if _spreadsheet is None:
        client = _get_sheets_client()

        # If client is None, we're in fallback mode
        if client is None:
            logger.info("CSV fallback mode active - storing data locally")
            return None

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


def _csv_fallback(filename: str, data: List[List[str]], headers: List[str] = None):
    """Fallback to CSV when Sheets is not available"""
    # IMPORTANT: /tmp/ is ephemeral on many hosting platforms like Render.
    # For persistent backups, set the STABLE_BACKUP_DIR environment variable.
    if not os.getenv("STABLE_BACKUP_DIR"):
        logger.warning("Using ephemeral /tmp/ directory for CSV fallback. Set STABLE_BACKUP_DIR for persistent storage.")

    filepath = os.path.join(CSV_DIR, filename)
    try:
        file_exists = os.path.exists(filepath)

        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Write headers if file doesn't exist and headers provided
            if not file_exists and headers:
                writer.writerow(headers)

            writer.writerow(data)
        logger.info("CSV fallback: wrote to %s", filepath)
        return True
    except Exception as e:
        logger.exception("CSV fallback failed: %s", e)
        return False


def _read_csv_fallback(filename: str) -> List[Dict[str, Any]]:
    """Read data from CSV file (fallback mode)"""
    filepath = os.path.join(CSV_DIR, filename)
    try:
        if not os.path.exists(filepath):
            return []

        with open(filepath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        logger.exception("CSV read fallback failed for %s: %s", filename, e)
        return []


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
        logger.warning("Failed to append pending verification to sheets (using CSV fallback): %s", e)
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
            payload.get("text_content", ""),
            payload.get("submitted_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            "",  # Grade column
            ""   # Comments column
        ]
        
        sheet.append_row(row)
        logger.info("Added submission to sheets: %s - Module %s", payload.get('username'), payload.get('module'))
        return True
        
    except Exception as e:
        logger.warning("Failed to append submission to sheets (using CSV fallback): %s", e)
        # CSV fallback
        return _csv_fallback("submissions.csv", [
            payload.get("submission_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("module", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("text_content", ""),
            payload.get("submitted_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            "",
            ""
        ], ["submission_id", "username", "telegram_id", "module", "type", "file_id", "file_name", "text_content", "submitted_at", "status", "graded_at", "grade"])


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
            payload.get("text_content", ""),
            payload.get("shared_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        sheet.append_row(row)
        logger.info("Added win to sheets: %s - %s", payload.get('username'), payload.get('type'))
        return True
        
    except Exception as e:
        logger.warning("Failed to append win to sheets (using CSV fallback): %s", e)
        # CSV fallback
        return _csv_fallback("wins.csv", [
            payload.get("win_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("type", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("text_content", ""),
            payload.get("shared_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
        ], ["win_id", "username", "telegram_id", "type", "file_id", "file_name", "text_content", "shared_at"])


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
        logger.warning("Failed to append question to sheets (using CSV fallback): %s", e)
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
        ], ["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])


def get_student_submissions(username: str, module: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get student submissions from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("submissions")
                # Get all data
                records = sheet.get_all_records()
                # Filter by username and optionally module
                student_submissions = [record for record in records if record.get("username") == username]
                if module:
                    student_submissions = [s for s in student_submissions if s.get("module") == module]
                return student_submissions
            except Exception as e:
                logger.warning("Failed to get submissions from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        return _get_student_submissions_csv(username, module)

    except Exception as e:
        logger.exception("Failed to get student submissions: %s", e)
        # Try CSV as last resort
        try:
            return _get_student_submissions_csv(username, module)
        except:
            return []


def _get_student_submissions_csv(username: str, module: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get student submissions from CSV file (fallback mode)"""
    try:
        records = _read_csv_fallback("submissions.csv")

        # Filter by username and optionally module
        student_submissions = [record for record in records if record.get("username") == username]
        if module:
            student_submissions = [s for s in student_submissions if s.get("module") == module]

        return student_submissions

    except Exception as e:
        logger.exception("Failed to get student submissions from CSV: %s", e)
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
        logger.warning("Failed to append tip to sheets (using CSV fallback): %s", e)
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


def update_submission_grade(username_or_id: str, module_or_grade: Any, grade: Optional[int] = None, comment: str = "") -> bool:
    """Update submission grade and comment in Google Sheets
    
    Can be called as:
    - update_submission_grade(username, module, grade, comment) - legacy
    - update_submission_grade(submission_id, grade, comment) - new way
    """
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Detect which calling pattern is being used
        if grade is not None:
            # Legacy pattern: update_submission_grade(username, module, grade, comment)
            username = username_or_id
            module = str(module_or_grade)
            actual_grade = grade
            
            # Find row by username and module
            all_records = sheet.get_all_records()
            for i, record in enumerate(all_records, start=2):  # start at 2 for header
                if record.get("username") == username and str(record.get("module")) == module:
                    sheet.update_cell(i, 9, "Graded")  # Status column
                    sheet.update_cell(i, 10, actual_grade)  # Grade column
                    if comment:
                        sheet.update_cell(i, 11, comment)  # Comments column
                    logger.info(f"Updated submission grade for {username} module {module}: {actual_grade}")
                    return True
            
            logger.warning(f"Submission not found for {username} module {module}")
            return False
        else:
            # New pattern: update_submission_grade(submission_id, grade, comment)
            submission_id = username_or_id
            actual_grade = module_or_grade
            
            # Find row by submission_id
            try:
                cell = sheet.find(submission_id)
                sheet.update_cell(cell.row, 9, "Graded")  # Status column
                sheet.update_cell(cell.row, 10, actual_grade)  # Grade column
                if comment:
                    sheet.update_cell(cell.row, 11, comment)  # Comments column
                logger.info("Updated submission grade: %s -> %s (comment: %s)", submission_id, actual_grade, comment)
                return True
            except Exception as e:
                logger.warning("Submission not found: %s", submission_id)
                return False
        
    except Exception as e:
        logger.exception("Failed to update submission grade: %s", e)
        return False


def add_grade_comment(username_or_id: str, module_or_comment: Any, comment: Optional[str] = None) -> bool:
    """Add grade comment to submission in Google Sheets
    
    Can be called as:
    - add_grade_comment(username, module, comment) - legacy
    - add_grade_comment(submission_id, comment) - new way
    """
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("submissions")
        
        # Detect which calling pattern is being used
        if comment is not None:
            # Legacy pattern: add_grade_comment(username, module, comment)
            username = username_or_id
            module = str(module_or_comment)
            actual_comment = comment
            
            # Find row by username and module
            all_records = sheet.get_all_records()
            for i, record in enumerate(all_records, start=2):  # start at 2 for header
                if record.get("username") == username and str(record.get("module")) == module:
                    sheet.update_cell(i, 11, actual_comment)  # Comments column
                    logger.info(f"Added grade comment for {username} module {module}: {actual_comment}")
                    return True
            
            logger.warning(f"Submission not found for {username} module {module}")
            return False
        else:
            # New pattern: add_grade_comment(submission_id, comment)
            submission_id = username_or_id
            actual_comment = module_or_comment
            
            # Find row by submission_id
            try:
                cell = sheet.find(submission_id)
                sheet.update_cell(cell.row, 11, actual_comment)  # Comments column
                logger.info("Added grade comment: %s -> %s", submission_id, actual_comment)
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
    """Get student wins from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("wins")
                # Get all data
                records = sheet.get_all_records()
                # Filter by username
                student_wins = [record for record in records if record.get("username") == username]
                return student_wins
            except Exception as e:
                logger.warning("Failed to get wins from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        return _get_student_wins_csv(username)

    except Exception as e:
        logger.exception("Failed to get student wins: %s", e)
        # Try CSV as last resort
        try:
            return _get_student_wins_csv(username)
        except:
            return []


def _get_student_wins_csv(username: str) -> List[Dict[str, Any]]:
    """Get student wins from CSV file (fallback mode)"""
    try:
        records = _read_csv_fallback("wins.csv")

        # Filter by username
        student_wins = [record for record in records if record.get("username") == username]

        return student_wins

    except Exception as e:
        logger.exception("Failed to get student wins from CSV: %s", e)
        return []


def get_student_questions(username: str) -> List[Dict[str, Any]]:
    """Get student questions from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("questions")
                # Get all data
                records = sheet.get_all_records()
                # Filter by username
                student_questions = [record for record in records if record.get("username") == username]
                return student_questions
            except Exception as e:
                logger.warning("Failed to get questions from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        return _get_student_questions_csv(username)

    except Exception as e:
        logger.exception("Failed to get student questions: %s", e)
        # Try CSV as last resort
        try:
            return _get_student_questions_csv(username)
        except:
            return []


def _get_student_questions_csv(username: str) -> List[Dict[str, Any]]:
    """Get student questions from CSV file (fallback mode)"""
    try:
        records = _read_csv_fallback("questions.csv")

        # Filter by username
        student_questions = [record for record in records if record.get("username") == username]

        return student_questions

    except Exception as e:
        logger.exception("Failed to get student questions from CSV: %s", e)
        return []


def update_question_status(username: str, answer: str) -> bool:
    """Update question status and add answer in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()
        sheet = spreadsheet.worksheet("questions")
        
        # Find row by username (get the most recent question)
        all_records = sheet.get_all_records()
        for i, record in enumerate(reversed(all_records), start=1):
            if record.get("username") == username and record.get("status") == "Pending":
                # Update the row (i is from bottom, so actual row is len - i + 2 for header)
                actual_row = len(all_records) - i + 2
                sheet.update_cell(actual_row, 8, "Answered")  # Status column
                sheet.update_cell(actual_row, 9, answer)  # Answer column
                logger.info(f"Updated question status for {username} to Answered")
                return True
        
        logger.warning(f"No pending question found for {username}")
        return False
        
    except Exception as e:
        logger.exception("Failed to update question status: %s", e)
        return False
