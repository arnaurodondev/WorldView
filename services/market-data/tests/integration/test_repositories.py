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
