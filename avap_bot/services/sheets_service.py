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
CSV_DIR = os.getenv("STABLE_BACKUP_DIR", "./data/csv_backup")

# Create directory if it doesn't exist
def _ensure_csv_directory():
    """Ensure CSV directory exists and is writable"""
    global CSV_DIR
    try:
        os.makedirs(CSV_DIR, exist_ok=True)
        logger.info(f"CSV backup directory created/verified: {CSV_DIR}")

        # Test write permissions
        test_file = os.path.join(CSV_DIR, ".test_write")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        logger.info(f"CSV directory write test successful: {CSV_DIR}")

    except Exception as e:
        logger.warning(f"Failed to create CSV directory {CSV_DIR}: {e}")
        # Fallback to current directory
        CSV_DIR = "./csv_backup"
        try:
            os.makedirs(CSV_DIR, exist_ok=True)
            logger.info(f"Using fallback CSV directory: {CSV_DIR}")
        except Exception as e2:
            logger.error(f"Failed to create fallback CSV directory {CSV_DIR}: {e2}")
            CSV_DIR = "./"

# Initialize CSV directory on module load
_ensure_csv_directory()


def _get_sheets_client():
    """Get Google Sheets client (lazy initialization)"""
    global _sheets_client
    if not GSPREAD_AVAILABLE:
        logger.error("gspread library not available. Install with: pip install gspread google-auth")
        raise RuntimeError("gspread not available")

    if _sheets_client is None:
        logger.info("Initializing Google Sheets client (lazy loading)...")
        # Check if we have any credentials available
        has_credentials = GOOGLE_CREDENTIALS_JSON or os.path.exists("credentials.json")

        if not has_credentials:
            logger.error("No Google Sheets credentials found")
            logger.error("Please configure Google Sheets credentials:")
            logger.error("1. Set GOOGLE_CREDENTIALS_JSON environment variable with base64-encoded service account JSON")
            logger.error("2. Or create credentials.json file with service account credentials")
            logger.error("3. Or set GOOGLE_SHEET_ID or GOOGLE_SHEET_URL")
            logger.error("CSV fallback active - all data stored locally")
            # Set a flag to indicate we're in fallback mode
            os.environ['_SHEETS_FALLBACK_MODE'] = 'true'
            return None  # Return None to indicate no client available

        if GOOGLE_CREDENTIALS_JSON:
            logger.info("Using provided Google credentials from environment variable")
            try:
                # Try base64 decode first
                try:
                    creds_json = base64.b64decode(GOOGLE_CREDENTIALS_JSON).decode('utf-8')
                    logger.debug("Successfully decoded base64 credentials")
                except Exception as b64_error:
                    logger.debug(f"Base64 decode failed: {b64_error}, trying as raw JSON")
                    # If not base64, use as raw JSON
                    creds_json = GOOGLE_CREDENTIALS_JSON

                # Validate JSON structure before parsing
                try:
                    creds_dict = json.loads(creds_json)
                    logger.debug("JSON parsed successfully")

                    # Check if required fields exist
                    if not creds_dict.get('type') == 'service_account':
                        logger.error("Credentials JSON does not appear to be a service account")
                        logger.error("Expected 'type': 'service_account'")
                        raise ValueError("Invalid credentials type")

                    if not creds_dict.get('project_id'):
                        logger.error("Service account credentials missing project_id")
                        raise ValueError("Missing project_id in credentials")

                    if not creds_dict.get('private_key'):
                        logger.error("Service account credentials missing private_key")
                        raise ValueError("Missing private_key in credentials")

                except json.JSONDecodeError as json_error:
                    logger.error(f"Invalid JSON in GOOGLE_CREDENTIALS_JSON: {json_error}")
                    logger.error("Please ensure GOOGLE_CREDENTIALS_JSON contains valid JSON")
                    raise

                # Create credentials with proper scopes for Google Sheets
                scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
                logger.debug(f"Creating credentials with scopes: {scopes}")

                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                logger.info("Google credentials loaded successfully")

            except Exception as e:
                logger.error(f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}")
                logger.error("Make sure GOOGLE_CREDENTIALS_JSON contains valid service account JSON")
                logger.error("Required format: base64-encoded JSON with type='service_account', project_id, and private_key")
                logger.error("CSV fallback active - all data stored locally")
                os.environ['_SHEETS_FALLBACK_MODE'] = 'true'
                return None  # Return None to indicate no client available
        else:
            # Try to load credentials from file
            try:
                creds = Credentials.from_service_account_file("credentials.json")
                logger.info("Loaded credentials from credentials.json file")
            except FileNotFoundError:
                logger.error("credentials.json file not found")
                logger.error("CSV fallback active - all data stored locally")
                os.environ['_SHEETS_FALLBACK_MODE'] = 'true'
                return None  # Return None to indicate no client available

        try:
            _sheets_client = gspread.authorize(creds)
            logger.info("Google Sheets client initialized successfully")

            # Test the connection by trying to access the spreadsheet
            if GOOGLE_SHEET_ID:
                try:
                    test_spreadsheet = _sheets_client.open_by_key(GOOGLE_SHEET_ID)
                    logger.info(f"Successfully connected to spreadsheet: {test_spreadsheet.title}")
                except Exception as test_error:
                    logger.warning(f"Could not access spreadsheet {GOOGLE_SHEET_ID}: {test_error}")
                    logger.warning("This may be due to insufficient permissions or incorrect spreadsheet ID")

        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            logger.error("Common causes:")
            logger.error("1. Service account doesn't have proper permissions for the spreadsheet")
            logger.error("2. Spreadsheet ID is incorrect")
            logger.error("3. Service account key has expired or been revoked")
            logger.error("4. Google Sheets API is not enabled in the project")
            logger.error("CSV fallback active - all data stored locally")
            os.environ['_SHEETS_FALLBACK_MODE'] = 'true'
            return None  # Return None to indicate no client available

    return _sheets_client


