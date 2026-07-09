"""SQLAlchemy async engine and session factory helpers.

Two engines are created:
- **Write engine** (primary): used for all INSERT/UPDATE/DELETE operations.
- **Read engine** (read replica): used for SELECT-only operations.
  Falls back to the write engine if no replica URL is configured.

Pool hardening (BP-720 amplifier fix, 2026-07-09)
-------------------------------------------------
The market-data pool used to erode under load because a slow read that the
caller (rag-chat, 10s timeout) cancelled could orphan its asyncpg connection
(see the pure-ASGI ``RequestIdMiddleware`` rewrite in ``app.py``). Two
defensive changes make the pool *fail fast* instead of silently blocking the
next reader for a full minute:

* ``pool_timeout`` dropped 60s → 10s — a checkout that cannot be satisfied
  raises quickly (surfacing the problem) instead of blocking a request thread.
* ``pool_use_lifo=True`` — reuses the most-recently-returned connection first,
  so a temporary spike drains idle connections faster and a genuinely leaked
  connection is more visible (idle connections at the *tail* age out).
* A server-side ``statement_timeout`` (~8s) caps any single query at the
  Postgres level, so a wedged/slow query cannot pin a connection open longer
  than the caller's own timeout budget.

Pool checkout/overflow gauges are emitted so an eroding pool is observable in
Prometheus rather than only manifesting as user-visible latency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Gauge
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from market_data.config import Settings

# ── Pool configuration constants ───────────────────────────────────────────────
# Fail-fast checkout: a request that cannot get a connection within this window
# raises rather than blocking (previously 60s, which turned a leak into a stall).
_POOL_TIMEOUT_SECONDS = 10
# Cap any single statement server-side so a slow/wedged query cannot pin a
# connection open indefinitely. Expressed in milliseconds for Postgres.
_STATEMENT_TIMEOUT_MS = "8000"


# ── Pool observability ─────────────────────────────────────────────────────────
# Module-level gauges (registered once at import) so repeated engine creation in
# tests does not trigger a duplicate-timeseries registration error. Labelled by
# engine ``role`` (write/read) so both pools are visible independently.
_pool_checked_out = Gauge(
    "market_data_db_pool_checked_out_connections",
    "Number of connections currently checked out of the SQLAlchemy pool.",
    ["role"],
)
_pool_overflow = Gauge(
    "market_data_db_pool_overflow_connections",
    "Current overflow count (connections beyond pool_size) for the pool.",
    ["role"],
)


def _instrument_pool(engine: AsyncEngine, *, role: str) -> None:
    """Attach checkout/checkin listeners that mirror pool status into gauges.

    Runs synchronously inside the pool's own callbacks, so the reported values
    are always consistent with the pool's internal accounting. Used to make a
    slow leak visible before it degrades user-facing latency.
    """
    sync_engine = engine.sync_engine

    def _update(*_args: object) -> None:
        pool = sync_engine.pool
        # ``checkedout``/``overflow`` are cheap integer accessors on QueuePool.
        _pool_checked_out.labels(role=role).set(pool.checkedout())  # type: ignore[attr-defined]
        _pool_overflow.labels(role=role).set(pool.overflow())  # type: ignore[attr-defined]

    event.listen(sync_engine, "checkout", _update)
    event.listen(sync_engine, "checkin", _update)


def _connect_args() -> dict[str, dict[str, str]]:
    """Shared asyncpg connect args: application_name + server-side timeout.

    ``statement_timeout`` is applied as an asyncpg server setting so it is set
    on every physical connection at connect time (no per-query wiring needed).
    """
    return {
        "server_settings": {
            # BP-502: application_name surfaces this service in pg_stat_activity.
            "application_name": "market-data",
            # Fail-fast at the DB layer (BP-720 amplifier fix).
            "statement_timeout": _STATEMENT_TIMEOUT_MS,
        }
    }


def build_write_engine(settings: Settings) -> AsyncEngine:
    """Create the primary (read/write) async SQLAlchemy engine."""
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
        pool_use_lifo=True,
        pool_recycle=300,
        connect_args=_connect_args(),
    )
    _instrument_pool(engine, role="write")
    return engine


def build_read_engine(settings: Settings) -> AsyncEngine:
    """Create a read-replica async engine.

    Falls back to the primary database URL if ``read_replica_url`` is not
    configured on the settings object.
    """
    _replica = getattr(settings, "read_replica_url", None)
    read_url = _replica.get_secret_value() if _replica is not None else settings.database_url.get_secret_value()
    engine = create_async_engine(
        read_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=30,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
        pool_use_lifo=True,
        pool_recycle=300,
        connect_args=_connect_args(),
    )
    _instrument_pool(engine, role="read")
    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Create an ``async_sessionmaker`` bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
