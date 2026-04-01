"""Read-side query helpers for the fundamental_metrics table.

Provides timeseries queries (one instrument, one metric, date range) and
screening queries (filter instruments by metric thresholds).

All functions accept an ``AsyncSession`` directly so the caller can pass the
read (replica) session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, select

from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.instruments import InstrumentModel

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession


async def query_timeseries(
    session: AsyncSession,
    instrument_id: str,
    metric: str,
    start_date: date | None = None,
    end_date: date | None = None,
    period_type: str | None = None,
    limit: int = 1000,
) -> list[MetricDataPoint]:
    """Query timeseries data for a single instrument and metric.

    Returns data points ordered by ``as_of_date`` ascending.
    """
    m = FundamentalMetricModel
    conditions = [
        m.instrument_id == instrument_id,
        m.metric == metric,
    ]
    if start_date is not None:
        conditions.append(m.as_of_date >= start_date)
    if end_date is not None:
        conditions.append(m.as_of_date <= end_date)
    if period_type is not None:
        conditions.append(m.period_type == period_type)

    stmt = (
        select(m.as_of_date, m.value_numeric, m.value_text, m.period_type)
        .where(and_(*conditions))
        .order_by(m.as_of_date.asc())
        .limit(limit)
    )

    result: Any = await session.execute(stmt)
    rows = result.all()

    return [
        MetricDataPoint(
            as_of_date=row.as_of_date,
            value_numeric=row.value_numeric,
            value_text=row.value_text,
            period_type=row.period_type,
        )
        for row in rows
    ]


async def query_screen(
    session: AsyncSession,
    filters: list[ScreenFilter],
    limit: int = 100,
    offset: int = 0,
) -> list[ScreenResult]:
    """Screen instruments by metric thresholds.

    For each filter, uses the most recent ``as_of_date`` per instrument.
    Returns instruments that satisfy ALL filters (AND logic).
    """
    if not filters:
        return []

    m = FundamentalMetricModel

    # Build a CTE for each filter that selects instruments matching the criterion
    # using the latest value per instrument for that metric.
    filter_subqueries = []
    metric_columns = []

    for i, f in enumerate(filters):
        alias = f"f{i}"

        # Subquery: latest as_of_date per instrument for this metric
        latest_date_sq = (
            select(
                m.instrument_id,
                func.max(m.as_of_date).label("max_date"),
            )
            .where(m.metric == f.metric)
            .group_by(m.instrument_id)
            .subquery(name=f"{alias}_latest")
        )

        # Join back to get the actual value at the latest date
        value_sq = select(
            m.instrument_id.label("instrument_id"),
            m.value_numeric.label("value_numeric"),
        ).join(
            latest_date_sq,
            and_(
                m.instrument_id == latest_date_sq.c.instrument_id,
                m.as_of_date == latest_date_sq.c.max_date,
                m.metric == f.metric,
            ),
        )

        # Apply period_type filter if specified
        if f.period_type is not None:
            value_sq = value_sq.where(m.period_type == f.period_type)

        # Apply min/max filters
        conditions = []
        if f.min_value is not None:
            conditions.append(m.value_numeric >= f.min_value)
        if f.max_value is not None:
            conditions.append(m.value_numeric <= f.max_value)
        if conditions:
            value_sq = value_sq.where(and_(*conditions))

        sq = value_sq.subquery(name=alias)
        filter_subqueries.append(sq)
        metric_columns.append((f.metric, sq.c.value_numeric))

    # INNER JOIN all filter subqueries on instrument_id
    base = filter_subqueries[0]

    # Add metric value columns
    select_cols = [base.c.instrument_id]
    for metric_name, col in metric_columns:
        select_cols.append(col.label(metric_name))

    joined = select(*select_cols)

    for sq in filter_subqueries[1:]:
        joined = joined.join(sq, base.c.instrument_id == sq.c.instrument_id)

    # Apply sector filter: join with instruments and restrict by sector if any filter specifies one
    sector_values = [f.sector for f in filters if f.sector is not None]
    if sector_values:
        instr = InstrumentModel
        joined = joined.join(instr, instr.id == base.c.instrument_id)
        # AND logic: all specified sector values must agree (in practice, use the first one
        # since cross-sector AND would match zero instruments).  Use IN to allow callers
        # to express "sector in (list)" by adding multiple filters with the same metric but
        # different sectors; here we apply the intersection (AND) of all sector values.
        for sv in sector_values:
            joined = joined.where(instr.sector == sv)

    joined = joined.order_by(base.c.instrument_id).offset(offset).limit(limit)

    result: Any = await session.execute(joined)
    rows = result.all()

    results = []
    for row in rows:
        metrics_dict: dict[str, Decimal | None] = {}
        for metric_name, _ in metric_columns:
            metrics_dict[metric_name] = getattr(row, metric_name, None)
        results.append(
            ScreenResult(
                instrument_id=row.instrument_id,
                metrics=metrics_dict,
            )
        )

    return results


async def query_latest_metric(
    session: AsyncSession,
    instrument_id: str,
    metric: str,
    period_type: str | None = None,
) -> MetricDataPoint | None:
    """Return the most recent value for a single instrument + metric."""
    m = FundamentalMetricModel
    conditions = [
        m.instrument_id == instrument_id,
        m.metric == metric,
    ]
    if period_type is not None:
        conditions.append(m.period_type == period_type)

    stmt = (
        select(m.as_of_date, m.value_numeric, m.value_text, m.period_type)
        .where(and_(*conditions))
        .order_by(m.as_of_date.desc())
        .limit(1)
    )

    result: Any = await session.execute(stmt)
    row = result.first()

    if row is None:
        return None

    return MetricDataPoint(
        as_of_date=row.as_of_date,
        value_numeric=row.value_numeric,
        value_text=row.value_text,
        period_type=row.period_type,
    )


async def query_available_metrics(
    session: AsyncSession,
    instrument_id: str,
) -> list[str]:
    """Return all distinct metric names available for an instrument."""
    m = FundamentalMetricModel
    stmt = select(m.metric).where(m.instrument_id == instrument_id).distinct().order_by(m.metric)
    result: Any = await session.execute(stmt)
    return [row[0] for row in result.all()]
