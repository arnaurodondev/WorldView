"""PostgreSQL advisory locks for single-leader scheduling.

Three flavors are provided, each with a DIFFERENT safety envelope — picking
the wrong one for a given caller is exactly how BP-752 (see
``docs/BUG_PATTERNS.md``) happened, so read this before reaching for one:

``pg_advisory_lock`` (SESSION-scoped, ``pg_try_advisory_lock``/``pg_advisory_unlock``)
    Safe ONLY when:
      1. The *session* passed in is a DIRECT (non-PgBouncer-transaction-pooled)
         connection, AND
      2. ``session.commit()`` is NEVER called on that same session before this
         context manager exits.
    Session-level advisory locks are pinned to whichever PHYSICAL backend
    connection the session happens to be using at acquire time. SQLAlchemy's
    async connection pool releases a session's underlying connection back to
    the pool on every ``commit()`` — the NEXT statement on that session (e.g.
    this helper's own unlock call) may therefore be served by a DIFFERENT
    physical connection, which:
      - never held the lock, so ``pg_advisory_unlock`` raises/warns
        (``WARNING: you don't own a lock of type ExclusiveLock``), and
      - leaks the ORIGINAL lock on the connection that DID acquire it, until
        that connection is reset/recycled by the pool.
    Under PgBouncer ``pool_mode=transaction`` this is WORSE and SILENT:
    ``server_reset_query=DISCARD ALL`` releases the lock the instant the
    acquiring transaction ends (no warning at all), voiding the mutual
    exclusion guarantee entirely. **Never use this flavor against a
    PgBouncer transaction-pooled engine — use ``pg_advisory_xact_lock``
    instead.**

``pg_advisory_xact_lock`` (TRANSACTION-scoped, ``pg_try_advisory_xact_lock``)
    Auto-released at the natural end of the CURRENT transaction (commit OR
    rollback) — no explicit unlock statement, so there is no "wrong
    connection" window at all. This is the only flavor that is safe through
    PgBouncer ``pool_mode=transaction``: PgBouncer always keeps a backend
    bound to a client for exactly the duration of one transaction, which is
    precisely what this lock's lifetime tracks. Use this when the guarded
    critical section is (or can be restructured into) a SINGLE transaction on
    a SINGLE dedicated session — e.g. hold the lock on a session that itself
    is never committed until the very end of the run, while separate
    sessions/UnitOfWorks perform the actual (possibly multi-commit) writes.
    ``knowledge_graph.infrastructure.intelligence_db.repositories.relation``
    uses the blocking sibling (``pg_advisory_xact_lock``, no "try") as the
    reference pattern for this scoping.

``pg_advisory_lock_pinned`` (SESSION-scoped, DEDICATED ``AsyncConnection``)
    For callers whose critical section commits one or more OTHER
    sessions/UnitsOfWork WHILE the lock must stay held (so ``pg_advisory_lock``
    is unsafe) but which do NOT route through PgBouncer transaction pooling
    (so ``pg_advisory_xact_lock`` doesn't apply either, or a single-transaction
    restructure isn't practical). Opens its own ``AsyncConnection`` directly
    from the engine — never handing it back to the pool until the lock is
    released — so it is immune to the "wrong connection" problem regardless
    of how many commits happen elsewhere. **Do not use against a PgBouncer
    transaction-pooled engine**: PgBouncer detaches the physical backend the
    instant THIS connection's own acquire-statement transaction ends, no
    matter how long the client holds onto the connection object.

IMPORTANT: All three use ``hashlib.sha256`` for deterministic lock IDs — never
Python's built-in ``hash()`` which is randomized per process (PYTHONHASHSEED).
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]


def advisory_lock_id(name: str) -> int:
    """Deterministic 32-bit positive lock id from a string name.

    Uses SHA-256 to ensure the same name produces the same lock ID
    across all Python processes, replicas, and restarts.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF


@asynccontextmanager
async def pg_advisory_lock(session: AsyncSession, name: str) -> AsyncIterator[bool]:
    """Try to acquire a SESSION-scoped PostgreSQL advisory lock (non-blocking).

    Yields ``True`` if the lock was acquired, ``False`` otherwise.
    The lock is automatically released on exit via an explicit unlock
    statement executed on ``session``.

    See the module docstring's "``pg_advisory_lock``" section for the exact
    safety envelope — in particular, ``session.commit()`` must NEVER be
    called before this context manager exits, and ``session`` must not be a
    PgBouncer transaction-pooled connection. If either condition doesn't
    hold, use ``pg_advisory_xact_lock`` or ``pg_advisory_lock_pinned``.

    Args:
        session: An active async database session. Must not be committed
            while this context manager is active.
        name: Human-readable lock name (hashed to a deterministic int key).
    """
    lock_id = advisory_lock_id(name)
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


