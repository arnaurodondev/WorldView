"""Pool hardening tests for the DB engines (BP-720 amplifier fix, 2026-07-09).

These assert the *fail-fast* pool configuration that prevents a single leaked /
cancelled read from silently blocking later readers for a full minute:

* ``pool_timeout`` 10s (was 60s)
* ``pool_use_lifo=True``
* server-side ``statement_timeout`` applied to every connection

``create_async_engine`` is lazy — it does not open a socket — so these build
real engines against a dummy URL without a live database.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_data.infrastructure.db.session import (
    _COMMAND_TIMEOUT_SECONDS,
    _POOL_TIMEOUT_SECONDS,
    _STATEMENT_TIMEOUT_MS,
    _connect_args,
    build_read_engine,
    build_write_engine,
)
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _settings():
    # Minimal duck-typed Settings; asyncpg URL so create_async_engine picks the
    # async dialect without connecting.
    return SimpleNamespace(
        debug=False,
        database_url=SecretStr("postgresql+asyncpg://u:p@localhost:5432/db"),
        read_replica_url=None,
    )


def test_connect_args_sets_statement_timeout_and_app_name() -> None:
    args = _connect_args()
    server_settings = args["server_settings"]
    assert server_settings["statement_timeout"] == _STATEMENT_TIMEOUT_MS
    assert server_settings["statement_timeout"] == "8000"
    assert server_settings["application_name"] == "market-data"


def test_connect_args_sets_client_side_command_timeout() -> None:
    """BP-732 parity fix (2026-07-24) — market-data was the one pooled service
    ``scripts/check_db_session_parity.py`` flagged as missing a client-side
    ``command_timeout``. Without it, the server-side ``statement_timeout``
    above is the ONLY backstop against a hung connection — and that GUC is a
    non-native PgBouncer startup parameter that may be silently dropped under
    transaction pooling (see ``_connect_args``'s docstring). This asserts the
    asyncpg-level backstop that has no such caveat is present, matching every
    other pooled service's session.py in this repo.
    """
    args = _connect_args()
    assert args["command_timeout"] == _COMMAND_TIMEOUT_SECONDS
    # Must sit above the existing fail-fast budget (8s statement + 10s pool
    # checkout) so it never fires before those more specific timeouts.
    assert _COMMAND_TIMEOUT_SECONDS > _POOL_TIMEOUT_SECONDS
    assert _COMMAND_TIMEOUT_SECONDS > int(_STATEMENT_TIMEOUT_MS) / 1000


def test_connect_args_disables_prepared_statements_for_pgbouncer() -> None:
    # PgBouncer transaction pooling (2026-07-19 Postgres-OOM fix): server-side
    # prepared statements must be disabled or asyncpg errors on a reused pooled
    # server connection. Both asyncpg's and the SQLAlchemy dialect's caches off.
    args = _connect_args()
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0


@pytest.mark.parametrize("builder", [build_write_engine, build_read_engine])
def test_engine_pool_is_fail_fast(builder) -> None:
    engine = builder(_settings())
    try:
        pool = engine.pool
        # Fail-fast checkout window (dropped from 60s).
        assert _POOL_TIMEOUT_SECONDS == 10
        assert pool._timeout == 10  # type: ignore[attr-defined]
        # LIFO reuse so idle connections age out at the tail. The flag lives on
        # the pool's underlying queue in SQLAlchemy 2.x.
        assert pool._pool.use_lifo is True  # type: ignore[attr-defined]
    finally:
        # Sync dispose is safe: no connections were ever opened.
        engine.sync_engine.dispose()
