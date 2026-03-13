"""Performance benchmarks for the market-data service.

Measures:
- Bulk OHLCV upsert throughput (rows/second)
- Single-instrument OHLCV range query latency
- Quote upsert + read-back latency
- TimescaleDB hypertable chunk query (large date range)

All benchmarks are marked ``slow`` and ``integration``.
Run with:
    cd services/market-data && make test -- tests/integration/test_benchmarks.py -m "integration and slow" -v -s
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_BULK_ROWS = 500  # rows per benchmark run
_LATENCY_WARMUP = 3  # warmup iterations discarded


# ── helpers ───────────────────────────────────────────────────────────────────


async def _make_instrument(uow) -> str:
    from market_data.domain.entities import Instrument, Security

    sec = Security(name="Benchmark Corp")
    await uow.securities.upsert(sec)
    instr = Instrument(security_id=sec.id, symbol="BNCHMRK", exchange="XNAS")
    created = await uow.instruments.upsert(instr)
    await uow.commit()
    return created.id


def _make_bars(instrument_id: str, count: int) -> list:
    from market_data.domain.entities import OHLCVBar
    from market_data.domain.enums import Timeframe
    from market_data.domain.value_objects import ProviderPriority

    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        OHLCVBar(
            instrument_id=instrument_id,
            timeframe=Timeframe.ONE_DAY,
            bar_date=base + timedelta(days=i),
            open=Decimal("100.00"),
            high=Decimal("105.00"),
            low=Decimal("98.00"),
            close=Decimal("103.00"),
            volume=100_000 + i,
            provider_priority=ProviderPriority(provider="polygon", priority=100),
        )
        for i in range(count)
    ]


# ── benchmarks ───────────────────────────────────────────────────────────────


class TestBulkUpsertThroughput:
    async def test_bulk_upsert_500_bars(self, uow) -> None:
        """Bulk-upsert 500 OHLCV bars and report rows/second."""
        instr_id = await _make_instrument(uow)
        bars = _make_bars(instr_id, _BULK_ROWS)

        start = time.perf_counter()
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()
        elapsed = time.perf_counter() - start

        throughput = _BULK_ROWS / elapsed
        print(f"\n[benchmark] bulk_upsert {_BULK_ROWS} rows: {elapsed:.3f}s  ({throughput:.0f} rows/s)")

        # Sanity: should complete within 10 seconds even on slow CI
        assert elapsed < 10.0, f"bulk_upsert too slow: {elapsed:.2f}s for {_BULK_ROWS} rows"

    async def test_bulk_upsert_idempotent_second_pass(self, uow) -> None:
        """Re-upserting the same 100 bars (same priority) should be fast."""
        instr_id = await _make_instrument(uow)
        bars = _make_bars(instr_id, 100)

        # First pass
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()

        # Second pass (same rows)
        start = time.perf_counter()
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()
        elapsed = time.perf_counter() - start

        print(f"\n[benchmark] idempotent re-upsert 100 rows: {elapsed:.3f}s")
        assert elapsed < 5.0


class TestQueryLatency:
    async def test_range_query_latency(self, uow) -> None:
        """Range query over 500 rows should return in under 2 seconds."""
        from datetime import date

        from market_data.domain.enums import Timeframe

        instr_id = await _make_instrument(uow)
        bars = _make_bars(instr_id, _BULK_ROWS)
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()

        start = time.perf_counter()
        results = await uow.ohlcv.find_by_instrument_timeframe_range(
            instr_id,
            Timeframe.ONE_DAY,
            date(2020, 1, 1),
            date(2021, 5, 15),  # covers all 500 rows
        )
        elapsed = time.perf_counter() - start

        print(f"\n[benchmark] range_query ({len(results)} rows): {elapsed:.3f}s")
        assert len(results) == _BULK_ROWS
        assert elapsed < 2.0

    async def test_quote_upsert_and_read_latency(self, uow) -> None:
        """Single quote upsert + read-back round-trip under 500ms."""
        from market_data.domain.entities import Instrument, Quote, Security

        sec = Security(name="Quote Bench Corp")
        await uow.securities.upsert(sec)
        instr = Instrument(security_id=sec.id, symbol="QBENCH", exchange="XNAS")
        created_instr = await uow.instruments.upsert(instr)
        await uow.commit()

        quote = Quote(
            instrument_id=created_instr.id,
            bid=Decimal("150.00"),
            ask=Decimal("150.50"),
            last=Decimal("150.25"),
            volume=1000,
            timestamp=datetime.now(tz=UTC),
        )

        start = time.perf_counter()
        await uow.quotes.upsert(quote)
        await uow.commit()
        found = await uow.quotes.find_by_instrument(created_instr.id)
        elapsed = time.perf_counter() - start

        print(f"\n[benchmark] quote upsert+read: {elapsed:.3f}s")
        assert found is not None
        assert elapsed < 0.5

    async def test_timescaledb_hypertable_date_range(self, uow) -> None:
        """Query across 2 hypertable chunks (monthly partitions) within 3s."""
        from datetime import date

        from market_data.domain.entities import Instrument, OHLCVBar, Security
        from market_data.domain.enums import Timeframe
        from market_data.domain.value_objects import ProviderPriority

        sec = Security(name="Hypertable Bench Corp")
        await uow.securities.upsert(sec)
        instr = Instrument(security_id=sec.id, symbol="HTBENCH", exchange="XNAS")
        created_instr = await uow.instruments.upsert(instr)
        await uow.commit()

        # 60 days across two calendar months (two TimescaleDB chunks)
        base = datetime(2023, 11, 1, tzinfo=UTC)
        bars = [
            OHLCVBar(
                instrument_id=created_instr.id,
                timeframe=Timeframe.ONE_DAY,
                bar_date=base + timedelta(days=i),
                open=Decimal("50.00"),
                high=Decimal("52.00"),
                low=Decimal("49.00"),
                close=Decimal("51.00"),
                volume=10_000 + i,
                provider_priority=ProviderPriority(provider="polygon", priority=100),
            )
            for i in range(60)
        ]
        await uow.ohlcv.bulk_upsert_with_priority(bars)
        await uow.commit()

        start = time.perf_counter()
        results = await uow.ohlcv.find_by_instrument_timeframe_range(
            created_instr.id,
            Timeframe.ONE_DAY,
            date(2023, 11, 1),
            date(2023, 12, 30),
        )
        elapsed = time.perf_counter() - start

        print(f"\n[benchmark] hypertable cross-chunk query ({len(results)} rows): {elapsed:.3f}s")
        assert len(results) == 60
        assert elapsed < 3.0
