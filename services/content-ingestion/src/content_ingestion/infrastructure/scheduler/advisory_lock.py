"""PostgreSQL advisory lock for single-leader scheduling.

Uses ``pg_try_advisory_lock`` (non-blocking) so that only one replica
runs the adapter for a given source at any time.  The lock is released
when the async context manager exits.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _lock_id(name: str) -> int:
    """Deterministic 32-bit lock id from a string name."""
    return hash(name) & 0x7FFF_FFFF


@asynccontextmanager
async def pg_advisory_lock(session: AsyncSession, name: str) -> AsyncIterator[bool]:
    """Try to acquire a PostgreSQL advisory lock (non-blocking).

    Yields ``True`` if the lock was acquired, ``False`` otherwise.
    The lock is automatically released on exit.

    Args:
        session: An active async database session.
        name: Human-readable lock name (hashed to an int key).
    """
    lock_id = _lock_id(name)
    result = await session.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
    acquired = bool(result.scalar())

    if acquired:
        logger.debug("advisory_lock_acquired", lock_name=name, lock_id=lock_id)
    else:
        logger.debug("advisory_lock_skipped", lock_name=name, lock_id=lock_id)

    try:
        yield acquired
    finally:
        if acquired:
            await session.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
            logger.debug("advisory_lock_released", lock_name=name, lock_id=lock_id)
