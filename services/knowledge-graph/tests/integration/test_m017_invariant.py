"""PLAN-0089 F2 §8.1 — M-017 architecture invariant integration test.

M-017 invariant
---------------
Every ``canonical_entities`` row whose ``entity_type='financial_instrument'``
AND whose ``entity_id`` is a post-F2 UUIDv7 (i.e. starts with the UUIDv7
millisecond-timestamp prefix the seed data uses — ``0190...``) MUST have a
matching row in ``market_data.instruments`` with ``id = entity_id``.

WHY filter on the ``0190`` UUIDv7 prefix
----------------------------------------
intelligence_db migration 0009 seeded foreign-ticker canonical entities
(e.g. Korean / Shenzhen / Hong Kong / Tokyo tickers like ``.KS`` / ``.SZ``
/ ``.HK`` / ``.T``) under v4 UUIDs. Those rows pre-date the F2 unification
and have no counterpart in market_data (no OHLCV adapter for those venues
yet). They will be cleaned up under a separate plan; the M-017 invariant
applies only to entities seeded *post-F2*. UUIDv7 stamps the timestamp into
the leading bits, so ``entity_id LIKE '0190%'`` is a precise filter for
F2-era rows (all 2024-2026 seeds + all live-pipeline entities).

Runtime
-------
Marked ``integration`` — skipped automatically by the conftest probe if
either database is unreachable, so unit-only runs (``pytest -m unit``) do
not require live infrastructure. CI / ``make qa`` boots both Postgres
instances and runs this test.
"""

from __future__ import annotations

import os
import socket
import urllib.parse
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


# ── market_data_db fixture (paired with intelligence_db ``db_session``) ──────
# WHY a local fixture: the existing integration ``conftest.py`` only wires
# intelligence_db (the S7 service's own DB). M-017 is a CROSS-DB invariant —
# we need a second engine pointing at market_data_db. We open a tiny
# read-only engine here rather than polluting the shared conftest with state
# unused by every other integration test.
_MARKET_DATA_DB_URL = os.getenv(
    "S7_TEST_MARKET_DATA_DATABASE_URL",
    # docker-compose.test.yml maps market_data_db to host port 55434
    # (intelligence_db lives on 55433 — same pattern as ``conftest.TEST_DB_URL``).
    "postgresql+asyncpg://postgres:postgres@localhost:55434/market_data_db",
)


def _is_md_db_available() -> bool:
    """Quick TCP probe — mirrors ``conftest._is_db_available`` style."""
    try:
        parsed = urllib.parse.urlparse(_MARKET_DATA_DB_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect((host, port))
        sock.close()
    except OSError:
        return False
    return True


@pytest.fixture
async def market_data_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession bound to market_data_db.

    Skips the test if the DB is unreachable, so this fixture is safe to
    request from any integration test even when the local dev stack is
    down.
    """
    if not _is_md_db_available():
        pytest.skip(f"market_data_db not available at {_MARKET_DATA_DB_URL}")

    engine = create_async_engine(_MARKET_DATA_DB_URL, echo=False)
    try:
        # Verify the ``instruments`` table is present — guards against
        # connecting to a misconfigured DB (e.g. a stale volume from a
        # previous schema version).
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables " "WHERE table_name = 'instruments')")
            )
            if not result.scalar():
                pytest.skip("market_data_db.instruments table missing — run S2 alembic")

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
            await session.rollback()
    finally:
        await engine.dispose()


# ── The invariant test ──────────────────────────────────────────────────────


async def test_every_post_f2_tradable_canonical_entity_has_matching_instrument(
    db_session: AsyncSession,
    market_data_db_session: AsyncSession,
) -> None:
    """M-017: every F2-era canonical_entities row with entity_type =
    'financial_instrument' MUST have a matching row in
    market_data.instruments with id = entity_id.

    Pre-F2 legacy rows with v4 UUIDs (e.g. migration 0009 foreign tickers like
    ``.KS`` / ``.SZ`` / ``.HK`` / ``.T``) are NOT in market_data and are
    excluded from this invariant — they predate the unification and will be
    cleaned up under a separate plan. The UUIDv7 prefix ``0190`` identifies
    post-F2 seed rows.
    """
    # WHY ``text()``: SQLAlchemy async sessions require an explicit SQL
    # construct; raw string isn't accepted by ``AsyncSession.execute``.
    kg_rows = await db_session.execute(
        text(
            "SELECT entity_id FROM canonical_entities "
            "WHERE entity_type = 'financial_instrument' "
            "AND entity_id::text LIKE '0190%'"
        )
    )
    tradable_ids = {row.entity_id for row in kg_rows.fetchall()}

    instrument_rows = await market_data_db_session.execute(text("SELECT id FROM instruments"))
    instrument_ids = {row.id for row in instrument_rows.fetchall()}

    missing = tradable_ids - instrument_ids
    assert not missing, (
        f"M-017 violated: {len(missing)} F2-seeded tradable canonical entities "
        f"have no matching instrument. First 5: {list(missing)[:5]}"
    )
