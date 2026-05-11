"""Read-side query helpers for the fundamental_metrics table.

Provides timeseries queries (one instrument, one metric, date range) and
screening queries (filter instruments by metric thresholds).

All functions accept an ``AsyncSession`` directly so the caller can pass the
read (replica) session.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, select

from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
from market_data.domain.entities import ScreenFieldMetadata
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.screen_field_metadata import ScreenFieldMetadataModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def query_timeseries(
    session: AsyncSession,
    instrument_id: str,
    metric: str,
    start_date: date | None = None,
    end_date: date | None = None,
    period_type: str | None = None,
    limit: int = 1000,
    order: str = "asc",
) -> list[MetricDataPoint]:
    """Query timeseries data for a single instrument and metric.

    ``order`` controls SQL-side ordering and is critical when ``limit`` is
    applied: with ``order="desc"`` and ``limit=12`` the caller gets the 12
    most-recent points (typical UI use case for sparklines / trend charts).
    With ``order="asc"`` the 12 OLDEST points are returned — almost never
    what UI callers want, but useful for back-test windows.

    Regardless of ``order``, the returned list is then re-sorted ASC by date
    so callers can render bars left-to-right in chronological order without
    needing to know the underlying fetch direction.

    Audit 2026-05-09: prior to this version, ``order`` was silently dropped
    by the read repository, causing the Fundamentals tab Revenue Trend and
    EPS Trend charts to render data from 1985-1988 (Apple's pre-IPO
    quarters) instead of the most recent 12.
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

    # WHY explicit lower(): defensive against case-mismatched callers; the
    # router validates the value but the repository must still be safe.
    sql_order = m.as_of_date.desc() if order.lower() == "desc" else m.as_of_date.asc()

    stmt = (
        select(m.as_of_date, m.value_numeric, m.value_text, m.period_type)
        .where(and_(*conditions))
        .order_by(sql_order)
        .limit(limit)
    )

    result: Any = await session.execute(stmt)
    rows = result.all()

    # Always return ASC by date so the UI never has to know the fetch order.
    points = [
        MetricDataPoint(
            as_of_date=row.as_of_date,
            value_numeric=row.value_numeric,
            value_text=row.value_text,
            period_type=row.period_type,
        )
        for row in rows
    ]
    points.sort(key=lambda p: p.as_of_date)
    return points