def _get_spreadsheet():
    """Get the main spreadsheet (lazy initialization)"""
    global _spreadsheet
    if _spreadsheet is None:
        logger.info("Initializing Google Sheets connection (lazy loading)...")
        client = _get_sheets_client()

        # If client is None, we're in fallback mode
        if client is None:
            logger.info("CSV fallback mode active - storing data locally")
            logger.warning("Google Sheets not configured. All data will be stored in CSV files only.")
            return None

        if not GOOGLE_SHEET_ID and not GOOGLE_SHEET_URL:
            logger.error("Neither GOOGLE_SHEET_ID nor GOOGLE_SHEET_URL is set")
            logger.error("Please configure at least one of these environment variables")
            logger.info("Falling back to CSV mode")
            return None

        try:
            if GOOGLE_SHEET_ID:
                logger.info("Opening spreadsheet by ID: %s", GOOGLE_SHEET_ID[:10] + "...")
                _spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
            elif GOOGLE_SHEET_URL:
                logger.info("Opening spreadsheet by URL")
                _spreadsheet = client.open_by_url(GOOGLE_SHEET_URL)

            logger.info("Google Sheets connected successfully")

            # Ensure all required worksheets exist
            _ensure_worksheets()
            
            # Force ensure questions worksheet exists
            ensure_Questions_worksheet()
        except Exception as e:
            logger.error("Failed to connect to Google Sheets: %s", e)
            logger.info("Falling back to CSV mode")
            return None

    return _spreadsheet


