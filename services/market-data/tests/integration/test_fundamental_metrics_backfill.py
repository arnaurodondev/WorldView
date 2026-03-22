"""Integration tests for fundamental_metrics backfill workflow (FMG-04/FM5).

Verifies:
- Backfill populates rows from existing fundamentals section tables.
- Re-running backfill is idempotent (no duplicate rows; updates in place).
- Resume cursor (--section + --start-id equivalent) processes only rows after cursor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from market_data.infrastructure.db.backfill_fundamental_metrics import BackfillOptions, run_backfill
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.fundamentals import ValuationRatiosModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.securities import SecurityModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


async def _create_instrument(session) -> str:
    sec = SecurityModel(name="Backfill Test Corp")
    session.add(sec)
    await session.flush()

    instr = InstrumentModel(
        security_id=sec.id,
        symbol=f"BF{uuid4().hex[:8].upper()}",
        exchange="XNAS",
        has_fundamentals=True,
    )
    session.add(instr)
    await session.flush()
    return instr.id


@pytest.mark.asyncio
async def test_backfill_populates_and_is_idempotent(_migrated_db: str) -> None:
    """Backfill inserts projected rows, and rerun updates without duplicates."""
    engine = create_async_engine(_migrated_db, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        instrument_id = await _create_instrument(session)
        session.add(
            ValuationRatiosModel(
                instrument_id=instrument_id,
                period_type="SNAPSHOT",
                period_end_date=datetime(2024, 9, 30, tzinfo=UTC),
                data={"PE": 20.0, "PB": 3.1},
                ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    summary_1 = await run_backfill(factory, BackfillOptions(batch_size=1, continue_on_error=False))

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(FundamentalMetricModel).where(FundamentalMetricModel.instrument_id == instrument_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2

    summary_2 = await run_backfill(factory, BackfillOptions(batch_size=1, continue_on_error=False))

    async with factory() as session:
        rows_after = (
            (
                await session.execute(
                    select(FundamentalMetricModel).where(FundamentalMetricModel.instrument_id == instrument_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_after) == 2

    assert summary_1.inserted_rows >= 2
    assert summary_2.inserted_rows == 0
    assert summary_2.updated_rows >= 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_resume_from_start_id(_migrated_db: str) -> None:
    """Resume cursor processes only rows with id > start_id for selected section."""
    engine = create_async_engine(_migrated_db, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    first_id = "00000000-0000-0000-0000-000000000001"
    second_id = "00000000-0000-0000-0000-000000000002"

    async with factory() as session:
        instrument_id = await _create_instrument(session)
        session.add_all(
            [
                ValuationRatiosModel(
                    id=first_id,
                    instrument_id=instrument_id,
                    period_type="SNAPSHOT",
                    period_end_date=datetime(2024, 9, 29, tzinfo=UTC),
                    data={"PE": 19.0},
                    ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
                ),
                ValuationRatiosModel(
                    id=second_id,
                    instrument_id=instrument_id,
                    period_type="SNAPSHOT",
                    period_end_date=datetime(2024, 9, 30, tzinfo=UTC),
                    data={"PE": 20.0},
                    ingested_at=datetime(2024, 10, 1, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()

    summary = await run_backfill(
        factory,
        BackfillOptions(
            section="valuation_ratios",
            start_id=first_id,
            batch_size=10,
            continue_on_error=False,
        ),
    )

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(FundamentalMetricModel)
                    .where(FundamentalMetricModel.metric == "pe_ratio")
                    .where(FundamentalMetricModel.instrument_id == instrument_id)
                    .order_by(FundamentalMetricModel.as_of_date.asc())
                )
            )
            .scalars()
            .all()
        )

    assert summary.scanned_rows >= 1
    assert len(rows) == 1
    assert rows[0].as_of_date.isoformat() == "2024-09-30"
    assert float(rows[0].value_numeric) == pytest.approx(20.0)

    await engine.dispose()
