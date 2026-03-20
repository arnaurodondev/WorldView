#!/usr/bin/env python3
"""One-time backfill: populate fundamental_metrics from existing section tables.

Reads all rows from the 18 fundamentals section tables, extracts catalogued
metrics via ``metric_extractor.extract_metrics``, and upserts them into
``fundamental_metrics``.

Usage:
    # Set DATABASE_URL (or MARKET_DATA_DB_URL) env var, then:
    python -m scripts.backfill_fundamental_metrics

    # Or from the service root:
    python scripts/backfill_fundamental_metrics.py

Requires:
    - The ``fundamental_metrics`` table to exist (migration 002).
    - A running PostgreSQL instance with the market-data schema.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Ensure the service package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from market_data.domain.enums import FundamentalsSection
from market_data.infrastructure.db.metric_extractor import extract_metrics
from market_data.infrastructure.db.models.fundamentals import (
    AnalystConsensusModel,
    BalanceSheetModel,
    CashFlowStatementModel,
    HighlightsModel,
    IncomeStatementModel,
    ValuationRatiosModel,
)
from market_data.infrastructure.db.repositories.fundamental_metrics_repo import PgFundamentalMetricsRepository

# Section tables that have entries in the metric catalog
_BACKFILL_SECTIONS: list[tuple[type, FundamentalsSection]] = [
    (AnalystConsensusModel, FundamentalsSection.ANALYST_CONSENSUS),
    (ValuationRatiosModel, FundamentalsSection.VALUATION_RATIOS),
    (HighlightsModel, FundamentalsSection.HIGHLIGHTS),
    (IncomeStatementModel, FundamentalsSection.INCOME_STATEMENT),
    (BalanceSheetModel, FundamentalsSection.BALANCE_SHEET),
    (CashFlowStatementModel, FundamentalsSection.CASH_FLOW),
]

BATCH_SIZE = 500
logger = structlog.get_logger(__name__)


async def backfill(db_url: str) -> None:
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    total_rows = 0

    async with session_factory() as session:
        repo = PgFundamentalMetricsRepository(session)

        for model_class, section_enum in _BACKFILL_SECTIONS:
            table_name = getattr(model_class, "__tablename__", model_class.__name__)
            logger.info("fundamental_metrics_backfill_started", section=section_enum.value, table=table_name)

            result = await session.execute(select(model_class))
            rows = result.scalars().all()

            batch: list = []
            for row in rows:
                period_type_str = getattr(row, "period_type", "SNAPSHOT")
                period_end = getattr(row, "period_end_date", None)
                if period_end is None:
                    continue

                as_of_date = period_end.date() if hasattr(period_end, "date") else period_end
                data = row.data or {}
                ingested_at = getattr(row, "ingested_at", datetime.now(tz=UTC))

                metric_rows = extract_metrics(
                    instrument_id=row.instrument_id,
                    section=section_enum,
                    period_type=period_type_str,
                    as_of_date=as_of_date,
                    data=data,
                    ingested_at=ingested_at,
                )
                batch.extend(metric_rows)

                if len(batch) >= BATCH_SIZE:
                    await repo.upsert_metrics(batch)
                    total_rows += len(batch)
                    batch = []

            if batch:
                await repo.upsert_metrics(batch)
                total_rows += len(batch)

            await session.commit()
            logger.info(
                "fundamental_metrics_backfill_section_done",
                section=section_enum.value,
                source_rows=len(rows),
            )

    await engine.dispose()
    logger.info("fundamental_metrics_backfill_complete", upserted_metric_rows=total_rows)


def main() -> None:
    db_url = os.environ.get("MARKET_DATA_DB_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("fundamental_metrics_backfill_missing_db_url")
        sys.exit(1)

    # Ensure async driver
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    asyncio.run(backfill(db_url))


if __name__ == "__main__":
    main()
