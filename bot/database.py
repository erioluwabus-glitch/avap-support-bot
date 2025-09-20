"""
Handles all database operations for the bot.
"""

import sqlite3
import asyncio
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from .config import DB_PATH, logger

# A lock to prevent concurrent writes to the SQLite database from different async tasks
db_lock = asyncio.Lock()

def get_db_connection() -> sqlite3.Connection:
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    # Table for students who are pre-registered but haven't verified with the bot yet
    cur.execute(
        """CREATE TABLE IF NOT EXISTS pending_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            telegram_id INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Pending',
            hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    # Table for students who have successfully verified with the bot
    cur.execute(
        """CREATE TABLE IF NOT EXISTS verified_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            telegram_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'Verified',
            verified_at TEXT NOT NULL
        )"""
    )
    # Table for assignment submissions
    cur.execute(
        """CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id TEXT NOT NULL UNIQUE,
            username TEXT,
            telegram_id INTEGER NOT NULL,
            module INTEGER NOT NULL,
            status TEXT DEFAULT 'Submitted',
            media_type TEXT,
            file_id TEXT,
            score INTEGER,
            comment TEXT,
            timestamp TEXT NOT NULL
        )"""
    )
    # Table for small wins shared by students
    cur.execute(
        """CREATE TABLE IF NOT EXISTS wins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            win_id TEXT NOT NULL UNIQUE,
            username TEXT,
            telegram_id INTEGER NOT NULL,
            content_type TEXT,
            content TEXT,
            timestamp TEXT NOT NULL
        )"""
    )
    # Table for questions asked by students
    cur.execute(
        """CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT NOT NULL UNIQUE,
            username TEXT,
            telegram_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            timestamp TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

# --- Utility ---
def make_hash(name: str, email: str, phone: str) -> str:
    """Creates a SHA256 hash from user details to uniquely identify them."""
    base = f"{name.lower().strip()}{email.lower().strip()}{phone.strip()}"
    return hashlib.sha256(base.encode()).hexdigest()

# --- Verification Flow ---

async def add_pending_student(name: str, email: str, phone: str) -> bool:
    """Adds a student to the pending verification list. Returns False if email already exists."""
    h = make_hash(name, email, phone)
    created_at = datetime.utcnow().isoformat()
    async with db_lock:
        try:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO pending_verifications (name, email, phone, hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name, email, phone, h, created_at),
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Attempted to add a pending student with an existing email: {email}")
            return False

async def find_pending_by_hash(h: str) -> Optional[sqlite3.Row]:
    """Finds a pending student by their verification hash."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM pending_verifications WHERE hash = ? AND status = 'Pending'", (h,)).fetchone()

async def get_pending_by_email(email: str) -> Optional[sqlite3.Row]:
    """Finds a pending student by their email."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM pending_verifications WHERE email = ? AND status = 'Pending'", (email,)).fetchone()

async def verify_user(pending_id: int, telegram_id: int, name: str, email: str, phone: str):
    """Moves a user from pending to verified."""
    verified_at = datetime.utcnow().isoformat()
    async with db_lock:
        with get_db_connection() as conn:
            # Add to verified_users table
            conn.execute(
                "INSERT OR REPLACE INTO verified_users (name, email, phone, telegram_id, status, verified_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, email, phone, telegram_id, "Verified", verified_at)
            )
            # Update pending_verifications table
            conn.execute(
                "UPDATE pending_verifications SET telegram_id = ?, status = ? WHERE id = ?",
                (telegram_id, "Verified", pending_id)
            )
            conn.commit()

async def manual_verify_user(email: str):
    """Manually verifies a user without a telegram_id, marking them as ready."""
    verified_at = datetime.utcnow().isoformat()
    async with db_lock:
        with get_db_connection() as conn:
            pending_user = conn.execute("SELECT name, phone FROM pending_verifications WHERE email = ?", (email,)).fetchone()
            if not pending_user:
                return

            # Add to verified_users, but with a placeholder telegram_id (0)
            conn.execute(
                "INSERT OR REPLACE INTO verified_users (name, email, phone, telegram_id, status, verified_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pending_user['name'], email, pending_user['phone'], 0, "Verified (Manual)", verified_at)
            )
            # Update pending status
            conn.execute("UPDATE pending_verifications SET status = ? WHERE email = ?", ("Verified (Manual)", email))
            conn.commit()

