"""
Async PostgreSQL database utilities using SQLAlchemy (async) with asyncpg.
Maintains helper functions compatible with prior call sites by converting
SQLite-style '?' placeholders to named parameters.
"""
import os
import logging
from typing import Any, Iterable, List, Optional, Tuple, Dict

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL is not set")
    # Avoid raising at import; some tools import this module without envs. Callers should ensure env.

ASYNC_DATABASE_URL = None
if DATABASE_URL:
    # Normalize DSN to asyncpg driver
    if DATABASE_URL.startswith("postgres://"):
        ASYNC_DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        ASYNC_DATABASE_URL = DATABASE_URL

async_engine = create_async_engine(ASYNC_DATABASE_URL) if ASYNC_DATABASE_URL else None
AsyncSessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False) if async_engine else None


async def init_async_db() -> None:
    """Placeholder for symmetry; engine/sessionmaker are module-level."""
    if not async_engine:
        raise RuntimeError("Async engine not initialized. Ensure DATABASE_URL is set.")


async def close_async_db() -> None:
    if async_engine:
        await async_engine.dispose()


async def ensure_schema() -> None:
    """Create required tables if they do not exist (idempotent)."""
    await init_async_db()
    # verified_users
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS verified_users (
            id SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            telegram_id BIGINT UNIQUE,
            status TEXT,
            systeme_contact_id TEXT,
            language TEXT DEFAULT 'en',
            created_at TIMESTAMP DEFAULT NOW(),
            removed_at TIMESTAMP NULL
        )
        """
    )
    # pending_verifications
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS pending_verifications (
            id SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            telegram_id BIGINT,
            status TEXT,
            hash TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # Prevent duplicate pending entries for same email
    await db_execute(
        """
        DO $$ BEGIN
            CREATE UNIQUE INDEX IF NOT EXISTS pending_unique_email_pending
            ON pending_verifications (email)
            WHERE status = 'Pending';
        EXCEPTION WHEN others THEN
            -- ignore
        END $$;
        """
    )
    # submissions
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            submission_id TEXT UNIQUE,
            username TEXT,
            telegram_id BIGINT,
            module INTEGER,
            status TEXT,
            media_type TEXT,
            media_file_id TEXT,
            score INTEGER,
            grader_id BIGINT,
            comment TEXT,
            comment_type TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            graded_at TIMESTAMP NULL
        )
        """
    )
    # wins
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS wins (
            id SERIAL PRIMARY KEY,
            win_id TEXT UNIQUE,
            username TEXT,
            telegram_id BIGINT,
            content_type TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # questions
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            question_id TEXT UNIQUE,
            username TEXT,
            telegram_id BIGINT,
            question TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            answer TEXT,
            answered_by BIGINT,
            answered_at TIMESTAMP NULL
        )
        """
    )
    # student_badges
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS student_badges (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            badge_type TEXT,
            earned_at TIMESTAMP DEFAULT NOW(),
            notified BOOLEAN DEFAULT FALSE,
            systeme_tagged BOOLEAN DEFAULT FALSE
        )
        """
    )
    # Ensure uniqueness per student per badge to avoid duplicates
    await db_execute(
        """
        DO $$ BEGIN
            CREATE UNIQUE INDEX IF NOT EXISTS idx_student_badges_unique
            ON student_badges (telegram_id, badge_type);
        EXCEPTION WHEN others THEN
            -- ignore
        END $$;
        """
    )
    # removals
    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS removals (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            admin_id BIGINT,
            reason TEXT,
            removed_at TIMESTAMP DEFAULT NOW()
        )
        """
    )

def _convert_sqlite_qmarks(query: str, params: Iterable[Any]) -> Tuple[str, Dict[str, Any]]:
    """Convert '?' placeholders to named parameters :p0, :p1, ... for SQLAlchemy text()."""
    if not isinstance(params, (list, tuple)):
        # Assume mapping already
        return query, params  # type: ignore
    parts = query.split("?")
    if len(parts) - 1 != len(params):
        # Fallback: return original; execution may fail loudly for easier debugging
        return query, {f"p{i}": v for i, v in enumerate(params)}
    new_query = []
    for i, segment in enumerate(parts):
        new_query.append(segment)
        if i < len(params):
            new_query.append(f":p{i}")
    named = {f"p{i}": v for i, v in enumerate(params)}
    return "".join(new_query), named


async def db_execute(query: str, params: Iterable[Any] = ()) -> None:
    """Execute a write statement (INSERT/UPDATE/DELETE)."""
    await init_async_db()
    assert AsyncSessionLocal is not None
    sql, bind = _convert_sqlite_qmarks(query, params)
    async with AsyncSessionLocal() as session:
        await session.execute(sa_text(sql), bind)
        await session.commit()


async def db_fetchone(query: str, params: Iterable[Any] = ()) -> Optional[Tuple[Any, ...]]:
    """Execute a SELECT and return a single row as a tuple (or None)."""
    await init_async_db()
    assert AsyncSessionLocal is not None
    sql, bind = _convert_sqlite_qmarks(query, params)
    async with AsyncSessionLocal() as session:
        result = await session.execute(sa_text(sql), bind)
        row = result.fetchone()
        return tuple(row) if row else None


async def db_fetchall(query: str, params: Iterable[Any] = ()) -> List[Tuple[Any, ...]]:
    """Execute a SELECT and return all rows as list of tuples."""
    await init_async_db()
    assert AsyncSessionLocal is not None
    sql, bind = _convert_sqlite_qmarks(query, params)
    async with AsyncSessionLocal() as session:
        result = await session.execute(sa_text(sql), bind)
        rows = result.fetchall()
        return [tuple(r) for r in rows]


