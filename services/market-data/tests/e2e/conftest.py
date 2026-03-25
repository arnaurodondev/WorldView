"""E2E test fixtures for the market-data service.

These tests run against the LIVE service started by:

    docker compose -f infra/compose/docker-compose.test.yml \
        --profile market-data-test up --build --wait

Stack:
  TimescaleDB (localhost:5433/market_data_db)
  Valkey      (localhost:6379)
  MinIO       (localhost:7480)
  Kafka       (localhost:9092)
  market-data API (localhost:8003)

The --wait flag guarantees the service is healthy before pytest runs, so
no skip logic or wait loops are required in the tests themselves.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

_BASE_URL = os.getenv("MARKET_DATA_E2E_BASE_URL", "http://localhost:8003")
_DB_URL = os.getenv(
    "MARKET_DATA_E2E_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/market_data_db",
)


# ── Session-scoped HTTP client ─────────────────────────────────────────────────


@pytest.fixture
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP client pointing at the live market-data service on localhost:8003."""
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac


# ── Function-scoped DB engine ──────────────────────────────────────────────────


@pytest.fixture
async def e2e_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Direct DB session for white-box assertions and test data seeding.
    
    Clears all tables before each test to ensure test isolation. Uses TRUNCATE
    at fixture setup to eliminate any leftover data from docker-compose tmpfs
    state or previous test runs.
    """
    engine = create_async_engine(_DB_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    
    # Clear all tables at START of test (not end) to ensure fresh slate
    # Use a fresh session for cleanup to avoid transaction state issues
    from sqlalchemy import text
    
    async with factory() as cleanup_session:
        await cleanup_session.execute(
            text(
                "TRUNCATE TABLE "
                "ohlcv_bars, quotes, "
                "income_statements, balance_sheets, "
                "highlights, company_profiles, institutional_holders, "
                "fund_holders, insider_transactions_snapshot, "
                "ingestion_events, failed_tasks, outbox_events, "
                "instruments, securities "
                "CASCADE"
            )
        )
        await cleanup_session.commit()
    
    # Now provide a fresh session for the test
    async with factory() as session:
        yield session
    
    await engine.dispose()


# ── Seeding helpers ───────────────────────────────────────────────────────────


@pytest.fixture
async def seeded_instrument(e2e_db_session: AsyncSession) -> dict:
    """Insert one Security + Instrument and return their IDs."""
    from market_data.domain.entities import Instrument, Security
    from market_data.infrastructure.db.repositories.instrument_repo import PgInstrumentRepository
    from market_data.infrastructure.db.repositories.security_repo import PgSecurityRepository

    sec_repo = PgSecurityRepository(e2e_db_session)
    instr_repo = PgInstrumentRepository(e2e_db_session)

    sec = Security(name="E2E Apple Inc.", figi="BBG000B9XRY4", isin="US0378331005")
    upserted_sec = await sec_repo.upsert(sec)
    # CRITICAL: Use the returned security from upsert, not the original
    # (upsert may return a different instance, e.g., with DB-assigned ID)
    await e2e_db_session.flush()  # Ensure security is written to DB

    instr = Instrument(security_id=upserted_sec.id, symbol="AAPL", exchange="XNAS")
    created_instr = await instr_repo.upsert(instr)
    await e2e_db_session.commit()

    return {
        "security_id": upserted_sec.id,
        "security_figi": upserted_sec.figi,
        "security_isin": upserted_sec.isin,
        "instrument_id": created_instr.id,
        "symbol": "AAPL",
        "exchange": "XNAS",
    }


@pytest.fixture
async def seeded_ohlcv(seeded_instrument: dict, e2e_db_session: AsyncSession) -> dict:
    """Insert 5 daily OHLCV bars for the seeded instrument."""
    from market_data.domain.entities import OHLCVBar
    from market_data.domain.enums import Timeframe
    from market_data.domain.value_objects import ProviderPriority
    from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository

    repo = PgOHLCVRepository(e2e_db_session)
    instr_id = seeded_instrument["instrument_id"]
    bars = [
        OHLCVBar(
            instrument_id=instr_id,
            timeframe=Timeframe.ONE_DAY,
            bar_date=datetime(2024, 6, d, tzinfo=UTC),
            open=Decimal("180.00"),
            high=Decimal("185.00"),
            low=Decimal("178.00"),
            close=Decimal(f"{182 + d}.00"),
            volume=1_000_000 * d,
            provider_priority=ProviderPriority(provider="polygon", priority=100),
        )
        for d in range(1, 6)
    ]
    await repo.bulk_upsert_with_priority(bars)
    await e2e_db_session.commit()
    return seeded_instrument


@pytest.fixture
async def seeded_quote(seeded_instrument: dict, e2e_db_session: AsyncSession) -> dict:
    """Insert one Quote for the seeded instrument."""
    from market_data.domain.entities import Quote
    from market_data.infrastructure.db.repositories.quote_repo import PgQuoteRepository

    repo = PgQuoteRepository(e2e_db_session)
    quote = Quote(
        instrument_id=seeded_instrument["instrument_id"],
        bid=Decimal("182.50"),
        ask=Decimal("183.00"),
        last=Decimal("182.75"),
        volume=5_000_000,
        timestamp=datetime.now(tz=UTC),
    )
    await repo.upsert(quote)
    await e2e_db_session.commit()
    return seeded_instrument