async def get_verified_user_by_telegram_id(telegram_id: int) -> Optional[sqlite3.Row]:
    """Retrieves a verified user's details by their Telegram ID."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM verified_users WHERE telegram_id = ?", (telegram_id,)).fetchone()

async def remove_verified_user(telegram_id: int) -> Optional[Tuple[str, str]]:
    """Removes a user from the verified list and updates their pending status."""
    async with db_lock:
        with get_db_connection() as conn:
            user = conn.execute("SELECT email, name FROM verified_users WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not user:
                return None

            conn.execute("DELETE FROM verified_users WHERE telegram_id = ?", (telegram_id,))
            conn.execute("UPDATE pending_verifications SET status = ?, telegram_id = ? WHERE email = ?", ("Removed", 0, user['email']))
            conn.commit()
            return user['email'], user['name']

# --- Submissions, Wins, Questions ---

async def create_submission(submission_id: str, username: str, telegram_id: int, module: int, media_type: str, file_id: str):
    """Creates a new submission record."""
    timestamp = datetime.utcnow().isoformat()
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO submissions (submission_id, username, telegram_id, module, media_type, file_id, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (submission_id, username, telegram_id, module, media_type, file_id, timestamp)
            )
            conn.commit()

async def update_submission_score(submission_id: str, score: int):
    """Updates the score for a submission."""
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute("UPDATE submissions SET score = ?, status = ? WHERE submission_id = ?", (score, "Graded", submission_id))
            conn.commit()

async def update_submission_comment(submission_id: str, comment: str):
    """Adds a comment to a submission."""
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute("UPDATE submissions SET comment = ? WHERE submission_id = ?", (comment, submission_id))
            conn.commit()

async def get_submission(submission_id: str) -> Optional[sqlite3.Row]:
    """Retrieves a submission by its ID."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)).fetchone()

async def create_win(win_id: str, username: str, telegram_id: int, content_type: str, content: str):
    """Creates a new 'small win' record."""
    timestamp = datetime.utcnow().isoformat()
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO wins (win_id, username, telegram_id, content_type, content, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (win_id, username, telegram_id, content_type, content, timestamp)
            )
            conn.commit()

async def create_question(question_id: str, username: str, telegram_id: int, question_text: str):
    """Creates a new question record."""
    timestamp = datetime.utcnow().isoformat()
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO questions (question_id, username, telegram_id, question, timestamp) VALUES (?, ?, ?, ?, ?)",
                (question_id, username, telegram_id, question_text, timestamp)
            )
            conn.commit()

async def get_question(question_id: str) -> Optional[sqlite3.Row]:
    """Retrieves a question by its ID."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM questions WHERE question_id = ?", (question_id,)).fetchone()

async def update_question_answer(question_id: str, answer: str):
    """Adds an answer to a question."""
    async with db_lock:
        with get_db_connection() as conn:
            conn.execute("UPDATE questions SET answer = ? WHERE question_id = ?", (answer, question_id))
            conn.commit()

async def get_student_stats(telegram_id: int) -> Tuple[List[sqlite3.Row], int]:
    """Gets all submissions and the total win count for a student."""
    async with db_lock:
        with get_db_connection() as conn:
            submissions = conn.execute("SELECT module, status, score, comment FROM submissions WHERE telegram_id = ?", (telegram_id,)).fetchall()
            wins_count = conn.execute("SELECT COUNT(*) FROM wins WHERE telegram_id = ?", (telegram_id,)).fetchone()[0]
            return submissions, wins_count

async def get_all_verified_users() -> List[sqlite3.Row]:
    """Gets all verified users for sending reminders."""
    async with db_lock:
        with get_db_connection() as conn:
            return conn.execute("SELECT telegram_id, name FROM verified_users WHERE status LIKE 'Verified%' AND telegram_id != 0").fetchall()
