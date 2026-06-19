"""Unit tests for the InsiderUniverseLoader + InsiderUniverseRefreshWorker.

Regression coverage for the 2026-06-18 reliability fixes
(docs/audits/2026-06-16-prd0089-l4b-insider-universe.md):

- ``upsert_insider_policies`` writes to the REAL ``polling_policies`` table
  (not the non-existent ``sched_policies``) — this test would FAIL against the
  old SQL with a "no such table: sched_policies" OperationalError.
- The written rows are ENABLED (``enabled=TRUE``), so the scheduler actually
  picks them up (old code wrote ``enabled=FALSE``).
- The ON CONFLICT upsert is idempotent and never duplicates rows.
- ``InsiderUniverseRefreshWorker`` is OFF by default (the env gate) and only
  runs when ``insider_universe_refresh_enabled`` is truthy.
- ``_seconds_until_next_run`` returns a strictly-positive weekly delay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from market_ingestion.config import Settings
from market_ingestion.infrastructure.workers.insider_universe_loader import (
    InsiderUniverseRefreshWorker,
    _seconds_until_next_run,
    run_insider_universe_load,
    upsert_insider_policies,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# In-memory DB fixture — creates the REAL polling_policies table from the ORM
# metadata, so a SQL statement targeting any other table name will fail loudly.
# ---------------------------------------------------------------------------


def _register_greatest(dbapi_conn: Any, _record: Any) -> None:
    """Register a scalar GREATEST(a, b) for SQLite (Postgres builtin).

    The production INSERT uses ``GREATEST(60, :interval / 10)``; SQLite lacks it,
    so we provide an equivalent. This keeps the test exercising the *real*
    INSERT SQL verbatim (table name included).
    """
    dbapi_conn.create_function("GREATEST", 2, lambda a, b: max(a, b))


# Raw DDL mirroring the real ``polling_policies`` schema (migrations
# 0001 / 0003 / 0008). Crucially it includes the NOT NULL *server* defaults for
# market_hours_only / tier / post_market_only / backfill_chunk_days — columns the
# loader's INSERT deliberately omits because Postgres fills them from defaults.
# The ORM model declares Python-side ``default=`` (not server_default), so
# ``create_all`` would NOT emit those defaults; using explicit DDL keeps the test
# faithful to the deployed schema.
_POLLING_POLICIES_DDL = """
CREATE TABLE polling_policies (
    id VARCHAR(26) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    dataset_type VARCHAR(50) NOT NULL,
    dataset_variant VARCHAR(100),
    symbol VARCHAR(50),
    exchange VARCHAR(20),
    timeframe VARCHAR(10),
    base_interval_sec INTEGER NOT NULL DEFAULT 3600,
    min_interval_sec INTEGER NOT NULL DEFAULT 60,
    jitter_sec INTEGER NOT NULL DEFAULT 10,
    adaptive_enabled BOOLEAN NOT NULL DEFAULT 0,
    adaptive_k FLOAT NOT NULL DEFAULT 1.0,
    adaptive_half_life_sec INTEGER NOT NULL DEFAULT 3600,
    priority INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    market_hours_only BOOLEAN NOT NULL DEFAULT 0,
    tier INTEGER NOT NULL DEFAULT 2,
    post_market_only BOOLEAN NOT NULL DEFAULT 0,
    backfill_enabled BOOLEAN NOT NULL DEFAULT 0,
    backfill_start_date DATE,
    backfill_chunk_days INTEGER DEFAULT 30,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


@pytest.fixture
async def session_factory() -> Any:
    """An aiosqlite session factory with the polling_policies table created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sa.event.listen(engine.sync_engine, "connect", _register_greatest)
    async with engine.begin() as conn:
        await conn.execute(sa.text(_POLLING_POLICIES_DDL))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# upsert_insider_policies — table name + enabled flag (the headline bugs)
# ---------------------------------------------------------------------------


class TestUpsertInsiderPolicies:
    async def test_writes_to_polling_policies_table(self, session_factory: Any) -> None:
        """Rows land in polling_policies — fails on old 'sched_policies' SQL."""
        symbols = [{"symbol": "AAPL", "exchange": "US"}, {"symbol": "MSFT", "exchange": "US"}]
        async with session_factory() as session:
            offered = await upsert_insider_policies(session=session, symbols=symbols)
            await session.commit()
        assert offered == 2

        # Query the rows back from the REAL table. If the INSERT had targeted
        # sched_policies this select would return nothing (and the insert would
        # have raised). Confirms the wrong-table bug is fixed.
        async with session_factory() as session:
            rows = (
                await session.execute(
                    sa.text(
                        "SELECT symbol, dataset_type, provider, enabled, base_interval_sec "
                        "FROM polling_policies ORDER BY symbol"
                    )
                )
            ).all()
        assert [r[0] for r in rows] == ["AAPL", "MSFT"]
        assert all(r[1] == "insider_transactions" for r in rows)
        assert all(r[2] == "eodhd" for r in rows)

    async def test_rows_are_enabled(self, session_factory: Any) -> None:
        """Policies are written ENABLED so the scheduler picks them up."""
        async with session_factory() as session:
            await upsert_insider_policies(session=session, symbols=[{"symbol": "NVDA", "exchange": "US"}])
            await session.commit()
        async with session_factory() as session:
            enabled = (
                await session.execute(sa.text("SELECT enabled FROM polling_policies WHERE symbol = 'NVDA'"))
            ).scalar_one()
        # SQLite stores booleans as 0/1; TRUE in the INSERT must surface truthy.
        assert bool(enabled) is True

    async def test_weekly_interval(self, session_factory: Any) -> None:
        async with session_factory() as session:
            await upsert_insider_policies(session=session, symbols=[{"symbol": "TSLA", "exchange": "US"}])
            await session.commit()
        async with session_factory() as session:
            interval = (
                await session.execute(sa.text("SELECT base_interval_sec FROM polling_policies WHERE symbol = 'TSLA'"))
            ).scalar_one()
        assert interval == 604800  # weekly

    async def test_idempotent_no_duplicates(self, session_factory: Any) -> None:
        symbols = [{"symbol": "AMZN", "exchange": "US"}]
        for _ in range(3):
            async with session_factory() as session:
                await upsert_insider_policies(session=session, symbols=symbols)
                await session.commit()
        async with session_factory() as session:
            count = (
                await session.execute(sa.text("SELECT COUNT(*) FROM polling_policies WHERE symbol = 'AMZN'"))
            ).scalar_one()
        assert count == 1

    async def test_empty_symbols_is_noop(self, session_factory: Any) -> None:
        async with session_factory() as session:
            offered = await upsert_insider_policies(session=session, symbols=[])
        assert offered == 0


# ---------------------------------------------------------------------------
# run_insider_universe_load — wires fetch + upsert
# ---------------------------------------------------------------------------


class TestRunInsiderUniverseLoad:
    async def test_load_persists_fetched_symbols(self, session_factory: Any) -> None:
        settings = SimpleNamespace(market_data_url="http://md:8003", internal_jwt_private_key="")
        fetched = [{"symbol": "AAPL", "exchange": "US"}, {"symbol": "GOOG", "exchange": "US"}]
        with patch(
            "market_ingestion.infrastructure.workers.insider_universe_loader.fetch_ohlcv_covered_symbols",
            AsyncMock(return_value=fetched),
        ):
            offered = await run_insider_universe_load(
                settings=settings,  # type: ignore[arg-type]
                session_factory=session_factory,
            )
        assert offered == 2
        async with session_factory() as session:
            count = (await session.execute(sa.text("SELECT COUNT(*) FROM polling_policies"))).scalar_one()
        assert count == 2

    async def test_load_no_symbols_is_noop(self, session_factory: Any) -> None:
        settings = SimpleNamespace(market_data_url="http://md:8003", internal_jwt_private_key="")
        with patch(
            "market_ingestion.infrastructure.workers.insider_universe_loader.fetch_ohlcv_covered_symbols",
            AsyncMock(return_value=[]),
        ):
            offered = await run_insider_universe_load(
                settings=settings,  # type: ignore[arg-type]
                session_factory=session_factory,
            )
        assert offered == 0


# ---------------------------------------------------------------------------
# InsiderUniverseRefreshWorker — gated scheduling (default OFF)
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> SimpleNamespace:
    base = {
        "insider_universe_refresh_enabled": False,
        "insider_universe_refresh_day_of_week": 6,
        "insider_universe_refresh_hour_utc": 5,
        "market_data_url": "http://md:8003",
        "internal_jwt_private_key": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRefreshWorkerGate:
    def test_real_settings_default_is_off(self) -> None:
        """The shipped config default must be OFF (no silent EODHD spend)."""
        settings = Settings(  # type: ignore[call-arg]
            storage_access_key="x",  # required fields
            storage_secret_key="y",
        )
        assert settings.insider_universe_refresh_enabled is False

    def test_enabled_property_reads_setting(self) -> None:
        assert InsiderUniverseRefreshWorker(settings=_settings()).enabled is False  # type: ignore[arg-type]
        assert (
            InsiderUniverseRefreshWorker(
                settings=_settings(insider_universe_refresh_enabled=True)  # type: ignore[arg-type]
            ).enabled
            is True
        )

    async def test_run_is_noop_when_disabled(self) -> None:
        """OFF default must NOT call the load (would spend credits)."""
        worker = InsiderUniverseRefreshWorker(settings=_settings())  # type: ignore[arg-type]
        with patch(
            "market_ingestion.infrastructure.workers.insider_universe_loader.run_insider_universe_load",
            AsyncMock(),
        ) as mock_load:
            await worker.run()
        mock_load.assert_not_awaited()

    async def test_run_executes_load_when_enabled(self) -> None:
        """When enabled, the loop runs the load then exits on stop()."""
        worker = InsiderUniverseRefreshWorker(
            settings=_settings(insider_universe_refresh_enabled=True),  # type: ignore[arg-type]
        )

        async def _fake_sleep(_delay: float) -> None:
            # Fire stop after the first scheduled-slot wait so the loop runs the
            # load exactly once then terminates.
            return None

        # Patch the stop-event wait so the loop reaches the load immediately.
        with (
            patch(
                "market_ingestion.infrastructure.workers.insider_universe_loader.run_insider_universe_load",
                AsyncMock(return_value=42),
            ) as mock_load,
            patch(
                "market_ingestion.infrastructure.workers.insider_universe_loader._seconds_until_next_run",
                return_value=0.0,
            ),
        ):
            # After one load, stop the loop.
            async def _load_then_stop(*_a: Any, **_k: Any) -> int:
                worker.stop()
                return 42

            mock_load.side_effect = _load_then_stop
            await worker.run()
        mock_load.assert_awaited()

    def test_stop_sets_event(self) -> None:
        worker = InsiderUniverseRefreshWorker(settings=_settings())  # type: ignore[arg-type]
        assert worker._stop_event.is_set() is False
        worker.stop()
        assert worker._stop_event.is_set() is True


class TestSecondsUntilNextRun:
    def test_returns_positive_delay(self) -> None:
        now = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)  # Thursday
        delay = _seconds_until_next_run(now=now, day_of_week=6, hour_utc=5)  # Sunday 05:00
        assert delay > 0
        # Sunday 05:00 is 2 days + 17 hours after Thu 12:00.
        assert delay == pytest.approx((2 * 86400) + (17 * 3600))

    def test_same_day_past_hour_rolls_to_next_week(self) -> None:
        now = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)  # Sunday, past 05:00
        delay = _seconds_until_next_run(now=now, day_of_week=6, hour_utc=5)
        assert delay == pytest.approx(7 * 86400 - (7 * 3600))
