"""Backfill utilities for fundamental_metrics projection.

This module replays existing fundamentals section rows through the metric
extractor and upserts the derived rows into ``fundamental_metrics``.

Operational guarantees:
- Deterministic section traversal order.
- Deterministic row traversal within each section (ORDER BY id ASC).
- Chunked processing with configurable batch size.
- Resumable execution via (section, start_id).
- Per-batch commit with structured counters.
- Optional continue-on-error mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, select, tuple_

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from market_data.domain.enums import FundamentalsSection
from market_data.infrastructure.db.metric_extractor import MetricRow, extract_metrics
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.fundamentals import (
    AnalystConsensusModel,
    BalanceSheetModel,
    CashFlowStatementModel,
    HighlightsModel,
    IncomeStatementModel,
    ValuationRatiosModel,
)
from market_data.infrastructure.db.repositories.fundamental_metrics_repo import PgFundamentalMetricsRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillOptions:
    batch_size: int = 500
    section: str | None = None
    start_id: str | None = None
    continue_on_error: bool = True


@dataclass(slots=True)
class BackfillSummary:
    started_at: datetime
    completed_at: datetime | None
    runtime_seconds: float
    sections_processed: list[str]
    section: str | None
    start_id: str | None
    batch_size: int
    scanned_rows: int
    extracted_metric_rows: int
    inserted_rows: int
    updated_rows: int
    skipped_rows: int
    failed_rows: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        return payload


_BACKFILL_SECTIONS: list[tuple[type[Any], FundamentalsSection]] = [
    (AnalystConsensusModel, FundamentalsSection.ANALYST_CONSENSUS),
    (ValuationRatiosModel, FundamentalsSection.VALUATION_RATIOS),
    (HighlightsModel, FundamentalsSection.HIGHLIGHTS),
    (IncomeStatementModel, FundamentalsSection.INCOME_STATEMENT),
    (BalanceSheetModel, FundamentalsSection.BALANCE_SHEET),
    (CashFlowStatementModel, FundamentalsSection.CASH_FLOW),
]


def _resolve_sections(section: str | None) -> list[tuple[type[Any], FundamentalsSection]]:
    if section is None:
        return _BACKFILL_SECTIONS

    normalized = section.strip().lower()
    for model, enum_val in _BACKFILL_SECTIONS:
        if enum_val.value == normalized:
            return [(model, enum_val)]
    raise ValueError(f"Unsupported section '{section}'. Expected one of: {[s.value for _, s in _BACKFILL_SECTIONS]}")


def _metric_key(row: MetricRow) -> tuple[str, Any, str, str | None]:
    return (row.instrument_id, row.as_of_date, row.metric, row.period_type)


async def _count_existing_keys(session: AsyncSession, metric_rows: list[MetricRow]) -> int:
    keys = sorted({_metric_key(r) for r in metric_rows})
    if not keys:
        return 0

    stmt = select(func.count()).where(
        tuple_(
            FundamentalMetricModel.instrument_id,
            FundamentalMetricModel.as_of_date,
            FundamentalMetricModel.metric,
            FundamentalMetricModel.period_type,
        ).in_(keys)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _fetch_section_batch(
    session: AsyncSession,
    model_class: type[Any],
    batch_size: int,
    last_id: str | None,
) -> list[Any]:
    conditions = []
    if last_id:
        conditions.append(model_class.id > last_id)

    stmt: Any = select(model_class).order_by(model_class.id.asc()).limit(batch_size)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def run_backfill(
    session_factory: async_sessionmaker[AsyncSession],
    options: BackfillOptions,
) -> BackfillSummary:
    started_at = datetime.now(tz=UTC)
    summary = BackfillSummary(
        started_at=started_at,
        completed_at=None,
        runtime_seconds=0.0,
        sections_processed=[],
        section=options.section,
        start_id=options.start_id,
        batch_size=options.batch_size,
        scanned_rows=0,
        extracted_metric_rows=0,
        inserted_rows=0,
        updated_rows=0,
        skipped_rows=0,
        failed_rows=0,
    )

    section_pairs = _resolve_sections(options.section)

    async with session_factory() as session:
        repo = PgFundamentalMetricsRepository(session)

        for model_class, section_enum in section_pairs:
            table_name = getattr(model_class, "__tablename__", model_class.__name__)
            section_value = section_enum.value
            summary.sections_processed.append(section_value)

            logger.info(
                "fundamental_metrics_backfill.section_started",
                section=section_value,
                table=table_name,
                start_id=options.start_id,
                batch_size=options.batch_size,
            )

            last_id = options.start_id
            while True:
                batch_rows = await _fetch_section_batch(session, model_class, options.batch_size, last_id)
                if not batch_rows:
                    break

                metric_batch: list[MetricRow] = []
                for row in batch_rows:
                    summary.scanned_rows += 1
                    row_id = getattr(row, "id", None)
                    last_id = str(row_id) if row_id else last_id

                    try:
                        period_end = row.period_end_date
                        as_of_date = period_end.date() if hasattr(period_end, "date") else period_end
                        data = row.data or {}
                        period_type_str = getattr(row, "period_type", "SNAPSHOT")
                        ingested_at = getattr(row, "ingested_at", datetime.now(tz=UTC))

                        extracted = extract_metrics(
                            instrument_id=row.instrument_id,
                            section=section_enum,
                            period_type=period_type_str,
                            as_of_date=as_of_date,
                            data=data,
                            ingested_at=ingested_at,
                        )
                        if not extracted:
                            summary.skipped_rows += 1
                            continue

                        summary.extracted_metric_rows += len(extracted)
                        metric_batch.extend(extracted)
                    except Exception as exc:
                        summary.failed_rows += 1
                        logger.error(
                            "fundamental_metrics_backfill.row_failed",
                            section=section_value,
                            row_id=row_id,
                            error=str(exc),
                        )
                        if not options.continue_on_error:
                            raise

                if metric_batch:
                    existing_count = await _count_existing_keys(session, metric_batch)
                    unique_count = len({_metric_key(r) for r in metric_batch})
                    await repo.upsert_metrics(metric_batch)
                    summary.updated_rows += existing_count
                    summary.inserted_rows += max(unique_count - existing_count, 0)

                await session.commit()

                logger.info(
                    "fundamental_metrics_backfill.batch_committed",
                    section=section_value,
                    last_id=last_id,
                    scanned_rows=summary.scanned_rows,
                    extracted_metric_rows=summary.extracted_metric_rows,
                    inserted_rows=summary.inserted_rows,
                    updated_rows=summary.updated_rows,
                    skipped_rows=summary.skipped_rows,
                    failed_rows=summary.failed_rows,
                )

            # Reset section-local cursor for next section unless a specific section was targeted.
            if options.section is None:
                last_id = None

            logger.info(
                "fundamental_metrics_backfill.section_completed",
                section=section_value,
                scanned_rows=summary.scanned_rows,
                extracted_metric_rows=summary.extracted_metric_rows,
            )

    completed_at = datetime.now(tz=UTC)
    summary.completed_at = completed_at
    summary.runtime_seconds = float((completed_at - started_at).total_seconds())
    logger.info("fundamental_metrics_backfill.completed", **summary.to_dict())
    return summary
