"""Shared async SQLAlchemy engine factory with PgBouncer + dead-connection hardening.

BP-732 (2026-07-19/22): three independent hardening passes each touched only the
service(s) in front of the incident that motivated them — `bea446831` added
PgBouncer transaction-pooling compatibility (`statement_cache_size=0`,
`prepared_statement_cache_size=0`) to five services by hand; `0d0f27119` added a
client-side `command_timeout` to bound dead-connection hangs, but ONLY to
nlp-pipeline; `f1d04b8e5` independently built a fail-fast pool + server-side
`statement_timeout` for market-data alone. None of the three fixes were extracted
into a shared helper, so every *other* pooled service still hand-rolls its own
``connect_args`` and can silently miss a hardening lesson learned elsewhere.

This module is the single place that assembles the proven-correct
``connect_args`` shape (server-side ``statement_timeout``, client-side
asyncpg ``command_timeout``, and PgBouncer transaction-pool prepared-statement
disabling) so a new hardening lesson is a one-file change instead of an
N-service hand-edit.

Placement rationale: this lives in ``libs/messaging`` (not ``libs/storage``,
which is a pure S3/MinIO abstraction with zero DB-related code or dependencies)
because ``libs/messaging.pg`` already exists as the shared home for
Postgres-adjacent cross-service utilities (see ``messaging.pg.advisory_lock``)
and already carries an optional ``sqlalchemy`` dependency for exactly this kind
of helper. Every consuming service already declares ``sqlalchemy[asyncio]`` and
``asyncpg`` as direct dependencies of its own, so no new transitive dependency
is introduced by importing this module.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Proven defaults — see module docstring for the incidents that established
# each one. Kept as named constants (not inlined) so both the factory default
# and any documentation/tests referencing "the standard timeout" stay in sync.
DEFAULT_COMMAND_TIMEOUT_S = 600.0
"""Client-side asyncpg ``command_timeout`` (seconds), from ``0d0f27119``.

Bounds how long asyncpg waits for ANY command on a given connection, regardless
of server state. Without it, a half-open (dead-but-not-RST) connection after a
Postgres crash/restart hangs the caller FOREVER (observed: a 2.4h article-
pipeline wedge, 2026-07-21). Chosen to sit above every legitimate query ceiling
(the 8s/60s statement_timeout tiers below) and below Kafka's
``max.poll.interval.ms`` (30 min default) so a wedged op raises in time for the
consumer to redeliver instead of getting fenced out of its consumer group.
"""

DEFAULT_STATEMENT_TIMEOUT_MS = 8_000
"""Server-side ``statement_timeout`` (milliseconds), from ``f1d04b8e5``.

