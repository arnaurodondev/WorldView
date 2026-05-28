"""Integration tests for all PostgreSQL repository adapters.

Covers:
- PgSecurityRepository  (4 tests)
- PgInstrumentRepository (6 tests)
- PgOHLCVRepository      (5 tests)
- PgQuoteRepository      (4 tests)

Total: 19 tests (all backed by real TimescaleDB container).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ── helpers ──────────────────────────────────────────────────────────────────


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


# ── Security repository ───────────────────────────────────────────────────────


class TestPgSecurityRepository:
    async def test_upsert_creates_new(self, uow) -> None:
        from market_data.domain.entities import Security

        sec = Security(figi="BBG001", isin="US0000000001", name="Test Corp")
        created = await uow.securities.upsert(sec)
        await uow.commit()

        assert created.id == sec.id
        assert created.figi == "BBG001"
        assert created.name == "Test Corp"

    async def test_find_by_figi_returns_record(self, uow) -> None:
        from market_data.domain.entities import Security

        sec = Security(figi="BBG002", name="Figi Corp")
        await uow.securities.upsert(sec)
        await uow.commit()

        found = await uow.securities.find_by_figi("BBG002")
        assert found is not None
        assert found.name == "Figi Corp"

    async def test_find_by_figi_missing_returns_none(self, uow) -> None:
        result = await uow.securities.find_by_figi("BBG-NONEXISTENT")
        assert result is None

    async def test_find_by_isin_returns_record(self, uow) -> None:
        from market_data.domain.entities import Security

        sec = Security(isin="US9999999999", name="ISIN Corp")
        await uow.securities.upsert(sec)
        await uow.commit()

        found = await uow.securities.find_by_isin("US9999999999")
        assert found is not None
        assert found.name == "ISIN Corp"

    async def test_upsert_same_figi_with_new_id_updates_existing_row(self, uow) -> None:
        from market_data.domain.entities import Security

        first = Security(figi="BBG-FIGI-UPSERT", isin="US1111111111", name="Original Name")
        created = await uow.securities.upsert(first)
        await uow.commit()

        second = Security(figi="BBG-FIGI-UPSERT", isin="US1111111111", name="Updated Name")
        updated = await uow.securities.upsert(second)
        await uow.commit()

        assert updated.id == created.id
        assert updated.name == "Updated Name"


# ── Instrument repository ─────────────────────────────────────────────────────


class TestPgInstrumentRepository:
    async def _make_security(self, uow) -> str:
        """Insert a security and return its id."""
        from market_data.domain.entities import Security

        sec = Security(name="Parent Corp")
        await uow.securities.upsert(sec)
        await uow.commit()
        return sec.id

    async def test_upsert_creates_new(self, uow) -> None:
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="AAPL", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()

        assert created.symbol == "AAPL"
        assert created.exchange == "XNAS"

    async def test_upsert_is_idempotent_on_symbol_exchange(self, uow) -> None:
        from market_data.domain.entities import Instrument
        from market_data.domain.value_objects import InstrumentFlags

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="GOOG", exchange="XNAS")
        first = await uow.instruments.upsert(instr)
        await uow.commit()

        # Second upsert with updated flags
        instr2 = Instrument(
            security_id=sec_id,
            symbol="GOOG",
            exchange="XNAS",
            flags=InstrumentFlags(has_ohlcv=True),
        )
        second = await uow.instruments.upsert(instr2)
        await uow.commit()

        # Same row, updated flag
        assert first.id == second.id
        assert second.flags.has_ohlcv is True

    async def test_find_by_symbol_exchange(self, uow) -> None:
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="MSFT", exchange="XNAS")
        await uow.instruments.upsert(instr)
        await uow.commit()

        found = await uow.instruments.find_by_symbol_exchange("MSFT", "XNAS")
        assert found is not None
        assert found.symbol == "MSFT"

    async def test_find_by_id(self, uow) -> None:
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="AMZN", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()

        found = await uow.instruments.find_by_id(created.id)
        assert found is not None
        assert found.id == created.id

    async def test_update_flags(self, uow) -> None:
        from market_data.domain.entities import Instrument
        from market_data.domain.value_objects import InstrumentFlags

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="TSLA", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()

        new_flags = InstrumentFlags(has_ohlcv=True, has_quotes=True)
        await uow.instruments.update_flags(created.id, new_flags)
        await uow.commit()

        updated = await uow.instruments.find_by_id(created.id)
        assert updated is not None
        assert updated.flags.has_ohlcv is True
        assert updated.flags.has_quotes is True

    async def test_search_by_symbol(self, uow) -> None:
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="NVDA", exchange="XNAS")
        await uow.instruments.upsert(instr)
        await uow.commit()

        results = await uow.instruments.search("NVD")
        symbols = [i.symbol for i in results]
        assert "NVDA" in symbols

    async def test_touch_fundamentals_ingest_at_persists(self, uow) -> None:
        """PLAN-0101 / BP-610 regression.

        ``touch_fundamentals_ingest_at`` must persist the new timestamp through
        a commit boundary. Before the fix the SQLAlchemy Core ``update()`` call
        was buffered in the session and silently dropped whenever a later
        in-UoW op (specifically the best-effort
        ``_upsert_fundamentals_snapshot``) raised + the consumer's try/except
        swallowed the exception. Live observation: 0 of 629 instruments had a
        non-NULL value despite the call wiring being correct since commit
        ``8450666b``. The fix adds an explicit ``await self._session.flush()``
        inside the repo method (matches the repo-wide convention in
        ``content-store`` / ``alert`` / ``rag-chat``).

        This test bumps the column, commits, then reads the row back via a
        raw ``text()`` SELECT (bypasses ORM identity map) to assert the
        UPDATE actually reached the database.
        """
        from market_data.domain.entities import Instrument
        from sqlalchemy import text

        sec_id = await self._make_security(uow)
        instr = Instrument(security_id=sec_id, symbol="FRSH", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()

        ts = datetime(2026, 5, 28, 12, 34, 56, tzinfo=UTC)
        await uow.instruments.touch_fundamentals_ingest_at(created.id, ts)
        await uow.commit()

        row = (
            await uow._write().execute(  # -- test-only access to write session
                text("SELECT last_fundamentals_ingest_at FROM instruments WHERE id = :iid"),
                {"iid": created.id},
            )
        ).one()
        assert row.last_fundamentals_ingest_at is not None
        assert row.last_fundamentals_ingest_at == ts


# ── OHLCV repository ──────────────────────────────────────────────────────────


class TestPgOHLCVRepository:
    async def _make_instrument(self, uow) -> str:
        from market_data.domain.entities import Instrument, Security

        sec = Security(name="OHLCV Test Corp")
        await uow.securities.upsert(sec)
        instr = Instrument(security_id=sec.id, symbol="OHLT", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()
        return created.id

    async def test_bulk_upsert_and_find_by_range(self, uow) -> None:
        from market_data.domain.entities import OHLCVBar
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        instr_id = await self._make_instrument(uow)
        bars = [
            OHLCVBar(
                instrument_id=instr_id,
                timeframe=Timeframe.ONE_DAY,
                bar_date=_utc(2024, 1, d),
                open=Decimal(100),
                high=Decimal(110),
                low=Decimal(95),
                close=Decimal(105),
                volume=1000 * d,
                provider_priority=ProviderPriority(provider="polygon", priority=100),
            )
            for d in range(1, 6)
        ]
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()

        from datetime import date

        results = await uow.ohlcv.find_by_instrument_timeframe_range(
            instr_id,
            Timeframe.ONE_DAY,
            date(2024, 1, 1),
            date(2024, 1, 5),
        )
        assert len(results) == 5
        assert results[0].bar_date.date() == date(2024, 1, 1)
        assert results[-1].bar_date.date() == date(2024, 1, 5)

    async def test_bulk_upsert_empty_is_noop(self, uow) -> None:
        # Should not raise; no DB changes
        await uow.ohlcv.bulk_upsert_with_priority([])
        await uow.commit()

    async def test_get_available_timeframes(self, uow) -> None:
        from market_data.domain.entities import OHLCVBar
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        instr_id = await self._make_instrument(uow)
        for tf in [Timeframe.ONE_DAY, Timeframe.ONE_HOUR]:
            await uow.ohlcv.bulk_upsert_with_priority(
                [
                    OHLCVBar(
                        instrument_id=instr_id,
                        timeframe=tf,
                        bar_date=_utc(2024, 2, 1),
                        open=Decimal(50),
                        high=Decimal(55),
                        low=Decimal(48),
                        close=Decimal(52),
                        volume=500,
                        provider_priority=ProviderPriority(provider="yahoo", priority=80),
                    ),
                ]
            )
        await uow.commit()

        tfs = await uow.ohlcv.get_available_timeframes(instr_id)
        tf_vals = {str(t) for t in tfs}
        assert "1d" in tf_vals
        assert "1h" in tf_vals

    async def test_get_date_range(self, uow) -> None:
        from datetime import date

        from market_data.domain.entities import OHLCVBar
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        instr_id = await self._make_instrument(uow)
        bars = [
            OHLCVBar(
                instrument_id=instr_id,
                timeframe=Timeframe.ONE_DAY,
                bar_date=_utc(2024, 3, d),
                open=Decimal(200),
                high=Decimal(210),
                low=Decimal(190),
                close=Decimal(205),
                volume=2000,
                provider_priority=ProviderPriority(provider="polygon", priority=100),
            )
            for d in [5, 10, 15]
        ]
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()

        date_range = await uow.ohlcv.get_date_range(instr_id, Timeframe.ONE_DAY)
        assert date_range is not None
        min_d, max_d = date_range
        assert min_d == date(2024, 3, 5)
        assert max_d == date(2024, 3, 15)

    async def test_priority_conflict_lower_does_not_overwrite(self, uow) -> None:
        """Lower-priority provider must NOT overwrite higher-priority stored data."""
        from market_data.domain.entities import OHLCVBar
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        instr_id = await self._make_instrument(uow)
        bar_date = _utc(2024, 4, 1)

        # First: write high-priority (polygon=100) bar
        high_priority_bar = OHLCVBar(
            instrument_id=instr_id,
            timeframe=Timeframe.ONE_DAY,
            bar_date=bar_date,
            open=Decimal(300),
            high=Decimal(310),
            low=Decimal(290),
            close=Decimal(305),
            volume=9000,
            provider_priority=ProviderPriority(provider="polygon", priority=100),
        )
        await uow.ohlcv.bulk_upsert_with_priority([high_priority_bar])
        await uow.commit()

        # Then: write low-priority (yahoo=80) bar for the same date
        low_priority_bar = OHLCVBar(
            instrument_id=instr_id,
            timeframe=Timeframe.ONE_DAY,
            bar_date=bar_date,
            open=Decimal(999),
            high=Decimal(999),
            low=Decimal(999),
            close=Decimal(999),
            volume=1,
            provider_priority=ProviderPriority(provider="yahoo", priority=80),
        )
        await uow.ohlcv.bulk_upsert_with_priority([low_priority_bar])
        await uow.commit()

        from datetime import date

        results = await uow.ohlcv.find_by_instrument_timeframe_range(
            instr_id,
            Timeframe.ONE_DAY,
            date(2024, 4, 1),
            date(2024, 4, 1),
        )
        assert len(results) == 1
        # High-priority data must be preserved
        assert results[0].close == Decimal(305)


# ── Quote repository ──────────────────────────────────────────────────────────


class TestPgQuoteRepository:
    async def _make_instrument(self, uow) -> str:
        from market_data.domain.entities import Instrument, Security

        sec = Security(name="Quote Test Corp")
        await uow.securities.upsert(sec)
        instr = Instrument(security_id=sec.id, symbol="QTST", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()
        return created.id

    async def test_upsert_creates_quote(self, uow) -> None:
        from market_data.domain.entities import Quote

        instr_id = await self._make_instrument(uow)
        quote = Quote(
            instrument_id=instr_id,
            bid=Decimal("99.50"),
            ask=Decimal("100.00"),
            last=Decimal("99.75"),
            volume=5000,
            timestamp=datetime.now(tz=UTC),
        )
        saved = await uow.quotes.upsert(quote)
        await uow.commit()

        assert saved.instrument_id == instr_id
        assert saved.bid == Decimal("99.50")

    async def test_upsert_updates_existing_quote(self, uow) -> None:
        from market_data.domain.entities import Quote

        instr_id = await self._make_instrument(uow)
        q1 = Quote(
            instrument_id=instr_id,
            bid=Decimal("10.00"),
            ask=Decimal("10.05"),
            last=Decimal("10.02"),
            volume=100,
            timestamp=datetime.now(tz=UTC),
        )
        await uow.quotes.upsert(q1)
        await uow.commit()

        q2 = Quote(
            instrument_id=instr_id,
            bid=Decimal("20.00"),
            ask=Decimal("20.05"),
            last=Decimal("20.02"),
            volume=200,
            timestamp=datetime.now(tz=UTC),
        )
        updated = await uow.quotes.upsert(q2)
        await uow.commit()

        assert updated.bid == Decimal("20.00")

    async def test_find_by_instrument_returns_latest(self, uow) -> None:
        from market_data.domain.entities import Quote

        instr_id = await self._make_instrument(uow)
        quote = Quote(
            instrument_id=instr_id,
            bid=Decimal("50.00"),
            ask=Decimal("50.50"),
            last=Decimal("50.25"),
            volume=300,
            timestamp=datetime.now(tz=UTC),
        )
        await uow.quotes.upsert(quote)
        await uow.commit()

        found = await uow.quotes.find_by_instrument(instr_id)
        assert found is not None
        assert found.instrument_id == instr_id

    async def test_find_by_instrument_missing_returns_none(self, uow) -> None:
        result = await uow.quotes.find_by_instrument("00000000-0000-0000-0000-000000000000")
        assert result is None


# ── PgFundamentalMetricsRepository (ROPT-10) ─────────────────────────────────


class TestPgFundamentalMetricsRepository:
    """Integration tests for the read-optimized fundamental_metrics projection.

    Covers:
    - Upsert creates a row and can be read back
    - ON CONFLICT DO UPDATE (idempotent re-ingest overwrites values)
    - Timeseries query returns sorted points and respects date boundaries
    - Screening uses latest date per metric per instrument (AND semantics)
    - Available metrics query returns distinct metric names
    """

    async def _make_instrument(self, uow) -> str:
        from market_data.domain.entities import Instrument, Security

        sec = Security(name="Metrics Test Corp")
        await uow.securities.upsert(sec)
        instr = Instrument(security_id=sec.id, symbol="MTRX", exchange="XNAS")
        created = await uow.instruments.upsert(instr)
        await uow.commit()
        return created.id

    # ── upsert and read-back ──────────────────────────────────────────────────

    async def test_upsert_creates_row(self, uow) -> None:
        """Upserting a MetricRow inserts into fundamental_metrics."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_available_metrics

        instr_id = await self._make_instrument(uow)
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric="pe_ratio",
                value_numeric=Decimal("25.0"),
                value_text=None,
                period_type="SNAPSHOT",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        metrics = await query_available_metrics(session, instr_id)
        assert "pe_ratio" in metrics

    async def test_upsert_idempotent_updates_value(self, uow) -> None:
        """Re-upserting the same (instrument_id, as_of_date, metric, period_type)
        overwrites value_numeric (ON CONFLICT DO UPDATE)."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_timeseries

        instr_id = await self._make_instrument(uow)
        as_of = date(2024, 9, 30)

        def _row(value: Decimal) -> MetricRow:
            return MetricRow(
                instrument_id=instr_id,
                as_of_date=as_of,
                metric="pe_ratio",
                value_numeric=value,
                value_text=None,
                period_type="SNAPSHOT",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )

        await uow.fundamental_metrics.upsert_metrics([_row(Decimal("25.0"))])
        await uow.commit()

        await uow.fundamental_metrics.upsert_metrics([_row(Decimal("30.0"))])
        await uow.commit()

        session = uow.get_read_session()
        points = await query_timeseries(session, instr_id, "pe_ratio")
        # Exactly one row (no duplicate created)
        assert len(points) == 1
        assert points[0].value_numeric == Decimal("30.000000")

    # ── timeseries query ──────────────────────────────────────────────────────

    async def test_timeseries_returns_sorted_ascending(self, uow) -> None:
        """query_timeseries returns data points ordered by as_of_date ascending."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_timeseries

        instr_id = await self._make_instrument(uow)
        dates_values = [
            (date(2022, 12, 31), Decimal("20")),
            (date(2023, 12, 31), Decimal("22")),
            (date(2024, 9, 30), Decimal("25")),
        ]
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=d,
                metric="pe_ratio",
                value_numeric=v,
                value_text=None,
                period_type="ANNUAL",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )
            for d, v in dates_values
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        points = await query_timeseries(session, instr_id, "pe_ratio")
        assert len(points) == 3
        # Must be ascending
        for i in range(len(points) - 1):
            assert points[i].as_of_date < points[i + 1].as_of_date

    async def test_timeseries_order_desc_returns_most_recent_with_limit(self, uow) -> None:
        """order='desc' + limit=N returns the N MOST-RECENT points, not the oldest.

        Audit 2026-05-09 regression: prior to this fix the ``order`` argument
        was silently dropped by the read repository, so a UI sparkline asking
        for the 12 newest quarters received the 12 OLDEST instead — which for
        AAPL meant 1985-1988 pre-IPO data instead of the recent year.
        """
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_timeseries

        instr_id = await self._make_instrument(uow)
        # 5 fiscal years: 2020 → 2024. With limit=2 + order=desc we expect
        # only 2023 and 2024 (re-sorted ASC for rendering).
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(year, 12, 31),
                metric="revenue",
                value_numeric=Decimal(str(year)),
                value_text=None,
                period_type="ANNUAL",
                section="income_statement",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )
            for year in (2020, 2021, 2022, 2023, 2024)
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        # order=desc + limit=2 → 2023 + 2024
        points = await query_timeseries(session, instr_id, "revenue", limit=2, order="desc")
        assert len(points) == 2
        # Always returned ASC by date so callers can render left→right
        assert points[0].as_of_date == date(2023, 12, 31)
        assert points[1].as_of_date == date(2024, 12, 31)

        # order=asc + limit=2 → 2020 + 2021 (the original / now-explicit behaviour)
        points = await query_timeseries(session, instr_id, "revenue", limit=2, order="asc")
        assert len(points) == 2
        assert points[0].as_of_date == date(2020, 12, 31)
        assert points[1].as_of_date == date(2021, 12, 31)

    async def test_timeseries_respects_start_date(self, uow) -> None:
        """query_timeseries with start_date excludes earlier rows."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_timeseries

        instr_id = await self._make_instrument(uow)
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2022, 12, 31),
                metric="revenue",
                value_numeric=Decimal("100"),
                value_text=None,
                period_type="ANNUAL",
                section="income_statements",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2023, 12, 31),
                metric="revenue",
                value_numeric=Decimal("120"),
                value_text=None,
                period_type="ANNUAL",
                section="income_statements",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        points = await query_timeseries(session, instr_id, "revenue", start_date=date(2023, 1, 1))
        assert len(points) == 1
        assert points[0].as_of_date == date(2023, 12, 31)

    async def test_timeseries_respects_end_date(self, uow) -> None:
        """query_timeseries with end_date excludes later rows."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_timeseries

        instr_id = await self._make_instrument(uow)
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2023, 12, 31),
                metric="revenue",
                value_numeric=Decimal("120"),
                value_text=None,
                period_type="ANNUAL",
                section="income_statements",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric="revenue",
                value_numeric=Decimal("150"),
                value_text=None,
                period_type="ANNUAL",
                section="income_statements",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        points = await query_timeseries(session, instr_id, "revenue", end_date=date(2023, 12, 31))
        assert len(points) == 1
        assert points[0].as_of_date == date(2023, 12, 31)

    # ── screening query ───────────────────────────────────────────────────────

    async def test_screen_uses_latest_date_per_metric(self, uow) -> None:
        """Screening uses the most recent as_of_date per instrument per metric."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import ScreenFilter, query_screen

        instr_id = await self._make_instrument(uow)
        # Two dates; only the later one should qualify the screen filter
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2023, 12, 31),
                metric="pe_ratio",
                value_numeric=Decimal("50"),  # high → would fail max=20
                value_text=None,
                period_type="ANNUAL",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric="pe_ratio",
                value_numeric=Decimal("15"),  # low → passes max=20
                value_text=None,
                period_type="ANNUAL",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        results, _total = await query_screen(session, [ScreenFilter(metric="pe_ratio", max_value=20.0)])
        instrument_ids = [r.instrument_id for r in results]
        assert instr_id in instrument_ids

    async def test_screen_and_logic_requires_all_filters(self, uow) -> None:
        """Instrument must satisfy ALL filters (AND logic)."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import ScreenFilter, query_screen

        instr_id = await self._make_instrument(uow)
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric="pe_ratio",
                value_numeric=Decimal("15"),
                value_text=None,
                period_type="SNAPSHOT",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric="roe_ttm",
                value_numeric=Decimal("0.05"),  # ROE too low → fails min=0.15
                value_text=None,
                period_type="SNAPSHOT",
                section="highlights",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            ),
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        # Both pe_ratio ≤ 20 AND roe_ttm ≥ 0.15 — instrument fails the second
        results, _total = await query_screen(
            session,
            [
                ScreenFilter(metric="pe_ratio", max_value=20.0),
                ScreenFilter(metric="roe_ttm", min_value=0.15),
            ],
        )
        instrument_ids = [r.instrument_id for r in results]
        assert instr_id not in instrument_ids

    # ── available metrics ─────────────────────────────────────────────────────

    async def test_available_metrics_returns_distinct_names(self, uow) -> None:
        """query_available_metrics returns all distinct metric names for an instrument."""
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from market_data.infrastructure.db.metric_extractor import MetricRow
        from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_available_metrics

        instr_id = await self._make_instrument(uow)
        rows = [
            MetricRow(
                instrument_id=instr_id,
                as_of_date=date(2024, 9, 30),
                metric=metric,
                value_numeric=Decimal("1"),
                value_text=None,
                period_type="SNAPSHOT",
                section="valuation_ratios",
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )
            for metric in ["pe_ratio", "pb_ratio", "enterprise_value"]
        ]
        await uow.fundamental_metrics.upsert_metrics(rows)
        await uow.commit()

        session = uow.get_read_session()
        metrics = await query_available_metrics(session, instr_id)
        assert set(metrics) == {"pe_ratio", "pb_ratio", "enterprise_value"}
