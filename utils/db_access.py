"""
Database access utilities for AVAP bot features.
Provides CRUD operations for all feature modules.
"""
import sqlite3
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

# Database path from environment
DB_PATH = os.getenv("DB_PATH", "./bot.db")

# Global database connection and lock
db_conn = None
db_lock = None

def init_database():
    """Initialize database connection and create tables."""
    global db_conn, db_lock
    
    if db_conn is None:
        db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        db_lock = asyncio.Lock()
        
        # Create tables if they don't exist
        create_tables()
    
    return db_conn, db_lock

def create_tables():
    """Create all required tables for the new features."""
    cur = db_conn.cursor()
    
    # Update verified_users table to include language
    try:
        cur.execute("ALTER TABLE verified_users ADD COLUMN language TEXT DEFAULT 'en'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Create asked_questions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS asked_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id TEXT UNIQUE,
            telegram_id INTEGER,
            username TEXT,
            question TEXT,
            answered INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create daily_tips table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip TEXT NOT NULL
        )
    """)
    
    # Create match_queue table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    db_conn.commit()

# Database access functions for features

async def get_verified_users() -> List[Dict[str, Any]]:
    """Get all verified users."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("SELECT telegram_id, name, email, language FROM verified_users WHERE removed_at IS NULL")
        rows = cur.fetchall()
        return [{"telegram_id": row[0], "name": row[1], "email": row[2], "language": row[3]} for row in rows]

async def get_user_language(telegram_id: int) -> str:
    """Get user's language preference."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("SELECT language FROM verified_users WHERE telegram_id = ?", (telegram_id,))
        row = cur.fetchone()
        return row[0] if row else 'en'

async def set_user_language(telegram_id: int, language: str) -> bool:
    """Set user's language preference."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("UPDATE verified_users SET language = ? WHERE telegram_id = ?", (language, telegram_id))
        conn.commit()
        return cur.rowcount > 0

async def add_question(question_id: str, telegram_id: int, username: str, question: str) -> bool:
    """Add a new question to the database."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO asked_questions (question_id, telegram_id, username, question)
                VALUES (?, ?, ?, ?)
            """, (question_id, telegram_id, username, question))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

async def mark_question_answered(question_id: str) -> bool:
    """Mark a question as answered."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("UPDATE asked_questions SET answered = 1 WHERE question_id = ?", (question_id,))
        conn.commit()
        return cur.rowcount > 0

async def get_unanswered_questions(timeout_hours: int) -> List[Dict[str, Any]]:
    """Get questions that haven't been answered within the timeout period."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=timeout_hours)
        cur.execute("""
            SELECT question_id, telegram_id, username, question, created_at
            FROM asked_questions
            WHERE answered = 0 AND created_at < ?
        """, (cutoff_time.isoformat(),))
        rows = cur.fetchall()
        return [{"question_id": row[0], "telegram_id": row[1], "username": row[2], 
                "question": row[3], "created_at": row[4]} for row in rows]

async def add_daily_tip(tip: str) -> bool:
    """Add a daily tip to the database."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO daily_tips (tip) VALUES (?)", (tip,))
            conn.commit()
            return True
        except Exception as e:
            logger.exception(f"Failed to add daily tip: {e}")
            return False

async def get_random_daily_tip() -> Optional[str]:
    """Get a random daily tip from the database."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("SELECT tip FROM daily_tips ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None

async def add_to_match_queue(telegram_id: int, username: str) -> bool:
    """Add user to match queue."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        try:
            cur.execute("INSERT OR REPLACE INTO match_queue (telegram_id, username) VALUES (?, ?)", 
                       (telegram_id, username))
            conn.commit()
            return True
        except Exception as e:
            logger.exception(f"Failed to add to match queue: {e}")
            return False

async def get_match_queue() -> List[Dict[str, Any]]:
    """Get all users in match queue."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        cur.execute("SELECT telegram_id, username, created_at FROM match_queue ORDER BY created_at")
        rows = cur.fetchall()
        return [{"telegram_id": row[0], "username": row[1], "created_at": row[2]} for row in rows]

async def remove_from_match_queue(telegram_ids: List[int]) -> bool:
    """Remove users from match queue after matching."""
    conn, lock = init_database()
    async with lock:
        cur = conn.cursor()
        try:
            placeholders = ','.join('?' * len(telegram_ids))
            cur.execute(f"DELETE FROM match_queue WHERE telegram_id IN ({placeholders})", telegram_ids)
            conn.commit()
            return True
        except Exception as e:
            logger.exception(f"Failed to remove from match queue: {e}")
            return False

async def send_with_backoff(bot, chat_id: int, text: str, max_retries: int = 3) -> bool:
    """Send message with exponential backoff to handle rate limits."""
    for attempt in range(max_retries):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}")
                await asyncio.sleep(wait_time)
            else:
                logger.exception(f"Failed to send message to {chat_id}: {e}")
                return False
    return False
