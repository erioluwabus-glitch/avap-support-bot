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


