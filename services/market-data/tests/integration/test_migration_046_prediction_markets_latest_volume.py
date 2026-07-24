"""Real-DB test for migration 046 (denormalize latest_volume_24h onto prediction_markets).

WHY A DEDICATED CONTAINER (not the shared ``_migrated_db`` fixture from
``conftest.py``): this test needs to run migrations up to 045 FIRST, insert
"pre-migration" fixture data directly (bypassing the ORM, mimicking rows that
existed in production before this migration ships), and THEN upgrade to 046
to observe the backfill. The shared session-scoped ``_migrated_db`` fixture
always migrates straight to ``head`` once and is reused read/write by every
other integration test in the suite — stepping it backward would corrupt
that shared state for tests that run before/after this one in the same
session. A dedicated, module-scoped container isolates this migration
exercise completely.

WHY THESE TESTS ARE SYNC (not ``async def``, unlike the rest of the
integration suite): ``alembic``'s ``env.py`` for this project drives
migrations through an async engine internally via its own ``asyncio.run(...)``
call (see ``alembic/env.py::run_migrations_online``). Calling
``alembic.command.upgrade/downgrade`` from a coroutine that is already
running inside a pytest-asyncio event loop raises ``RuntimeError:
asyncio.run() cannot be called from a running event loop``. Keeping these
test functions plain ``def`` (no event loop running) lets Alembic manage its
own loop; the async SQLAlchemy engine work needed to seed/verify data is
wrapped in small local coroutines driven by ``asyncio.run(...)`` from that
same sync context.

Covers the /implement Gate mandate: "test the migration locally against a
test/local Postgres — confirm the backfill actually populates correctly on
seeded fixture data mimicking multiple markets with snapshot history."
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SERVICE_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def _mig046_container():
    """A dedicated TimescaleDB container for this migration test only."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        dbname="market_data_db",
        username="postgres",
        password="postgres",
    ) as container:
        yield container


def _asyncpg_url(container) -> str:
    raw_url = container.get_connection_url()
    return raw_url.replace("postgresql://", "postgresql+asyncpg://").replace("psycopg2", "asyncpg")


def _run_alembic(asyncpg_url: str, target: str, *, direction: str) -> None:
    """Run ``alembic upgrade`` or ``downgrade`` to ``target`` synchronously.

    Must be called from a context with NO asyncio event loop running (see
    module docstring) — Alembic's own ``env.py`` manages its async engine via
    ``asyncio.run(...)`` internally.
    """
    from alembic import command
    from alembic.config import Config

    os.environ["ALEMBIC_URL"] = asyncpg_url
    try:
        cfg = Config(str(_SERVICE_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_SERVICE_DIR / "alembic"))
        if direction == "upgrade":
            command.upgrade(cfg, target)
        else:
            command.downgrade(cfg, target)
    finally:
        os.environ.pop("ALEMBIC_URL", None)


