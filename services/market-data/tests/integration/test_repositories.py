"""Integration tests for all PostgreSQL repository adapters.

Covers:
- PgSecurityRepository  (4 tests)
- PgInstrumentRepository (6 tests)
- PgOHLCVRepository      (5 tests)
- PgQuoteRepository      (4 tests)

Total: 19 tests (all backed by real TimescaleDB container).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

    async def test_find_by_symbol_icase_prefers_nonempty_exchange(self, uow) -> None:
        """NFLX-duplicate-instrument regression (2026-07).

        Given two rows for the same symbol — a placeholder ``exchange=''``
        row and a real ``exchange='US'`` row — ``find_by_symbol_icase`` MUST
        deterministically return the real-exchange row, never the
        placeholder, regardless of insertion order. Before the fix,
        ``.first()`` with no ``ORDER BY`` returned whichever row Postgres
        happened to store first on disk — which was the stale placeholder in
        the live NFLX incident.
        """
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        # Insert the PLACEHOLDER row first (matches the live incident's
        # ordering: fundamentals-refresh created the placeholder a day
        # before regular ingestion created the canonical row).
        placeholder = Instrument(security_id=sec_id, symbol="DUPX", exchange="")
        await uow.instruments.upsert(placeholder)
        await uow.commit()

        canonical = Instrument(security_id=sec_id, symbol="DUPX", exchange="US")
        created_canonical = await uow.instruments.upsert(canonical)
        await uow.commit()

        found = await uow.instruments.find_by_symbol_icase("DUPX")
        assert found is not None
        assert found.id == created_canonical.id
        assert found.exchange == "US"

        # Case-insensitivity is preserved by the new ORDER BY.
        found_lower = await uow.instruments.find_by_symbol_icase("dupx")
        assert found_lower is not None
        assert found_lower.id == created_canonical.id

    async def test_find_by_symbol_icase_prefers_freshest_fundamentals(self, uow) -> None:
        """When both rows have a real exchange, the freshest row wins.

        Tie-break #2 (after "non-empty exchange"): most recent
        ``last_fundamentals_ingest_at``. This covers duplicates that are NOT
        the placeholder-exchange pattern (e.g. a historical dual-listing
        cleanup), so the resolver still picks the row with the most current
        data rather than an arbitrary one.
        """
        from market_data.domain.entities import Instrument

        sec_id = await self._make_security(uow)
        stale = Instrument(security_id=sec_id, symbol="DUPY", exchange="XNAS")
        created_stale = await uow.instruments.upsert(stale)
        await uow.commit()
        await uow.instruments.touch_fundamentals_ingest_at(created_stale.id, datetime(2026, 3, 31, tzinfo=UTC))
        await uow.commit()

        # A second row for the SAME symbol under a DIFFERENT exchange (the
        # constraint is on (symbol, exchange), so this insert succeeds
        # distinctly — mirrors how the real duplicate came to exist).
        fresh = Instrument(security_id=sec_id, symbol="DUPY", exchange="XLON")
        created_fresh = await uow.instruments.upsert(fresh)
        await uow.commit()
        await uow.instruments.touch_fundamentals_ingest_at(created_fresh.id, datetime(2026, 7, 22, tzinfo=UTC))
        await uow.commit()

        found = await uow.instruments.find_by_symbol_icase("DUPY")
        assert found is not None
        assert found.id == created_fresh.id


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

    async def test_bulk_upsert_within_batch_duplicate_keys_no_cardinality_error(self, uow) -> None:
        """A single batch carrying DUPLICATE conflict keys must upsert cleanly.

        Regression for the crash-loop: overlapping crypto backfill/replay windows
        published the same (instrument_id, timeframe, bar_date) twice in one
        batch, so the bulk ``ON CONFLICT DO UPDATE`` raised
        ``CardinalityViolationError: ON CONFLICT DO UPDATE command cannot affect
        row a second time`` — crash-looping the ohlcv-consumer 2_686x. The repo
        now dedupes by conflict key first, keeping the highest-priority (tie →
        last) row, so this batch lands a single bar with the winning value.
        """
        from datetime import date

        from market_data.domain.entities import OHLCVBar
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        instr_id = await self._make_instrument(uow)
        bar_date = _utc(2026, 6, 19)

        def _bar(close: int, priority: int, source: str) -> OHLCVBar:
            return OHLCVBar(
                instrument_id=instr_id,
                timeframe=Timeframe.ONE_MIN,
                bar_date=bar_date,
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=10,
                source=source,
                provider_priority=ProviderPriority(provider=source, priority=priority),
            )

        # Three rows, SAME conflict key, in one batch. Highest priority (300) wins.
        await uow.ohlcv.bulk_upsert_with_priority(
            [
                _bar(close=111, priority=80, source="yahoo"),
                _bar(close=333, priority=300, source="polygon"),  # winner
                _bar(close=222, priority=80, source="yahoo"),
            ]
        )
        await uow.commit()

        results = await uow.ohlcv.find_by_instrument_timeframe_range(
            instr_id, Timeframe.ONE_MIN, date(2026, 6, 19), date(2026, 6, 19)
        )
        # Exactly one row stored (dedup), carrying the highest-priority winner.
        assert len(results) == 1
        assert results[0].close == Decimal(333)


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


# ── Prediction market repository — free-text query ESCAPE (BP-712) ────────────


class TestPgPredictionMarketRepositoryQuery:
    """Real-DB regression tests for the free-text ILIKE ESCAPE clause (BP-712).

    Runs the ``list_markets`` free-text branch against a live TimescaleDB
    container (``standard_conforming_strings=on`` by default) — the exact
    condition under which the old two-backslash ESCAPE literal raised
    asyncpg ``InvalidEscapeSequenceError`` → HTTP 500.
    """

    @staticmethod
    async def _cleanup(uow) -> None:
        # prediction_markets is not in the conftest TRUNCATE list, so remove the
        # rows this test inserted to keep the shared session state clean.
        from sqlalchemy import text as _sql_text

        await uow.get_write_session().execute(_sql_text("DELETE FROM prediction_markets"))
        await uow.commit()

    @staticmethod
    def _market(market_id: str, question: str) -> object:
        from market_data.domain.entities import PredictionMarket

        return PredictionMarket(market_id=market_id, question=question)

    async def test_free_text_query_filters_without_escape_error(self, uow) -> None:
        """A free-text query executes cleanly and filters on question text."""
        try:
            await uow.prediction_markets.upsert(
                self._market("mkt-election", "US presidential election outcome 2024"),
            )
            await uow.prediction_markets.upsert(
                self._market("mkt-sports", "Will the home team win the final"),
            )
            await uow.commit()

            # Before the fix this raised InvalidEscapeSequenceError (HTTP 500).
            pairs, total = await uow.prediction_markets.list_markets(
                status=None,
                query="election",
                limit=10,
                offset=0,
            )

            assert total == 1
            assert len(pairs) == 1
            assert pairs[0][0].market_id == "mkt-election"
        finally:
            await self._cleanup(uow)

    async def test_percent_in_query_is_escaped_not_wildcard(self, uow) -> None:
        """A literal ``%`` in the query is escaped, not treated as a wildcard.

        Proves the single-backslash ESCAPE char is consistent with the
        ``safe_query`` metacharacter escaping: ``"win 50%"`` must match a
        literal ``50%`` substring only, so it does NOT match ``"win 50k"``.
        """
        try:
            await uow.prediction_markets.upsert(
                self._market("mkt-50k", "Will BTC win 50k this year"),
            )
            await uow.commit()

            # Pattern becomes `%win 50\%%` — the escaped % matches a literal %,
            # which "win 50k" does not contain → zero rows (not a wildcard hit).
            pairs, total = await uow.prediction_markets.list_markets(
                status=None,
                query="win 50%",
                limit=10,
                offset=0,
            )

            assert total == 0
            assert pairs == []
        finally:
            await self._cleanup(uow)

    async def test_multi_word_query_matches_out_of_order_tokens(self, uow) -> None:
        """R2 fix: a natural multi-word phrase matches on AND-ed tokens.

        The market question does not contain the query as a verbatim substring
        (word order differs, extra words in between), so the old whole-phrase
        ILIKE returned 0. Tokenised AND matching now finds it.
        """
        try:
            await uow.prediction_markets.upsert(
                self._market(
                    "mkt-dem-2028",
                    "Who will win the 2028 Democratic presidential nomination?",
                ),
            )
            await uow.prediction_markets.upsert(
                self._market("mkt-gop-2028", "2028 Republican primary winner"),
            )
            await uow.commit()

            # "presidential nomination" is not a contiguous substring match test
            # here — both tokens appear (in order) but the key point is the query
            # phrase differs from the stored question; multi-token AND matches.
            pairs, total = await uow.prediction_markets.list_markets(
                status=None,
                query="Democratic 2028 nomination",
                limit=10,
                offset=0,
            )

            assert total == 1
            assert len(pairs) == 1
            assert pairs[0][0].market_id == "mkt-dem-2028"
        finally:
            await self._cleanup(uow)

    async def test_nonsense_multi_word_phrase_matches_nothing(self, uow) -> None:
        """A phrase whose tokens do not all co-occur in any question → 0 rows."""
        try:
            await uow.prediction_markets.upsert(
                self._market(
                    "mkt-dem-2028",
                    "Who will win the 2028 Democratic presidential nomination?",
                ),
            )
            await uow.commit()

            # "presidential" is present but "bitcoin" is not → AND fails.
            pairs, total = await uow.prediction_markets.list_markets(
                status=None,
                query="bitcoin presidential nomination",
                limit=10,
                offset=0,
            )

            assert total == 0
            assert pairs == []
        finally:
            await self._cleanup(uow)


class TestPgPredictionMarketSnapshotDenormalizationLive:
    """Real-DB end-to-end coverage for migration 048's write-path sync.

    Complements the mock-session unit tests in ``test_repositories.py``
    (unit) — those pin the exact SQL shape; these confirm the whole thing
    actually works against a real (TimescaleDB) Postgres: a snapshot write
    updates ``prediction_markets.last_snapshot_at`` /
    ``latest_volume_24h`` in the SAME transaction, ``list_markets`` reads the
    result back correctly (no LATERAL involved), and an out-of-order/older
    snapshot never regresses the denormalized columns.
    """

    @staticmethod
    async def _cleanup(uow) -> None:
        from sqlalchemy import text as _sql_text

        await uow.get_write_session().execute(_sql_text("DELETE FROM prediction_market_snapshots"))
        await uow.get_write_session().execute(_sql_text("DELETE FROM prediction_markets"))
        await uow.commit()

    @staticmethod
    def _market(market_id: str, question: str = "Will X happen?") -> object:
        from market_data.domain.entities import PredictionMarket

        return PredictionMarket(market_id=market_id, question=question)

    @staticmethod
    def _snapshot(market_id: str, snapshot_at, volume_24h) -> object:
        from market_data.domain.entities import PredictionMarketSnapshot

        return PredictionMarketSnapshot(
            market_id=market_id,
            snapshot_at=snapshot_at,
            outcomes_prices={"Yes": 0.6, "No": 0.4},
            source_event_id="evt-1",
            volume_24h=volume_24h,
        )

    async def test_single_snapshot_insert_denormalizes_onto_market_row(self, uow) -> None:
        """A single snapshot write updates last_snapshot_at + latest_volume_24h."""
        from sqlalchemy import text as _sql_text

        try:
            await uow.prediction_markets.upsert(self._market("mkt-denorm-1"))
            await uow.commit()

            snap = self._snapshot("mkt-denorm-1", datetime(2026, 4, 9, 12, tzinfo=UTC), Decimal("1234.56"))
            inserted = await uow.prediction_market_snapshots.insert_if_not_exists(snap)
            await uow.commit()

            assert inserted is True
            row = (
                await uow.get_read_session().execute(
                    _sql_text(
                        "SELECT latest_volume_24h, last_snapshot_at FROM prediction_markets WHERE market_id = :m"
                    ).bindparams(m="mkt-denorm-1")
                )
            ).fetchone()
            assert row.latest_volume_24h == Decimal("1234.5600")
            assert row.last_snapshot_at == datetime(2026, 4, 9, 12, tzinfo=UTC)

            # list_markets must surface the SAME value with no LATERAL — the
            # whole point of migration 048.
            pairs, total = await uow.prediction_markets.list_markets(status=None, query=None, limit=10, offset=0)
            assert total == 1
            assert pairs[0][1] == Decimal("1234.5600")
        finally:
            await self._cleanup(uow)

    async def test_out_of_order_snapshot_never_regresses_denormalized_columns(self, uow) -> None:
        """An older/late-arriving snapshot must not clobber the newer denormalized state.

        Kafka delivery is not globally ordered — a replay or a re-delivered
        older message must never regress last_snapshot_at/latest_volume_24h
        to a stale value.
        """
        from sqlalchemy import text as _sql_text

        try:
            await uow.prediction_markets.upsert(self._market("mkt-denorm-2"))
            await uow.commit()

            newer = self._snapshot("mkt-denorm-2", datetime(2026, 4, 9, 12, tzinfo=UTC), Decimal("900"))
            await uow.prediction_market_snapshots.insert_if_not_exists(newer)
            await uow.commit()

            older = self._snapshot("mkt-denorm-2", datetime(2026, 4, 9, 10, tzinfo=UTC), Decimal("100"))
            await uow.prediction_market_snapshots.insert_if_not_exists(older)
            await uow.commit()

            row = (
                await uow.get_read_session().execute(
                    _sql_text(
                        "SELECT latest_volume_24h, last_snapshot_at FROM prediction_markets WHERE market_id = :m"
                    ).bindparams(m="mkt-denorm-2")
                )
            ).fetchone()
            # Must still reflect the NEWER snapshot, not the out-of-order older one.
            assert row.latest_volume_24h == Decimal("900.0000")
            assert row.last_snapshot_at == datetime(2026, 4, 9, 12, tzinfo=UTC)
        finally:
            await self._cleanup(uow)

    async def test_bulk_insert_denormalizes_using_newest_snapshot_per_market(self, uow) -> None:
        """bulk_insert_if_not_exists syncs each market using its newest snapshot in the batch."""
        from sqlalchemy import text as _sql_text

        try:
            await uow.prediction_markets.upsert(self._market("mkt-bulk-a"))
            await uow.prediction_markets.upsert(self._market("mkt-bulk-b"))
            await uow.commit()

            snapshots = [
                self._snapshot("mkt-bulk-a", datetime(2026, 4, 9, 10, tzinfo=UTC), Decimal("100")),
                self._snapshot("mkt-bulk-a", datetime(2026, 4, 9, 12, tzinfo=UTC), Decimal("500")),  # newest for A
                self._snapshot("mkt-bulk-b", datetime(2026, 4, 9, 9, tzinfo=UTC), Decimal("42")),
            ]
            inserted = await uow.prediction_market_snapshots.bulk_insert_if_not_exists(snapshots)
            await uow.commit()

            assert inserted == 3
            rows = {
                r.market_id: r
                for r in (
                    await uow.get_read_session().execute(
                        _sql_text(
                            "SELECT market_id, latest_volume_24h, last_snapshot_at FROM prediction_markets "
                            "WHERE market_id IN ('mkt-bulk-a', 'mkt-bulk-b')"
                        )
                    )
                ).fetchall()
            }
            assert rows["mkt-bulk-a"].latest_volume_24h == Decimal("500.0000")
            assert rows["mkt-bulk-a"].last_snapshot_at == datetime(2026, 4, 9, 12, tzinfo=UTC)
            assert rows["mkt-bulk-b"].latest_volume_24h == Decimal("42.0000")
        finally:
            await self._cleanup(uow)

    async def test_list_markets_volume_window_days_degrades_stale_market_to_null(self, uow) -> None:
        """Real-DB coverage for the ``volume_window_days`` CASE (migration 048).

        Regression guard tied to a review finding on migration 048's backfill
        (a ``COALESCE`` bug that would have left ``last_snapshot_at`` stale for
        already-synced markets, silently breaking this exact CASE in
        production). This test exercises the SAME code path end-to-end
        against a real Postgres: a market whose ``last_snapshot_at`` falls
        OUTSIDE the window must report ``volume_24h = None`` (sorts last),
        while a market whose ``last_snapshot_at`` is inside the window must
        keep reporting its real ``latest_volume_24h``. The unit tests
        (``TestPredictionMarketListVolumeWindow``) only pin the emitted SQL
        text against a mocked session — this proves the SQL is also
        semantically correct against a real database.
        """
        from sqlalchemy import text as _sql_text

        try:
            await uow.prediction_markets.upsert(self._market("mkt-stale"))
            await uow.prediction_markets.upsert(self._market("mkt-fresh"))
            await uow.commit()

            now = datetime.now(UTC)
            stale_snapshot_at = now - timedelta(days=45)  # outside a 30-day window
            fresh_snapshot_at = now - timedelta(hours=1)  # inside a 30-day window

            await uow.prediction_market_snapshots.insert_if_not_exists(
                self._snapshot("mkt-stale", stale_snapshot_at, Decimal("777"))
            )
            await uow.prediction_market_snapshots.insert_if_not_exists(
                self._snapshot("mkt-fresh", fresh_snapshot_at, Decimal("888"))
            )
            await uow.commit()

            # Sanity: the denormalized columns themselves are populated
            # correctly regardless of the window (the window only affects
            # what list_markets() SURFACES, not what's stored).
            row = (
                await uow.get_read_session().execute(
                    _sql_text(
                        "SELECT market_id, latest_volume_24h FROM prediction_markets WHERE market_id = 'mkt-stale'"
                    )
                )
            ).fetchone()
            assert row.latest_volume_24h == Decimal("777.0000")

            pairs, total = await uow.prediction_markets.list_markets(
                status=None,
                query=None,
                limit=10,
                offset=0,
                volume_window_days=30,
            )
            assert total == 2
            volume_by_market = {m.market_id: vol for m, vol in pairs}
            # Outside the window: volume degrades to None (sorts last) even
            # though latest_volume_24h is populated in the table.
            assert volume_by_market["mkt-stale"] is None
            # Inside the window: the real denormalized volume is surfaced.
            assert volume_by_market["mkt-fresh"] == Decimal("888.0000")
        finally:
            await self._cleanup(uow)


# ── PLAN-0056 A2: prediction deeper-stream repos (real TimescaleDB) ────────────
#
# These tables are NOT in the conftest TRUNCATE list, so each test cleans up the
# rows it inserts in a try/finally (same pattern as the free-text query tests).


class TestPgPredictionStreamRepositories:
    @staticmethod
    async def _cleanup(uow) -> None:
        from sqlalchemy import text as _sql_text

        session = uow.get_write_session()
        for tbl in (
            "prediction_market_prices",
            "prediction_market_trades",
            "prediction_market_oi",
            "prediction_events",
        ):
            await session.execute(_sql_text(f"DELETE FROM {tbl}"))  # noqa: S608 — tbl is a hardcoded constant list
        await uow.commit()

    async def test_price_insert_dedup_and_list(self, uow) -> None:
        from market_data.domain.entities import PredictionMarketPrice

        try:
            p1 = PredictionMarketPrice(
                market_id="mkt-p",
                token_id="tok-a",
                interval="1h",
                window_start_ts=_utc(2026, 1, 1),
                price=Decimal("0.40"),
            )
            assert await uow.prediction_market_prices.insert_if_not_exists(p1) is True
            # Same natural key → conflict → False, no duplicate row.
            assert await uow.prediction_market_prices.insert_if_not_exists(p1) is False
            await uow.commit()

            rows = await uow.prediction_market_prices.list_prices(
                "mkt-p", token_id="tok-a", interval="1h", from_dt=None, to_dt=None, limit=10
            )
            assert len(rows) == 1
            assert rows[0].price == Decimal("0.400000")
        finally:
            await self._cleanup(uow)

    async def test_price_bulk_insert_counts_and_orders_desc(self, uow) -> None:
        from market_data.domain.entities import PredictionMarketPrice

        try:
            prices = [
                PredictionMarketPrice(
                    market_id="mkt-p",
                    token_id="tok-a",
                    interval="1h",
                    window_start_ts=_utc(2026, 1, d),
                    price=Decimal(f"0.{d:02d}"),
                )
                for d in (1, 2, 3)
            ]
            inserted = await uow.prediction_market_prices.bulk_insert(prices)
            await uow.commit()
            assert inserted == 3

            # Re-inserting the same 3 + 1 new → only the new one counts.
            more = [
                *prices,
                PredictionMarketPrice(
                    market_id="mkt-p",
                    token_id="tok-a",
                    interval="1h",
                    window_start_ts=_utc(2026, 1, 4),
                    price=Decimal("0.44"),
                ),
            ]
            assert await uow.prediction_market_prices.bulk_insert(more) == 1
            await uow.commit()

            rows = await uow.prediction_market_prices.list_prices(
                "mkt-p",
                token_id=None,
                interval=None,
                from_dt=_utc(2026, 1, 2),
                to_dt=_utc(2026, 1, 3),
                limit=10,
            )
            # Date-range filter → only Jan 2 and Jan 3, newest first.
            assert [r.window_start_ts.day for r in rows] == [3, 2]
        finally:
            await self._cleanup(uow)

    async def test_trade_insert_dedup_and_list_since(self, uow) -> None:
        from market_data.domain.entities import PredictionMarketTrade

        try:
            t1 = PredictionMarketTrade(
                market_id="mkt-t",
                trade_id="trd-1",
                token_id="tok-a",
                price=Decimal("0.5"),
                side="buy",
                ts=_utc(2026, 1, 1),
            )
            t2 = PredictionMarketTrade(
                market_id="mkt-t",
                trade_id="trd-2",
                token_id="tok-a",
                price=Decimal("0.6"),
                side="sell",
                ts=_utc(2026, 1, 5),
            )
            assert await uow.prediction_market_trades.bulk_insert([t1, t2]) == 2
            # Dedup on (market_id, trade_id, ts).
            assert await uow.prediction_market_trades.insert_if_not_exists(t1) is False
            await uow.commit()

            recent = await uow.prediction_market_trades.list_trades("mkt-t", since=_utc(2026, 1, 3), limit=10)
            assert [t.trade_id for t in recent] == ["trd-2"]
        finally:
            await self._cleanup(uow)

    async def test_oi_upsert_overwrites_and_get_latest(self, uow) -> None:
        from datetime import date

        from market_data.domain.entities import PredictionMarketOI

        try:
            await uow.prediction_market_oi.upsert(
                PredictionMarketOI("mkt-o", date(2026, 1, 1), Decimal("100"), Decimal("10"))
            )
            # Same (market_id, snapshot_date) → overwrite money fields.
            await uow.prediction_market_oi.upsert(
                PredictionMarketOI("mkt-o", date(2026, 1, 1), Decimal("250"), Decimal("25"))
            )
            await uow.prediction_market_oi.upsert(PredictionMarketOI("mkt-o", date(2026, 1, 2), Decimal("300"), None))
            await uow.commit()

            rows = await uow.prediction_market_oi.list_oi("mkt-o", from_date=None, to_date=None, limit=10)
            assert len(rows) == 2  # two distinct days, not three inserts
            by_day = {r.snapshot_date: r for r in rows}
            assert by_day[date(2026, 1, 1)].total_oi_usd == Decimal("250.0000")

            latest = await uow.prediction_market_oi.get_latest("mkt-o")
            assert latest is not None
            assert latest.snapshot_date == date(2026, 1, 2)
            assert latest.total_volume_24h_usd is None
        finally:
            await self._cleanup(uow)

    async def test_event_upsert_find_and_list(self, uow) -> None:
        from market_data.domain.entities import PredictionEvent

        try:
            await uow.prediction_events.upsert(
                PredictionEvent(event_id="evt-1", name="Election", category="politics", market_count=2)
            )
            # Upsert on event_id → update metadata (market_count grows).
            await uow.prediction_events.upsert(
                PredictionEvent(event_id="evt-1", name="Election 2028", category="politics", market_count=5)
            )
            await uow.prediction_events.upsert(
                PredictionEvent(event_id="evt-2", name="World Cup", category="sports", market_count=1)
            )
            await uow.commit()

            found = await uow.prediction_events.find_by_event_id("evt-1")
            assert found is not None
            assert found.name == "Election 2028"
            assert found.market_count == 5

            events, total = await uow.prediction_events.list_events(limit=10, offset=0)
            assert total == 2
            assert {e.event_id for e in events} == {"evt-1", "evt-2"}
            assert await uow.prediction_events.find_by_event_id("missing") is None
        finally:
            await self._cleanup(uow)