async def query_screen(
    session: AsyncSession,
    filters: list[ScreenFilter],
    limit: int = 50,
    offset: int = 0,
    sort_by: str | None = None,
    sort_order: str = "asc",
) -> tuple[list[ScreenResult], int]:
    """Screen instruments by metric thresholds.

    For each filter, uses the most recent ``as_of_date`` per instrument.
    Returns instruments that satisfy ALL filters (AND logic), along with the
    total count of matching rows (before LIMIT/OFFSET, for pagination).

    ``sort_by`` is validated by the caller (router) against a whitelist of
    allowed field names before reaching this function — it is never interpolated
    into raw SQL; column references are resolved via SQLAlchemy ORM attributes.
    """
    instr = InstrumentModel

    if not filters:
        # No filters — return ALL instruments sorted by symbol, with the most
        # common display metrics populated via LEFT JOIN so the screener table
        # shows real values instead of "—" in the default view.
        # WHY LEFT JOIN (not INNER): we must not exclude instruments that lack
        # some metrics (e.g. crypto instruments have no P/E). LEFT JOIN returns
        # NULL for missing metrics, which the frontend renders as "—".
        m = FundamentalMetricModel

        key_metrics = [
            "market_capitalization",
            "pe_ratio",
            "daily_return",
            "beta",
            "revenue_usd",
        ]

        def _latest_metric_sq(metric_name: str, alias: str) -> Any:
            """Subquery: latest value for metric_name per instrument."""
            latest_sq = (
                select(
                    m.instrument_id,
                    func.max(m.as_of_date).label("max_date"),
                )
                .where(m.metric == metric_name)
                .group_by(m.instrument_id)
                .subquery(name=f"{alias}_latest")
            )
            return (
                select(
                    m.instrument_id.label("instrument_id"),
                    m.value_numeric.label("value_numeric"),
                )
                .join(
                    latest_sq,
                    and_(
                        m.instrument_id == latest_sq.c.instrument_id,
                        m.as_of_date == latest_sq.c.max_date,
                        m.metric == metric_name,
                    ),
                )
                .subquery(name=alias)
            )

        key_sqs = {name: _latest_metric_sq(name, f"km_{name}") for name in key_metrics}

        total_col = func.count().over().label("total_count")
        select_cols: list[Any] = [
            instr.id.label("instrument_id"),
            instr.symbol.label("ticker"),
            instr.name.label("name"),
            instr.exchange.label("exchange"),
            instr.sector.label("sector"),
            total_col,
        ]
        for metric_name, sq in key_sqs.items():
            select_cols.append(sq.c.value_numeric.label(metric_name))

        stmt = select(*select_cols).order_by(instr.symbol.asc()).offset(offset).limit(limit)
        for sq in key_sqs.values():
            stmt = stmt.outerjoin(sq, instr.id == sq.c.instrument_id)

        result: Any = await session.execute(stmt)
        rows = result.all()
        if not rows:
            return [], 0
        total = int(rows[0].total_count)
        return [
            ScreenResult(
                instrument_id=str(row.instrument_id),
                ticker=row.ticker,
                name=row.name,
                exchange=row.exchange,
                sector=row.sector,
                metrics={
                    name: getattr(row, name, None) for name in key_metrics if getattr(row, name, None) is not None
                },
            )
            for row in rows
        ], total

    m = FundamentalMetricModel

    # Build a subquery for each filter: latest value per instrument for that metric.
    filter_subqueries: list[Any] = []
    metric_columns: list[tuple[str, Any]] = []

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

        if f.period_type is not None:
            value_sq = value_sq.where(m.period_type == f.period_type)

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

    # INNER JOIN all filter subqueries then always JOIN instruments for
    # ticker/name/exchange/sector and COUNT(*) OVER() for pagination total.
    base = filter_subqueries[0]

    filter_select_cols: list[Any] = [
        base.c.instrument_id,
        instr.symbol.label("ticker"),
        instr.name.label("name"),
        instr.exchange.label("exchange"),
        instr.sector.label("sector"),
        func.count().over().label("total_count"),
    ]
    for metric_name, col in metric_columns:
        filter_select_cols.append(col.label(metric_name))

    stmt = select(*filter_select_cols)

    for sq in filter_subqueries[1:]:
        stmt = stmt.join(sq, base.c.instrument_id == sq.c.instrument_id)

    # Always JOIN instruments (provides ticker/name/exchange/sector + sector filter)
    stmt = stmt.join(instr, instr.id == base.c.instrument_id)

    # Sector filter (AND logic across all filter entries that specify a sector)
    for sv in (f.sector for f in filters if f.sector is not None):
        stmt = stmt.where(instr.sector == sv)

    # Sorting — column resolved from ORM attributes (no raw SQL interpolation)
    sort_col: Any
    if sort_by == "ticker":
        sort_col = instr.symbol
    elif sort_by == "name":
        sort_col = instr.name
    elif sort_by is not None:
        # metric sort: find the column from the metric subqueries
        sort_col = next((col for mn, col in metric_columns if mn == sort_by), base.c.instrument_id)
    else:
        sort_col = None

    if sort_col is not None:
        order_expr = sort_col.desc().nullslast() if sort_order == "desc" else sort_col.asc().nullslast()
        stmt = stmt.order_by(order_expr)
    else:
        stmt = stmt.order_by(base.c.instrument_id)

    stmt = stmt.offset(offset).limit(limit)

    screen_result: Any = await session.execute(stmt)
    rows = screen_result.all()

    if not rows:
        return [], 0

    total = int(rows[0].total_count)
    results = []
    for row in rows:
        metrics_dict: dict[str, Decimal | None] = {}
        for metric_name, _ in metric_columns:
            metrics_dict[metric_name] = getattr(row, metric_name, None)
        results.append(
            ScreenResult(
                instrument_id=row.instrument_id,
                ticker=row.ticker,
                name=row.name,
                exchange=row.exchange,
                sector=row.sector,
                metrics=metrics_dict,
            )
        )

    return results, total


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


async def query_screen_field_metadata(session: AsyncSession) -> list[ScreenFieldMetadata]:
    """Return all rows from ``screen_field_metadata`` ordered by field_name.

    Used as the DB fallback when the Valkey cache misses.
    """
    sfm = ScreenFieldMetadataModel
    stmt = select(
        sfm.field_name,
        sfm.label,
        sfm.field_type,
        sfm.unit,
        sfm.description,
        sfm.observed_min,
        sfm.observed_max,
        sfm.null_fraction,
    ).order_by(sfm.field_name)

    result: Any = await session.execute(stmt)
    rows = result.all()

    return [
        ScreenFieldMetadata(
            name=row.field_name,
            label=row.label,
            field_type=row.field_type,
            unit=row.unit,
            description=row.description,
            observed_min=float(row.observed_min) if row.observed_min is not None else None,
            observed_max=float(row.observed_max) if row.observed_max is not None else None,
            null_fraction=float(row.null_fraction) if row.null_fraction is not None else 0.0,
        )
        for row in rows
    ]