@asynccontextmanager
async def pg_advisory_xact_lock(session: AsyncSession, name: str) -> AsyncIterator[bool]:
    """Try to acquire a TRANSACTION-scoped PostgreSQL advisory lock (non-blocking).

    Yields ``True`` if the lock was acquired, ``False`` otherwise. Unlike
    ``pg_advisory_lock``, there is NO explicit unlock statement: the lock is
    released automatically by Postgres when the CURRENT transaction on
    ``session`` ends (commit OR rollback) — including one triggered by
    ``session.close()`` on context-manager exit if nothing was explicitly
    committed. This makes it safe through PgBouncer ``pool_mode=transaction``,
    where the physical backend is only ever detached at a transaction
    boundary — exactly when this lock releases anyway.

    Callers whose critical section spans multiple LOGICAL writes MUST perform
    those writes through OTHER sessions/UnitsOfWork (each free to commit as
    many times as needed) while this ``session`` itself is left uncommitted
    for the lock's entire intended lifetime — committing ``session`` early
    releases the lock early.

    Args:
        session: An active async database session. Must not be committed
            until the lock should be released.
        name: Human-readable lock name (hashed to a deterministic int key).
    """
    lock_id = advisory_lock_id(name)
    result = await session.execute(text(f"SELECT pg_try_advisory_xact_lock({lock_id})"))
    acquired = bool(result.scalar())

    if acquired:
        logger.debug("advisory_xact_lock_acquired", lock_name=name, lock_id=lock_id)
    else:
        logger.debug("advisory_xact_lock_skipped", lock_name=name, lock_id=lock_id)

    try:
        yield acquired
    finally:
        # No explicit release: pg_try_advisory_xact_lock is auto-released by
        # Postgres at commit/rollback of the current transaction. Issuing an
        # unlock statement here would be a no-op at best (xact locks have no
        # ``pg_advisory_xact_unlock`` function) and is intentionally omitted.
        if acquired:
            logger.debug("advisory_xact_lock_will_release_at_txn_end", lock_name=name, lock_id=lock_id)


@asynccontextmanager
async def pg_advisory_lock_pinned(engine: AsyncEngine, name: str) -> AsyncIterator[bool]:
    """Try to acquire a SESSION-scoped advisory lock on a DEDICATED connection.

    Yields ``True`` if the lock was acquired, ``False`` otherwise. Opens its
    own ``AsyncConnection`` directly from *engine* — separate from any ORM
    ``Session`` the caller's business logic uses — and does not return that
    connection to the pool until the lock is released, so a commit on some
    OTHER session/connection can never cause the unlock statement to land on
    the wrong physical backend (the failure mode ``pg_advisory_lock`` is
    exposed to when a caller's critical section spans multiple commits).

    NOT safe against a PgBouncer transaction-pooled engine: PgBouncer detaches
    the physical backend the instant the acquire statement's OWN transaction
    ends, regardless of how long the client process holds onto the connection
    object. Use ``pg_advisory_xact_lock`` for pgbouncer transaction-pooled
    engines instead.

    Args:
        engine: The ``AsyncEngine`` to open a dedicated connection from. Must
            NOT be a PgBouncer ``pool_mode=transaction`` engine.
        name: Human-readable lock name (hashed to a deterministic int key).
    """
    lock_id = advisory_lock_id(name)
    conn = await engine.connect()
    acquired = False
    try:
        result = await conn.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
        acquired = bool(result.scalar())
        # Commit the trivial acquire-statement's own (autobegin) transaction so
        # this connection isn't left idle-in-transaction for the duration of
        # the critical section. This is safe because pg_try_advisory_lock is
        # SESSION-scoped, not transaction-scoped: it persists across
        # commits/rollbacks on this same connection until explicitly unlocked
        # or the connection closes.
        await conn.commit()

        if acquired:
            logger.debug("advisory_lock_pinned_acquired", lock_name=name, lock_id=lock_id)
        else:
            logger.debug("advisory_lock_pinned_skipped", lock_name=name, lock_id=lock_id)

        yield acquired
    finally:
        if acquired:
            await conn.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
            await conn.commit()
            logger.debug("advisory_lock_pinned_released", lock_name=name, lock_id=lock_id)
        await conn.close()
