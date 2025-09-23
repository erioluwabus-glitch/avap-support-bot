"""
Async SQLite database utilities using aiosqlite.
Provides a shared connection with WAL enabled and simple helpers
for executing queries in async handlers.
"""
import os
import logging
import aiosqlite
from typing import Any, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/bot.db")

DB_POOL: Optional[aiosqlite.Connection] = None


async def init_async_db() -> None:
    """Initialize a shared aiosqlite connection with WAL enabled."""
    global DB_POOL
    if DB_POOL is not None:
        return
    # Ensure directory exists
    try:
        db_dir = os.path.dirname(DB_PATH) or "."
        os.makedirs(db_dir, exist_ok=True)
    except Exception:
        pass

    DB_POOL = await aiosqlite.connect(DB_PATH)
    # Performance pragmas
    await DB_POOL.execute("PRAGMA journal_mode=WAL;")
    await DB_POOL.execute("PRAGMA synchronous=NORMAL;")
    await DB_POOL.execute("PRAGMA cache_size=-64000;")  # ~64MB cache
    await DB_POOL.commit()
    # Row factory for dict-like access if needed
    DB_POOL.row_factory = aiosqlite.Row
    logger.info("SQLite (aiosqlite) initialized with WAL for async concurrency")


async def close_async_db() -> None:
    global DB_POOL
    if DB_POOL is not None:
        try:
            await DB_POOL.close()
        finally:
            DB_POOL = None


async def db_execute(query: str, params: Iterable[Any] = ()) -> None:
    """Execute a write statement (INSERT/UPDATE/DELETE)."""
    if DB_POOL is None:
        await init_async_db()
    assert DB_POOL is not None
    await DB_POOL.execute(query, tuple(params))
    await DB_POOL.commit()


async def db_fetchone(query: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
    """Execute a SELECT and return a single row."""
    if DB_POOL is None:
        await init_async_db()
    assert DB_POOL is not None
    async with DB_POOL.execute(query, tuple(params)) as cursor:
        return await cursor.fetchone()


async def db_fetchall(query: str, params: Iterable[Any] = ()) -> List[aiosqlite.Row]:
    """Execute a SELECT and return all rows."""
    if DB_POOL is None:
        await init_async_db()
    assert DB_POOL is not None
    async with DB_POOL.execute(query, tuple(params)) as cursor:
        return await cursor.fetchall()


