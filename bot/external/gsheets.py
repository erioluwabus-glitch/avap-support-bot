"""
Handles all interactions with Google Sheets.
"""

import json
import gspread
from google.oauth2.service_account import Credentials

from ..config import (
    GSPREAD_AVAILABLE,
    GOOGLE_CREDENTIALS_JSON,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    logger,
)

gs_client = None
gs_sheet = None

def init_gsheets():
    """Initializes the Google Sheets client and opens the target spreadsheet."""
    global gs_client, gs_sheet
    if not GSPREAD_AVAILABLE:
        logger.info("gspread library not installed, Google Sheets integration is disabled.")
        return
    if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEETS_SPREADSHEET_ID:
        logger.info("Google Sheets credentials or Spreadsheet ID not configured; skipping.")
        return

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gs_client = gspread.authorize(creds)
        gs_sheet = gs_client.open_by_key(GOOGLE_SHEETS_SPREADSHEET_ID)
        logger.info("Google Sheets integration initialized successfully.")
    except Exception as e:
        logger.exception("Failed to initialize Google Sheets: %s", e)
        gs_client = None
        gs_sheet = None

def get_verifications_worksheet() -> gspread.Worksheet | None:
    """Gets the 'Verifications' worksheet, creating it if it doesn't exist."""
    if not gs_sheet:
        return None
    try:
        return gs_sheet.worksheet("Verifications")
    except gspread.WorksheetNotFound:
        try:
            logger.info("Creating 'Verifications' worksheet.")
            sheet = gs_sheet.add_worksheet("Verifications", rows=100, cols=10)
            sheet.append_row(["Name", "Email", "Phone", "Telegram ID", "Status", "Hash", "Created At"])
            return sheet
        except Exception as e:
            logger.exception("Failed to create 'Verifications' worksheet: %s", e)
    return None


def append_pending_student(name: str, email: str, phone: str, h: str, created_at: str):
    """Appends a new pending student record to the 'Verifications' sheet."""
    if not gs_sheet:
        return
    try:
        sheet = get_verifications_worksheet()
        if sheet:
            sheet.append_row([name, email, phone, 0, "Pending", h, created_at])
    except Exception:
        logger.exception("Failed to append pending student to Google Sheets (non-fatal).")


def update_verification_status(email: str, new_status: str, telegram_id: int | None = None):
    """Updates the status of a student in the 'Verifications' sheet, identified by email."""
    if not gs_sheet:
        return
    try:
        sheet = get_verifications_worksheet()
        if not sheet:
            return

        # Find all cells matching the email
        cells = sheet.findall(email)
        for cell in cells:
            row_idx = cell.row
            # Update status in column 5
            sheet.update_cell(row_idx, 5, new_status)
            # Update Telegram ID if provided
            if telegram_id is not None:
                sheet.update_cell(row_idx, 4, telegram_id)
    except Exception:
        logger.exception(f"Failed to update verification status for {email} in Google Sheets.")
