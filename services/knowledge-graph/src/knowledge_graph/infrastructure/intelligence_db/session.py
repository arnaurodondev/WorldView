"""Session factories for intelligence_db (dual-session, ALEMBIC_ENABLED=false guard).

S7 must NEVER run Alembic against intelligence_db.  This module raises an error
if ``ALEMBIC_ENABLED`` is set to a truthy value in the process environment.

Two session factories are provided:
- ``create_intelligence_session_factory`` — read/write sessions for hot-path writes.
- ``create_readonly_session_factory``    — read-only sessions for query/worker reads.

Supports R23 dual-session pattern: when ``database_url_read`` is configured,
the read-only factory uses a separate connection pool pointed at the read replica.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from knowledge_graph.domain.errors import IntelligenceDbAlembicError
from observability import get_logger  # type: ignore[import-untyped]

_log = get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from knowledge_graph.config import Settings

_ALLOWED_FALSE_VALUES = {"false", "0", "no", "off", ""}

# Default per-connection statement_timeout (milliseconds) used by the
# backward-compatible raw-URL factory wrappers, which have no Settings object to
# read from.  The settings-aware ``_build_factories`` path uses
# ``settings.statement_timeout_ms`` instead.  Override via the
# ``KNOWLEDGE_GRAPH_STATEMENT_TIMEOUT_MS`` env var (read directly here so the
# wrappers honour the same knob as the main path).
_DEFAULT_STATEMENT_TIMEOUT_MS = 60_000


def _build_connect_args(statement_timeout_ms: int) -> dict[str, object]:
    """Build asyncpg ``connect_args`` with application_name + statement_timeout.

    The ``statement_timeout`` is set as an asyncpg ``server_settings`` connection
    parameter so every regular (non-AGE) SQL session is bounded the moment the
    connection is established.  AGE Cypher use cases issue ``SET LOCAL
    statement_timeout`` per transaction, which overrides this connection-level
    default for that transaction only (precedence is correct — their explicit
    5/20/30 s bounds are preserved).

    When *statement_timeout_ms* <= 0 the timeout is omitted entirely (unbounded),
    matching the previous behaviour for operators who explicitly disable it.
    asyncpg requires every ``server_settings`` value to be a string, hence the
    ``str(...)`` cast (the bare-integer form is interpreted as milliseconds by
    Postgres, which is exactly what we want).
    """
    server_settings: dict[str, str] = {"application_name": "knowledge-graph"}
    if statement_timeout_ms > 0:
        server_settings["statement_timeout"] = str(statement_timeout_ms)
    return {"server_settings": server_settings}


def _statement_timeout_from_env() -> int:
    """Read the statement_timeout default for the raw-URL wrappers from env.

    Falls back to ``_DEFAULT_STATEMENT_TIMEOUT_MS`` when the env var is unset or
    not a valid integer (fail-safe: a malformed value must not disable the
    backstop).
    """
    raw = os.environ.get("KNOWLEDGE_GRAPH_STATEMENT_TIMEOUT_MS", "").strip()
    if not raw:
        return _DEFAULT_STATEMENT_TIMEOUT_MS
    try:
        return int(raw)
    except ValueError:
        _log.warning(
            "kg_statement_timeout_env_invalid",
            value=raw,
            fallback_ms=_DEFAULT_STATEMENT_TIMEOUT_MS,
        )
        return _DEFAULT_STATEMENT_TIMEOUT_MS


def _same_db_endpoint(url1: str, url2: str) -> bool:
    """True if two DB URLs connect to the same host, port, and database."""
    from urllib.parse import urlparse

    try:
        p1, p2 = urlparse(url1), urlparse(url2)
        return (
            p1.scheme == p2.scheme
            and (p1.hostname or "").lower() == (p2.hostname or "").lower()
            and p1.port == p2.port
            and p1.path.rstrip("/") == p2.path.rstrip("/")
        )
    except Exception:
        return url1 == url2


def _check_alembic_guard() -> None:
    """Raise if ALEMBIC_ENABLED is truthy — intelligence_db DDL is not ours to own."""
    raw = os.environ.get("ALEMBIC_ENABLED", "false").strip().lower()
    if raw not in _ALLOWED_FALSE_VALUES:
        raise IntelligenceDbAlembicError(
            "ALEMBIC_ENABLED=true detected for intelligence_db. "
            "S7 must never run Alembic against intelligence_db — "
            "DDL is exclusively owned by the intelligence-migrations init container.",
        )


def _build_factories(
    settings: Settings,
) -> tuple[AsyncEngine, AsyncEngine, async_sessionmaker[AsyncSession], async_sessionmaker[AsyncSession]]:
    """Build write + read session factories from *settings* (R23 compliant).

    Returns
    -------
        ``(write_engine, read_engine, write_factory, read_factory)`` — caller owns
        both engines for disposal on shutdown.  When no read replica is configured,
        ``read_engine is write_engine``.

    """
    _check_alembic_guard()

    # BP-502: application_name surfaces this service in pg_stat_activity for
    # connection debugging; pool_recycle=300 defends against stale DNS sockets.
    # statement_timeout (from settings) bounds every regular SQL session so no
    # query can run unbounded again (4.5 h promoter incident, 2026-06-21).
    _connect_args: dict[str, object] = _build_connect_args(settings.statement_timeout_ms)
    write_engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=300,
        connect_args=_connect_args,
    )
    write_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=write_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    read_url: str = (
        settings.database_url_read.get_secret_value()
        if settings.database_url_read
        else settings.database_url.get_secret_value()
    )
    if _same_db_endpoint(read_url, settings.database_url.get_secret_value()):
        # QA-fix §2.5: surface the misconfiguration explicitly so an operator
        # who forgot to set DATABASE_URL_READ does not silently route 100% of
        # read traffic through the write pool (defeats Wave B-5 / R23).
        _log.warning(
            "kg_read_replica_not_configured",
            message=(
                "DATABASE_URL_READ is empty or matches DATABASE_URL — read traffic "
                "falls through to the write pool (Wave B-5 / R23 partially active)."
            ),
        )
        read_engine = write_engine
        read_factory = write_factory
    else:
        read_engine = create_async_engine(
            read_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size_read,
            max_overflow=settings.db_max_overflow_read,
            pool_recycle=300,
            connect_args=_connect_args,
            execution_options={"postgresql_readonly": True, "no_parameters": False},
        )
        read_factory = async_sessionmaker(
            bind=read_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        _log.info("kg_read_replica_engine_initialized")

    return write_engine, read_engine, write_factory, read_factory


def create_intelligence_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a read/write async session factory for intelligence_db.

    Backward-compatible wrapper — accepts a raw URL string.  For R23 dual-factory
    support, use ``_build_factories(settings)`` directly.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``

    """
    _check_alembic_guard()
    # pool_size/max_overflow match the right-sized Settings defaults (2 + 4) so this
    # raw-URL wrapper cannot silently re-introduce the oversized 10/20 pool that
    # contributed to the shared-Postgres direct-backend OOM (2026-07-23).
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=4,
        pool_recycle=300,
        connect_args=_build_connect_args(_statement_timeout_from_env()),
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory


def create_readonly_session_factory(
    url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a read-only async session factory for intelligence_db.

    Backward-compatible wrapper — accepts a raw URL string.

    Raises :class:`~knowledge_graph.domain.errors.IntelligenceDbAlembicError`
    if ``ALEMBIC_ENABLED`` is truthy.

    Returns
    -------
    tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
        ``(engine, session_factory)``

    """
    _check_alembic_guard()
    # Right-sized read pool (2 + 4) — matches the write wrapper above. On the
    # single-node topology the read URL points at the same primary, so this pool is
    # inert today, but keeping it small prevents a future read-replica swap from
    # re-introducing an oversized 20/30 pool (2026-07-23 direct-backend OOM fix).
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=4,
        pool_recycle=300,
        connect_args=_build_connect_args(_statement_timeout_from_env()),
        execution_options={"postgresql_readonly": True, "no_parameters": False},
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, factory