@pytest.fixture
def pre_046_url(_mig046_container) -> str:
    """Migrate the dedicated container to revision 045 (pre-denormalization).

    Yields the asyncpg connection URL. Teardown truncates the two tables this
    module seeds and resets the container back to revision 045, so the next
    test function sharing the module-scoped container starts from an
    identical, empty baseline.
    """
    asyncpg_url = _asyncpg_url(_mig046_container)
    _run_alembic(asyncpg_url, "045", direction="upgrade")

    yield asyncpg_url

    async def _cleanup() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(asyncpg_url, echo=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE TABLE prediction_market_snapshots, prediction_markets CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(_cleanup())
    # Whatever revision the test left the DB at (045 or 046), settle back to
    # 045 so the next test's "upgrade to 045" setup step is a clean no-op.
    _run_alembic(asyncpg_url, "045", direction="downgrade")


async def _seed_pre_migration_fixture(asyncpg_url: str) -> None:
    """Insert markets + snapshot history directly (bypassing the ORM/repo).

    Mimics production data as it exists BEFORE migration 046 ships:
    ``prediction_markets`` rows with NO ``latest_volume_24h`` column yet
    (revision 045), and pre-existing snapshot history in
    ``prediction_market_snapshots`` for three markets:

      * ``mkt-a``: 3 snapshots, newest volume_24h=500 at t=12:00.
      * ``mkt-b``: 1 snapshot, volume_24h=NULL (market with no recorded volume).
      * ``mkt-c``: 0 snapshots (open market that was never polled/snapshotted)
        — must stay NULL after backfill, not error.
      * ``mkt-a`` ALSO seeds a pre-existing, STALE non-NULL
        ``last_snapshot_at`` (mimicking migration 006's one-time backfill,
        which nothing kept in sync until this migration's write-path change)
        to regression-guard the backfill overwriting it with the TRUE
        newest snapshot_at rather than preserving the stale value via
        ``COALESCE`` (a bug caught in review before this migration merged —
        see the migration's own docstring / SET clause comment).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(asyncpg_url, echo=False)
    try:
        async with engine.begin() as conn:
            for market_id, question in (
                ("mkt-a", "Will A happen?"),
                ("mkt-b", "Will B happen?"),
                ("mkt-c", "Will C happen?"),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO prediction_markets "
                        "(id, market_id, source, question, outcomes, resolution_status, last_snapshot_at) "
                        "VALUES (:id, :market_id, 'polymarket', :question, '[]'::jsonb, 'open', "
                        ":stale_last_snapshot_at)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "market_id": market_id,
                        "question": question,
                        # Only mkt-a gets a pre-existing (stale) value — see
                        # docstring above; mkt-b/mkt-c start NULL like a market
                        # that predates migration 006's backfill entirely.
                        "stale_last_snapshot_at": (
                            datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC) if market_id == "mkt-a" else None
                        ),
                    },
                )

            # mkt-a: 3 historical snapshots; the newest (12:00, volume=500) must win
            # — and must OVERWRITE the stale last_snapshot_at seeded above (2026-03-01).
            for hour, volume in ((10, 100), (11, 300), (12, 500)):
                await conn.execute(
                    text(
                        "INSERT INTO prediction_market_snapshots "
                        "(id, market_id, snapshot_at, outcomes_prices, volume_24h, source_event_id) "
                        "VALUES (:id, 'mkt-a', :snapshot_at, '{\"Yes\": 0.5, \"No\": 0.5}'::jsonb, :volume, 'evt-a')"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "snapshot_at": datetime(2026, 4, 9, hour, 0, 0, tzinfo=UTC),
                        "volume": volume,
                    },
                )

            # mkt-b: single snapshot with NULL volume_24h.
            await conn.execute(
                text(
                    "INSERT INTO prediction_market_snapshots "
                    "(id, market_id, snapshot_at, outcomes_prices, volume_24h, source_event_id) "
                    "VALUES (:id, 'mkt-b', :snapshot_at, '{\"Yes\": 0.5, \"No\": 0.5}'::jsonb, NULL, 'evt-b')"
                ),
                {"id": str(uuid.uuid4()), "snapshot_at": datetime(2026, 4, 9, 9, 0, 0, tzinfo=UTC)},
            )
            # mkt-c: intentionally no snapshots at all.
    finally:
        await engine.dispose()


async def _fetch_markets(asyncpg_url: str) -> dict[str, object]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(asyncpg_url, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT market_id, latest_volume_24h, last_snapshot_at FROM prediction_markets ORDER BY market_id")
            )
            return {row.market_id: row for row in result.fetchall()}
    finally:
        await engine.dispose()


def test_backfill_populates_latest_volume_from_newest_snapshot(pre_046_url) -> None:
    """The 046 backfill picks each market's NEWEST snapshot's volume_24h."""
    asyncio.run(_seed_pre_migration_fixture(pre_046_url))

    # Run the migration under test (045 -> 046): adds the column + backfills.
    _run_alembic(pre_046_url, "048", direction="upgrade")

    rows = asyncio.run(_fetch_markets(pre_046_url))

    # mkt-a: backfilled from the NEWEST (12:00) snapshot, not the oldest/any other.
    assert rows["mkt-a"].latest_volume_24h == Decimal("500.0000")
    # REGRESSION GUARD: mkt-a was seeded with a STALE pre-existing
    # last_snapshot_at (2026-03-01, mimicking migration 006's one-time
    # backfill that nothing kept in sync). The backfill MUST overwrite it
    # with the true newest snapshot_at (2026-04-09 12:00) — a prior draft of
    # this migration used `COALESCE(pm.last_snapshot_at, sub.snapshot_at)`,
    # which would have left the stale 2026-03-01 value in place here and
    # broken list_markets()'s volume_window_days CASE for every
    # already-synced market on deploy (caught in review, see the migration's
    # SET clause comment).
    assert rows["mkt-a"].last_snapshot_at != datetime(2026, 3, 1, tzinfo=UTC)
    assert rows["mkt-a"].last_snapshot_at == datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)

    # mkt-b: has a snapshot, but its volume_24h was NULL — backfill preserves NULL
    # (never fabricates a value), while last_snapshot_at IS populated (a real
    # snapshot exists, just with no volume recorded).
    assert rows["mkt-b"].latest_volume_24h is None
    assert rows["mkt-b"].last_snapshot_at == datetime(2026, 4, 9, 9, 0, 0, tzinfo=UTC)

    # mkt-c: no snapshot history at all — both columns stay NULL, no error.
    assert rows["mkt-c"].latest_volume_24h is None
    assert rows["mkt-c"].last_snapshot_at is None


def test_downgrade_drops_latest_volume_column_cleanly(pre_046_url) -> None:
    """``downgrade()`` removes latest_volume_24h without touching last_snapshot_at."""
    asyncio.run(_seed_pre_migration_fixture(pre_046_url))
    _run_alembic(pre_046_url, "048", direction="upgrade")

    async def _select_column(column: str) -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(pre_046_url, echo=False)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(f"SELECT {column} FROM prediction_markets LIMIT 1"))  # noqa: S608
                result.fetchall()
        finally:
            await engine.dispose()

    # Sanity: the column exists post-upgrade.
    asyncio.run(_select_column("latest_volume_24h"))

    _run_alembic(pre_046_url, "047", direction="downgrade")

    # Post-downgrade: the column must be gone (querying it raises).
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError):
        asyncio.run(_select_column("latest_volume_24h"))

    # last_snapshot_at (owned by migration 006) must be unaffected by 046's downgrade.
    asyncio.run(_select_column("last_snapshot_at"))

    # NOTE: the pre_046_url fixture's teardown truncates the seeded tables and
    # re-issues `downgrade(..., "045")` unconditionally — a no-op here since
    # we're already at 045 — so no explicit cleanup is needed in this test body.
