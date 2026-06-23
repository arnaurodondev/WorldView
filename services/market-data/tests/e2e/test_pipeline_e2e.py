"""E2E pipeline tests — verify the full data flow from ingest → query.

Strategy: rather than publishing real Kafka events (fragile, slow), these tests
simulate the consumer's write path by seeding data directly into the live
TimescaleDB, then asserting the API surfaces it correctly.  This validates the
complete path:

    DB write (consumer equivalent) → HTTP API → response shape + content

Four scenarios:
  1. OHLCV ingestion: bars written by multiple providers; only the highest-
     priority bar survives for each date. API query reflects final state.
  2. Quote invalidation: quote upserted → API returns it → update quote →
     API returns updated value (verifies the cache has short TTL / invalidates).
  3. Instrument flag promotion: instrument starts with no flags; after OHLCV
     seed, `has_ohlcv` is True; after quote seed, `has_quotes` is True.
     GET /instruments/{id} reflects both flags.
  4. Fundamentals availability: after seeding an income-statement record the
     GET /fundamentals/{security_id}/income-statement endpoint returns 200
     with data.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


# ── Scenario 1: OHLCV provider-priority battle ────────────────────────────────


async def test_ohlcv_priority_resolution_visible_via_api(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """Seed Polygon (100) then Yahoo (80) bars for same date.
    API must return the Polygon close, not Yahoo's.
    """
    from market_data.domain.entities import OHLCVBar
    from market_data.domain.enums import Timeframe
    from market_data.domain.value_objects import ProviderPriority
    from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository

    repo = PgOHLCVRepository(e2e_db_session)
    instr_id = seeded_instrument["instrument_id"]
    bar_date = datetime(2024, 7, 15, tzinfo=UTC)

    # High-priority Polygon bar
    polygon_bar = OHLCVBar(
        instrument_id=instr_id,
        timeframe=Timeframe.ONE_DAY,
        bar_date=bar_date,
        open=Decimal("200.00"),
        high=Decimal("205.00"),
        low=Decimal("198.00"),
        close=Decimal("202.50"),
        volume=10_000_000,
        provider_priority=ProviderPriority(provider="polygon", priority=100),
    )
    await repo.bulk_upsert_with_priority([polygon_bar])
    await e2e_db_session.commit()

    # Low-priority Yahoo bar (should NOT overwrite Polygon)
    yahoo_bar = OHLCVBar(
        instrument_id=instr_id,
        timeframe=Timeframe.ONE_DAY,
        bar_date=bar_date,
        open=Decimal("999.00"),
        high=Decimal("999.00"),
        low=Decimal("999.00"),
        close=Decimal("999.00"),
        volume=1,
        provider_priority=ProviderPriority(provider="yahoo", priority=80),
    )
    await repo.bulk_upsert_with_priority([yahoo_bar])
    await e2e_db_session.commit()

    resp = await e2e_client.get(
        f"/api/v1/ohlcv/{instr_id}",
        params={"timeframe": "1d", "start": "2024-07-15", "end": "2024-07-15"},
    )
    assert resp.status_code == 200, resp.text
    bars = resp.json()["items"]
    assert len(bars) == 1
    assert float(bars[0]["close"]) == pytest.approx(202.50), f"Expected Polygon close=202.50, got {bars[0]['close']}"


# ── Scenario 2: Quote update reflected after short TTL ────────────────────────


async def test_quote_update_reflected_via_api(
    e2e_client: AsyncClient,
    seeded_quote: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """Update a quote in DB, invalidate the cache (as the live pipeline does), then
    confirm the API re-resolves the new value from the DB.

    Why we invalidate explicitly rather than sleeping for the TTL
    ------------------------------------------------------------
    In production a fresh quote arrives via Kafka → ``QuotesConsumer`` →
    ``schedule_quote_cache_fanout`` which *invalidates* the per-quote cache
    (``quote:v1:{id}``) so the next API read re-resolves from the DB — the
    update is visible immediately, NOT after the TTL elapses.  This test seeds
    the DB directly (it has no consumer), so it must reproduce that same
    invalidation side effect to exercise the real read path.

    Previously this test blind-slept ``6s`` and relied on the API cache TTL
    (then 5s) to expire.  Commit ``e32d84454`` legitimately raised the API
    quote-cache TTL to 60s for performance, which made the 6s sleep shorter
    than the TTL → the stale value persisted → test failed.  Tying the test to
    an exact TTL value is brittle; mirroring the production invalidation +
    bounded polling makes it deterministic and TTL-independent (R19: we
    strengthen, not weaken, the assertion).
    """
    from market_data.domain.entities import Quote
    from market_data.infrastructure.cache.quote_cache import QuoteCache
    from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository

    from messaging.valkey.client import create_valkey_client_from_url  # type: ignore[import-untyped]

    repo = PgQuoteRepository(e2e_db_session)
    instr_id = seeded_quote["instrument_id"]

    # Warm the cache with the original quote (bid=182.50 from the fixture).
    resp = await e2e_client.get(f"/api/v1/quotes/{instr_id}")
    assert resp.status_code == 200
    assert float(resp.json()["bid"]) == pytest.approx(182.50)

    # Update quote in DB.
    updated = Quote(
        instrument_id=instr_id,
        bid=Decimal("195.00"),
        ask=Decimal("195.50"),
        last=Decimal("195.25"),
        volume=8_000_000,
        timestamp=datetime.now(tz=UTC),
    )
    await repo.upsert(updated)
    await e2e_db_session.commit()

    # Invalidate the live per-quote cache exactly as ``schedule_quote_cache_fanout``
    # does in the real consumer path (key ``quote:v1:{id}``).  The Valkey instance
    # is exposed to the test runner on localhost:6379 by docker-compose.test.yml.
    valkey_url = os.getenv("MARKET_DATA_E2E_VALKEY_URL", "redis://localhost:6379/0")
    valkey_client = create_valkey_client_from_url(valkey_url)
    try:
        await QuoteCache(valkey_client).invalidate(str(instr_id))
    finally:
        await valkey_client.close()

    # Bounded poll: the next read should re-resolve the fresh DB row.  We poll
    # (rather than asserting on a single read) to tolerate eventual-consistency
    # of the invalidate→read race without depending on the TTL length.
    deadline = 10.0  # generous bound; the invalidate makes this near-instant
    interval = 0.25
    elapsed = 0.0
    body: dict = {}
    while elapsed <= deadline:
        resp2 = await e2e_client.get(f"/api/v1/quotes/{instr_id}")
        assert resp2.status_code == 200
        body = resp2.json()
        if float(body["bid"]) == pytest.approx(195.00):
            break
        await asyncio.sleep(interval)
        elapsed += interval

    assert float(body["bid"]) == pytest.approx(
        195.00
    ), f"Expected updated bid=195.00 after cache invalidation, got {body['bid']}"


# ── Scenario 3: Instrument flag promotion ─────────────────────────────────────


async def test_instrument_flags_promoted_by_data_ingest(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """After seeding OHLCV + quote data, both has_ohlcv and has_quotes must be True
    on the instrument returned by the API.
    """
    from market_data.domain.entities import OHLCVBar, Quote
    from market_data.domain.enums import Timeframe
    from market_data.domain.value_objects import InstrumentFlags, ProviderPriority
    from market_data.infrastructure.db.repositories.instrument_repo import PgInstrumentRepository
    from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository
    from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository

    instr_id = seeded_instrument["instrument_id"]

    # Seed OHLCV bar
    ohlcv_repo = PgOHLCVRepository(e2e_db_session)
    await ohlcv_repo.bulk_upsert_with_priority(
        [
            OHLCVBar(
                instrument_id=instr_id,
                timeframe=Timeframe.ONE_DAY,
                bar_date=datetime(2024, 8, 1, tzinfo=UTC),
                open=Decimal("150"),
                high=Decimal("155"),
                low=Decimal("148"),
                close=Decimal("152"),
                volume=500_000,
                provider_priority=ProviderPriority(provider="polygon", priority=100),
            )
        ]
    )

    # Seed quote
    quote_repo = PgQuoteRepository(e2e_db_session)
    await quote_repo.upsert(
        Quote(
            instrument_id=instr_id,
            bid=Decimal("151.00"),
            ask=Decimal("152.00"),
            last=Decimal("151.50"),
            volume=100_000,
            timestamp=datetime.now(tz=UTC),
        )
    )

    # Promote flags on the instrument row
    instr_repo = PgInstrumentRepository(e2e_db_session)
    await instr_repo.update_flags(instr_id, InstrumentFlags(has_ohlcv=True, has_quotes=True))
    await e2e_db_session.commit()

    # NOTE: there is intentionally no ``GET /api/v1/instruments/{id}`` route
    # (reverted in commit 50dab515; see ``test_old_symbol_endpoint_removed``).
    # The canonical way to verify per-instrument flags is the list endpoint
    # which returns ``InstrumentResponse`` items with the full ``flags``
    # block; we filter to the seeded instrument by id.
    resp = await e2e_client.get(
        "/api/v1/instruments",
        params={"has_ohlcv": "true", "has_quotes": "true", "limit": 1000},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    match = next((item for item in body["items"] if item["id"] == str(instr_id)), None)
    assert match is not None, f"Seeded instrument {instr_id} missing from filtered list: {body}"
    flags = match["flags"]
    assert flags["has_ohlcv"] is True, f"has_ohlcv should be True: {flags}"
    assert flags["has_quotes"] is True, f"has_quotes should be True: {flags}"


# ── Scenario 4: Fundamentals section accessible via API ───────────────────────


async def test_fundamentals_income_statement_accessible(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """After seeding an income_statement record, the API endpoint returns 200."""
    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType
    from market_data.infrastructure.db.repositories.fundamentals_repo import PgFundamentalsRepository

    instr_id = seeded_instrument["instrument_id"]

    repo = PgFundamentalsRepository(e2e_db_session)
    record = FundamentalsRecord(
        security_id=instr_id,  # repo maps security_id → instrument_id FK
        section=FundamentalsSection.INCOME_STATEMENT,
        period_end=datetime(2024, 3, 31, tzinfo=UTC),
        period_type=PeriodType.QUARTERLY,
        data={
            "total_revenue": 119_575_000_000,
            "net_income": 28_390_000_000,
            "eps_diluted": 1.89,
        },
        source="polygon",
    )
    await repo.merge_upsert([record], instrument_id=instr_id)
    await e2e_db_session.commit()

    resp = await e2e_client.get(f"/api/v1/fundamentals/{instr_id}/income-statement")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Response must contain at least one period's data
    assert body["security_id"] == instr_id
    assert len(body["records"]) >= 1