Caps any single query at the Postgres level so a wedged/slow statement cannot
pin a connection open indefinitely, regardless of client-side behavior. This is
a GUC applied via ``server_settings`` at connect time; under PgBouncer
transaction pooling it is a non-native startup parameter, so PgBouncer must
list it in ``ignore_startup_parameters`` for it to take effect (if PgBouncer
silently drops it, the operator's fallback is
``ALTER DATABASE <db> SET statement_timeout = '<ms>'``, which survives
``DISCARD ALL`` — see market-data's session module for the full note).
"""


def build_async_engine(
    dsn: str,
    *,
    pooled: bool,
    command_timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    application_name: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 300,
    pool_pre_ping: bool = True,
    pool_timeout: float | None = None,
    connect_timeout_s: float | None = None,
    echo: bool = False,
    extra_connect_args: dict[str, object] | None = None,
) -> AsyncEngine:
    """Build an async SQLAlchemy engine with the proven-correct connect_args.

    This is the ONE place `connect_args` for a Postgres asyncpg engine should be
    assembled — every service's ``infrastructure/db/session.py`` should call
    this instead of hand-building the dict, so a future hardening lesson lands
    here once instead of needing N hand-edits (BP-732).

    Args:
        dsn: Full ``postgresql+asyncpg://...`` connection string (already
            resolved from a ``SecretStr`` by the caller — this factory never
            logs or otherwise handles the raw DSN beyond passing it through).
        pooled: ``True`` if this connection routes through PgBouncer in
            transaction-pooling mode (``pool_mode=transaction``). When
            ``True``, both asyncpg's own statement cache
            (``statement_cache_size=0``) and the SQLAlchemy asyncpg dialect's
            prepared-statement cache (``prepared_statement_cache_size=0``) are
            disabled, because server-side prepared statements do NOT survive
            across transaction-pooled server connections — without this, a
            statement prepared on one pooled backend connection fails with
            ``prepared statement ... does not exist`` the next time PgBouncer
            hands the client a different backend. Both flags are harmless when
            connecting direct (non-pooled), so ``pooled=False`` simply omits
            them rather than needing a different code path.
        command_timeout_s: Client-side asyncpg ``command_timeout`` in seconds.
            A value <= 0 disables it (explicit operator opt-out, matching the
            behavior of the raw-URL wrappers this factory supersedes).
        statement_timeout_ms: Server-side ``statement_timeout`` in
            milliseconds. A value <= 0 disables it (unbounded).
        application_name: Surfaces this service/engine in
            ``pg_stat_activity`` for connection debugging (BP-502) — always
            required, never has a shared default, since a shared default would
            defeat its entire purpose (distinguishing engines in monitoring).
        pool_size: SQLAlchemy connection pool size.
        max_overflow: Additional connections allowed beyond ``pool_size``
            under burst load.
        pool_recycle: Seconds before a pooled connection is discarded and
            replaced — defends against stale DNS/Docker DNS resolution
            (BP-502) on long-uptime processes.
        pool_pre_ping: Issue a lightweight ``SELECT 1`` before handing out a
            pooled connection, so a connection that died while idle is
            detected and replaced instead of failing the caller's query.
        pool_timeout: Seconds to wait for a connection checkout before raising
            ``TimeoutError``. ``None`` uses SQLAlchemy's own default (30s).
            Services that need the market-data-style fail-fast behavior (10s)
            should pass it explicitly.
        connect_timeout_s: asyncpg's own connect-level timeout (covers DNS
            resolution + TCP handshake), forwarded as the asyncpg ``timeout``
            connect kwarg. This is DIFFERENT from ``command_timeout_s``: this
            one bounds establishing a NEW connection (e.g. the alert
            dispatcher's DNS-hiccup hardening, PLAN-0088 P0-4), while
            ``command_timeout_s`` bounds waiting for a command on an
            ALREADY-established connection. ``None`` omits it (asyncpg's
            default connect timeout is unbounded for DNS resolution).
        echo: SQLAlchemy engine-level SQL echo/debug logging.
        extra_connect_args: Additional asyncpg connect kwargs merged on top of
            (and able to override) the ones this factory builds — an escape
            hatch for a service-specific connect setting that doesn't belong
            in the shared signature. Applied last, so it wins on key
            collision; use sparingly and prefer promoting a genuinely shared
            setting into a named parameter instead.

    Returns:
        A configured, not-yet-connected :class:`AsyncEngine`. The caller owns
        the engine's lifecycle (``await engine.dispose()`` on shutdown).
    """
    server_settings: dict[str, str] = {"application_name": application_name}
    if statement_timeout_ms > 0:
        # asyncpg requires every server_settings value to be a string; Postgres
        # interprets a bare-integer string GUC value as milliseconds for
        # statement_timeout.
        server_settings["statement_timeout"] = str(statement_timeout_ms)

    connect_args: dict[str, object] = {"server_settings": server_settings}
    if command_timeout_s > 0:
        # Top-level asyncpg connect kwarg (NOT a server_setting) — SQLAlchemy's
        # asyncpg dialect forwards connect_args straight to asyncpg.connect().
        connect_args["command_timeout"] = float(command_timeout_s)

    if pooled:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0

    if connect_timeout_s is not None:
        connect_args["timeout"] = connect_timeout_s

    if extra_connect_args:
        connect_args.update(extra_connect_args)

    # Called with explicit keyword arguments (not a **kwargs dict unpack) so
    # mypy can check each one against SQLAlchemy's actual signature instead of
    # requiring a single blanket type: ignore for the whole call.
    if pool_timeout is not None:
        return create_async_engine(
            dsn,
            echo=echo,
            future=True,
            pool_pre_ping=pool_pre_ping,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
            connect_args=connect_args,
        )
    return create_async_engine(
        dsn,
        echo=echo,
        future=True,
        pool_pre_ping=pool_pre_ping,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        connect_args=connect_args,
    )