def _ensure_worksheets():
    """Ensure all required worksheets exist"""
    spreadsheet = _get_spreadsheet()

    # If spreadsheet is None, we're in CSV fallback mode - skip worksheet creation
    if spreadsheet is None:
        logger.info("CSV fallback mode - skipping worksheet creation")
        return

    required_sheets = [
        "verification", "submissions", "submissions_updates",
        "wins", "questions", "tips_manual"
    ]

    try:
        existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
        logger.info(f"Existing worksheets: {existing_sheets}")

        for sheet_name in required_sheets:
            if sheet_name not in existing_sheets:
                try:
                    spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
                    logger.info("Created worksheet: %s", sheet_name)
                    
                    # Add headers for questions worksheet
                    if sheet_name == "questions":
                        sheet = spreadsheet.worksheet("Questions")
                        sheet.append_row(["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])
                        logger.info("Added headers to questions worksheet")
                        
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.info("Worksheet %s already exists, skipping creation", sheet_name)
                    else:
                        logger.warning("Failed to create worksheet %s: %s", sheet_name, e)
            else:
                logger.debug("Worksheet %s already exists, skipping creation", sheet_name)
    except Exception as e:
        logger.error("Failed to list existing worksheets: %s", e)
        logger.info("Continuing with existing worksheets")


def ensure_Questions_worksheet():
    """Ensure the questions worksheet exists with proper headers"""
    try:
        spreadsheet = _get_spreadsheet()
        if spreadsheet is None:
            logger.warning("Cannot create questions worksheet in CSV fallback mode")
            return False
            
        try:
            sheet = spreadsheet.worksheet("Questions")
            logger.info("Questions worksheet already exists")
            return True
        except Exception as e:
            if "WorksheetNotFound" in str(e):
                logger.info("Creating Questions worksheet...")
                spreadsheet.add_worksheet(title="Questions", rows=1000, cols=20)
                sheet = spreadsheet.worksheet("Questions")
                sheet.append_row(["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])
                logger.info("Created Questions worksheet with headers")
                return True
            else:
                raise e
    except Exception as e:
        logger.error(f"Failed to ensure questions worksheet: {e}")
        return False


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

        # If spreadsheet is None, use CSV fallback
        if spreadsheet is None:
            logger.info("Using CSV fallback for pending verification")
            return _csv_fallback("verification_pending.csv", [
                record.get("name", ""),
                record.get("email", ""),
                record.get("phone", ""),
                record.get("status", "Pending"),
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            ], ["name", "email", "phone", "status", "created_at"])

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
        ], ["name", "email", "phone", "status", "created_at"])


def append_submission(payload: Dict[str, Any]) -> bool:
    """Append assignment submission to Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()

        # If spreadsheet is None, use CSV fallback
        if spreadsheet is None:
            logger.info("Using CSV fallback for submission")
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

        try:
            sheet = spreadsheet.worksheet("submissions")
            
            # Check if sheet has headers, if not add them
            try:
                headers = sheet.row_values(1)
                if not headers or headers[0] == "":
                    # Add headers if sheet is empty
                    sheet.update('A1:L1', [['submission_id', 'username', 'telegram_id', 'module', 'type', 'file_id', 'file_name', 'text_content', 'submitted_at', 'status', 'grade', 'comments']])
                    logger.info("Added headers to submissions worksheet")
            except Exception as header_error:
                logger.warning(f"Could not check/update headers for submissions worksheet: {header_error}")

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
            
        except Exception as sheet_error:
            logger.warning(f"Failed to access submissions worksheet: {sheet_error}")
            # Try to create a new submissions worksheet with proper headers
            try:
                new_sheet = spreadsheet.add_worksheet(title="submissions_new", rows=1000, cols=15)
                new_sheet.update('A1:L1', [['submission_id', 'username', 'telegram_id', 'module', 'type', 'file_id', 'file_name', 'text_content', 'submitted_at', 'status', 'grade', 'comments']])
                
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
                
                new_sheet.append_row(row)
                logger.info("Added submission to new submissions worksheet: %s - Module %s", payload.get('username'), payload.get('module'))
                return True
            except Exception as create_error:
                logger.error(f"Failed to create new submissions worksheet: {create_error}")
                raise sheet_error

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

        # If spreadsheet is None, use CSV fallback
        if spreadsheet is None:
            logger.info("Using CSV fallback for win")
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

        try:
            # Try wins_new worksheet first (preferred)
            try:
                sheet = spreadsheet.worksheet("wins_new")
                logger.info("Using wins_new worksheet")
            except:
                # Fallback to wins worksheet
                try:
                    sheet = spreadsheet.worksheet("wins")
                    logger.info("Using wins worksheet")
                except:
                    # Create wins_new worksheet if neither exists
                    sheet = spreadsheet.add_worksheet(title="wins_new", rows=1000, cols=10)
                    sheet.update('A1:H1', [['win_id', 'username', 'telegram_id', 'type', 'file_id', 'file_name', 'text_content', 'shared_at']])
                    logger.info("Created new wins_new worksheet")
            
            # Check if sheet has headers, if not add them
            try:
                headers = sheet.row_values(1)
                if not headers or headers[0] == "":
                    # Add headers if sheet is empty
                    sheet.update('A1:H1', [['win_id', 'username', 'telegram_id', 'type', 'file_id', 'file_name', 'text_content', 'shared_at']])
                    logger.info("Added headers to wins worksheet")
            except Exception as header_error:
                logger.warning(f"Could not check/update headers for wins worksheet: {header_error}")

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
            logger.info("Added win to new wins worksheet: %s - %s", payload.get('username'), payload.get('type'))
            return True
            
        except Exception as sheet_error:
            logger.error(f"Failed to access any wins worksheet: {sheet_error}")
            raise sheet_error

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

        # If spreadsheet is None, use CSV fallback
        if spreadsheet is None:
            logger.info("Using CSV fallback for question")
            return _csv_fallback("questions.csv", [
                payload.get("question_id", ""),
                payload.get("username", ""),
                payload.get("telegram_id", ""),
                payload.get("question_text", ""),
                payload.get("file_id", ""),
                payload.get("file_name", ""),
                payload.get("asked_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
                payload.get("status", "Pending"),
                payload.get("answer", "")
            ], ["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])

        # Ensure the questions worksheet exists
        try:
            sheet = spreadsheet.worksheet("Questions")
        except Exception as e:
            if "WorksheetNotFound" in str(e):
                logger.warning("Questions worksheet not found, creating it...")
                try:
                    spreadsheet.add_worksheet(title="Questions", rows=1000, cols=20)
                    # Add headers
                    sheet = spreadsheet.worksheet("Questions")
                    sheet.append_row(["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])
                    logger.info("Created questions worksheet with headers")
                except Exception as create_error:
                    logger.error(f"Failed to create questions worksheet: {create_error}")
                    return False
            else:
                raise e

        row = [
            payload.get("question_id", ""),
            payload.get("username", ""),
            payload.get("telegram_id", ""),
            payload.get("question_text", ""),
            payload.get("file_id", ""),
            payload.get("file_name", ""),
            payload.get("asked_at", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S"),
            payload.get("status", "Pending"),
            payload.get("answer", "")  # Answer column
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


def get_student_submissions(username: str, module: Optional[str] = None, telegram_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get student submissions from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("submissions")
                # Get all data
                records = sheet.get_all_records()

                # Filter by username and/or telegram_id and optionally module
                student_submissions = []
                for record in records:
                    # Check if record matches either username or telegram_id
                    username_match = username and record.get("username") == username
                    telegram_id_match = telegram_id and record.get("telegram_id") == telegram_id

                    if username_match or telegram_id_match:
                        student_submissions.append(record)

                if module:
                    student_submissions = [s for s in student_submissions if s.get("module") == module]
                return student_submissions
            except Exception as e:
                logger.warning("Failed to get submissions from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        logger.info("Using CSV fallback for submissions")
        return _get_student_submissions_csv(username, module, telegram_id)

    except Exception as e:
        logger.exception("Failed to get student submissions: %s", e)
        # Try CSV as last resort
        try:
            return _get_student_submissions_csv(username, module)
        except:
            return []


def _get_student_submissions_csv(username: str, module: Optional[str] = None, telegram_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get student submissions from CSV file (fallback mode)"""
    try:
        records = _read_csv_fallback("submissions.csv")

        # Filter by username and/or telegram_id and optionally module
        student_submissions = []
        for record in records:
            # Check if record matches either username or telegram_id
            username_match = username and record.get("username") == username
            telegram_id_match = telegram_id and record.get("telegram_id") == telegram_id

            if username_match or telegram_id_match:
                student_submissions.append(record)

        if module:
            student_submissions = [s for s in student_submissions if s.get("module") == module]

        # Convert string values to appropriate types if needed
        for submission in student_submissions:
            # Convert telegram_id to int if it's a string
            if 'telegram_id' in submission and submission['telegram_id']:
                try:
                    submission['telegram_id'] = int(submission['telegram_id'])
                except (ValueError, TypeError):
                    pass

        return student_submissions

    except Exception as e:
        logger.exception("Failed to get student submissions from CSV: %s", e)
        return []


def get_all_submissions() -> List[Dict[str, Any]]:
    """Get all student submissions from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("submissions")
                # Get all data
                records = sheet.get_all_records()
                return records
            except Exception as e:
                logger.warning("Failed to get all submissions from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        logger.info("Using CSV fallback for all submissions")
        return _read_csv_fallback("submissions.csv")

    except Exception as e:
        logger.exception("Failed to get all submissions: %s", e)
        return []


def list_achievers() -> List[Dict[str, Any]]:
    """List students with 3+ assignments and 3+ wins"""
    try:
        spreadsheet = _get_spreadsheet()

        # Handle CSV fallback mode
        if spreadsheet is None:
            logger.info("Google Sheets not available, using CSV fallback for list_achievers")
            return _list_achievers_csv()

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
            if stats["assignments"] >= 2 or stats["wins"] >= 2:
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
        logger.error(f"Error details: {str(e)}")
        return []


def _list_achievers_csv() -> List[Dict[str, Any]]:
    """List achievers from CSV files (fallback when Google Sheets not available)"""
    try:
        # Read verified users CSV
        verified_users = _read_csv_fallback("verified_users.csv")

        # Create email to telegram_id mapping
        email_to_telegram_id = {
            user.get("email"): user.get("telegram_id")
            for user in verified_users if user.get("email") and user.get("telegram_id")
        }

        # Read submissions CSV
        submissions = _read_csv_fallback("submissions.csv")

        # Read wins CSV
        wins = _read_csv_fallback("wins.csv")

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
            if stats["assignments"] >= 2 or stats["wins"] >= 2:
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

        logger.info(f"Found {len(achievers)} achievers from CSV files")
        return achievers

    except Exception as e:
        logger.exception("Failed to list achievers from CSV: %s", e)
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

        # Handle CSV fallback mode
        if spreadsheet is None:
            logger.info("Google Sheets not available, using CSV fallback for get_manual_tips")
            return _get_manual_tips_csv()

        sheet = spreadsheet.worksheet("tips_manual")

        # Get all data
        records = sheet.get_all_records()

        # Filter manual tips
        manual_tips = [record for record in records if record.get("type") == "manual"]

        return manual_tips

    except Exception as e:
        logger.exception("Failed to get manual tips: %s", e)
        return []


def _get_manual_tips_csv() -> List[Dict[str, Any]]:
    """Get manual tips from CSV files (fallback when Google Sheets not available)"""
    try:
        # Read tips CSV
        tips = _read_csv_fallback("tips.csv")

        # Filter manual tips
        manual_tips = [tip for tip in tips if tip.get("tip_type") == "manual"]

        logger.info(f"Found {len(manual_tips)} manual tips from CSV files")
        return manual_tips

    except Exception as e:
        logger.exception("Failed to get manual tips from CSV: %s", e)
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
                    sheet.update_cell(i, 10, "Graded")  # Status column (column 10)
                    sheet.update_cell(i, 11, actual_grade)  # Grade column (column 11)
                    if comment:
                        sheet.update_cell(i, 12, comment)  # Comments column (column 12)
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
                sheet.update_cell(cell.row, 10, "Graded")  # Status column (column 10)
                sheet.update_cell(cell.row, 11, actual_grade)  # Grade column (column 11)
                if comment:
                    sheet.update_cell(cell.row, 12, comment)  # Comments column (column 12)
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
                    # Update the comments column (column 12)
                    sheet.update_cell(i, 12, actual_comment)
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
                # Update the comments column (column 12)
                sheet.update_cell(cell.row, 12, actual_comment)
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

        # Handle CSV fallback mode
        if spreadsheet is None:
            logger.info("Google Sheets not available, using CSV fallback for get_all_verified_users")
            return _get_all_verified_users_csv()

        sheet = spreadsheet.worksheet("verification")

        # Get all data
        records = sheet.get_all_records()

        # Filter verified users
        verified_users = [record for record in records if record.get("status", "").lower() == "verified"]

        return verified_users

    except Exception as e:
        logger.exception("Failed to get verified users: %s", e)
        return []


def _get_all_verified_users_csv() -> List[Dict[str, Any]]:
    """Get all verified users from CSV files (fallback when Google Sheets not available)"""
    try:
        verified_users = _read_csv_fallback("verified_users.csv")

        # Filter verified users
        filtered_users = [user for user in verified_users if user.get("status", "").lower() == "verified"]

        logger.info(f"Found {len(filtered_users)} verified users from CSV files")
        return filtered_users

    except Exception as e:
        logger.exception("Failed to get verified users from CSV: %s", e)
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


def get_all_wins() -> List[Dict[str, Any]]:
    """Get all wins from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                # Try wins_new worksheet first (new format)
                try:
                    sheet = spreadsheet.worksheet("wins_new")
                    logger.info("Using wins_new worksheet")
                    records = sheet.get_all_records()
                    return records
                except Exception:
                    # Fallback to wins worksheet
                    sheet = spreadsheet.worksheet("wins")
                    logger.info("Using wins worksheet")
                    records = sheet.get_all_records()
                    return records
            except Exception as e:
                logger.warning("Failed to get wins from Google Sheets, falling back to CSV: %s", e)
                return _get_all_wins_csv()
        else:
            # CSV fallback
            return _get_all_wins_csv()
    except Exception as e:
        logger.exception("Error in get_all_wins: %s", e)
        return []


def _get_all_wins_csv() -> List[Dict[str, Any]]:
    """Get all wins from CSV file (fallback mode)"""
    try:
        csv_file = "data/csv_backup/wins.csv"
        wins = []
        if os.path.exists(csv_file):
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                wins = list(reader)
        return wins
    except Exception as e:
        logger.exception("Error reading wins CSV: %s", e)
        return []


def get_student_wins(username: str) -> List[Dict[str, Any]]:
    """Get student wins from Google Sheets or CSV fallback"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                # Try wins_new worksheet first (new format)
                try:
                    sheet = spreadsheet.worksheet("wins_new")
                    records = sheet.get_all_records()
                    student_wins = [record for record in records if record.get("username") == username]
                    if student_wins:
                        logger.info(f"Found {len(student_wins)} wins in wins_new worksheet for {username}")
                        return student_wins
                except Exception as e:
                    logger.debug(f"wins_new worksheet not found or empty: {e}")
                
                # Fallback to wins worksheet (old format)
                sheet = spreadsheet.worksheet("wins")
                records = sheet.get_all_records()
                student_wins = [record for record in records if record.get("username") == username]
                return student_wins
            except Exception as e:
                logger.warning("Failed to get wins from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        logger.info("Using CSV fallback for wins")
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

        # Convert string values to appropriate types if needed
        for win in student_wins:
            # Convert telegram_id to int if it's a string
            if 'telegram_id' in win and win['telegram_id']:
                try:
                    win['telegram_id'] = int(win['telegram_id'])
                except (ValueError, TypeError):
                    pass

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
                sheet = spreadsheet.worksheet("Questions")
                # Get all data
                records = sheet.get_all_records()
                # Filter by username
                student_questions = [record for record in records if record.get("username") == username]
                return student_questions
            except Exception as e:
                if "WorksheetNotFound" in str(e):
                    logger.warning("Questions worksheet not found, creating it...")
                    try:
                        spreadsheet.add_worksheet(title="Questions", rows=1000, cols=20)
                        # Add headers
                        sheet = spreadsheet.worksheet("Questions")
                        sheet.append_row(["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])
                        logger.info("Created questions worksheet with headers")
                        # Return empty list since we just created the worksheet
                        return []
                    except Exception as create_error:
                        logger.error(f"Failed to create questions worksheet: {create_error}")
                        logger.warning("Failed to get questions from Google Sheets, falling back to CSV: %s", e)
                else:
                    logger.warning("Failed to get questions from Google Sheets, falling back to CSV: %s", e)

        # CSV fallback mode
        logger.info("Using CSV fallback for questions")
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

        # Convert string values to appropriate types if needed
        for question in student_questions:
            # Convert telegram_id to int if it's a string
            if 'telegram_id' in question and question['telegram_id']:
                try:
                    question['telegram_id'] = int(question['telegram_id'])
                except (ValueError, TypeError):
                    pass

        return student_questions

    except Exception as e:
        logger.exception("Failed to get student questions from CSV: %s", e)
        return []


def update_question_status(username: str, answer: str) -> bool:
    """Update question status and add answer in Google Sheets"""
    try:
        spreadsheet = _get_spreadsheet()

        # If spreadsheet is None, we can't update (CSV fallback doesn't support updates)
        if spreadsheet is None:
            logger.warning("Cannot update question status in CSV fallback mode")
            return False

        # Ensure the questions worksheet exists
        try:
            sheet = spreadsheet.worksheet("Questions")
        except Exception as e:
            if "WorksheetNotFound" in str(e):
                logger.warning("Questions worksheet not found, creating it...")
                try:
                    spreadsheet.add_worksheet(title="Questions", rows=1000, cols=20)
                    # Add headers
                    sheet = spreadsheet.worksheet("Questions")
                    sheet.append_row(["question_id", "username", "telegram_id", "question_text", "file_id", "file_name", "asked_at", "status", "answer"])
                    logger.info("Created questions worksheet with headers")
                except Exception as create_error:
                    logger.error(f"Failed to create questions worksheet: {create_error}")
                    return False
            else:
                raise e

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


def get_submission_by_id(submission_id: str) -> Optional[Dict[str, Any]]:
    """Get submission information by submission ID"""
    try:
        spreadsheet = _get_spreadsheet()

        # If Google Sheets is available, use it
        if spreadsheet:
            try:
                sheet = spreadsheet.worksheet("submissions")
                # Get all data
                records = sheet.get_all_records()
                # Find submission by ID
                for record in records:
                    if record.get("submission_id") == submission_id:
                        return {
                            'submission_id': record.get("submission_id", ""),
                            'username': record.get("username", ""),
                            'telegram_id': record.get("telegram_id", ""),
                            'module': record.get("module", ""),
                            'type': record.get("type", ""),
                            'file_id': record.get("file_id", ""),
                            'file_name': record.get("file_name", ""),
                            'text_content': record.get("text_content", ""),
                            'submitted_at': record.get("submitted_at", ""),
                            'status': record.get("status", ""),
                        }
                logger.warning(f"Submission not found in Google Sheets: {submission_id}")
                return None
            except Exception as e:
                logger.warning(f"Failed to get submission from Google Sheets, falling back to CSV: {e}")

        # CSV fallback mode
        logger.info("Using CSV fallback for submission lookup")
        return _get_submission_by_id_csv(submission_id)

    except Exception as e:
        logger.exception("Failed to get submission by ID: %s", e)
        # Try CSV as last resort
        try:
            return _get_submission_by_id_csv(submission_id)
        except:
            return None


def _get_submission_by_id_csv(submission_id: str) -> Optional[Dict[str, Any]]:
    """Get submission from CSV file (fallback mode)"""
    try:
        records = _read_csv_fallback("submissions.csv")

        # Find submission by ID
        for record in records:
            if record.get("submission_id") == submission_id:
                return record

        logger.warning(f"Submission not found in CSV: {submission_id}")
        return None

    except Exception as e:
        logger.exception("Failed to get submission from CSV: %s", e)
        return None


def test_sheets_connection() -> bool:
    """Test Google Sheets connection and return status"""
    try:
        logger.info("Testing Google Sheets connection...")
        spreadsheet = _get_spreadsheet()

        if spreadsheet is None:
            logger.warning("Google Sheets not configured - using CSV fallback mode")
            return False

        # Try to access a worksheet to verify connection
        try:
            sheet = spreadsheet.worksheet("verification")
            # Try a simple operation
            records = sheet.get_all_records()
            logger.info(f"Google Sheets test successful - found {len(records)} verification records")
            return True
        except Exception as e:
            logger.error(f"Google Sheets test failed: {e}")
            return False

    except Exception as e:
        logger.exception("Google Sheets connection test failed: %s", e)
        return False
