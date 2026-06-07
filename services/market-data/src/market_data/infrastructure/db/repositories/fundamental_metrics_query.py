"""Read-side query helpers for the fundamental_metrics table.

Provides timeseries queries (one instrument, one metric, date range) and
screening queries (filter instruments by metric thresholds).

All functions accept an ``AsyncSession`` directly so the caller can pass the
read (replica) session.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import and_, func, select, text

from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
from market_data.domain.entities import ScreenFieldMetadata
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.fundamentals_snapshot import InstrumentFundamentalsSnapshotModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.quotes import QuoteModel
from market_data.infrastructure.db.models.screen_field_metadata import ScreenFieldMetadataModel

# Snapshot metric columns selected from instrument_fundamentals_snapshot (L-2).
# Aliased with "snap_" prefix to avoid name collisions with fundamental_metrics columns.
_SNAP_FIELDS: tuple[str, ...] = (
    "avg_volume_30d",
    "eps_ttm",
    "free_cash_flow",
    "fcf_margin",
    "interest_coverage",
    "net_debt_to_ebitda",
    "credit_rating",
    # ── Wave L-4a snapshot fields (PLAN-0089) ────────────────────────────────
    # Projected via the same LEFT JOIN as the L-2 fields above so every
    # ``ScreenResult`` carries them when populated. Filtering/sorting on
    # these fields is wired below alongside the L-2 ``numeric_snap_filters``.
    "analyst_target_price",
    "analyst_consensus_rating",
    "institutional_ownership_pct",
    "short_percent",
    # Wave L-5c: calendar snapshot fields — included in every projection so
    # the screener table can render a "NEXT EARN" / "NEXT DIV" column even
    # without an active filter.
    "next_earnings_date",
    "next_dividend_date",
    # Wave L-4b: trailing-90d insider net dollar flow.
    "insider_net_buy_90d",
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)

# PLAN-0103 W16 (BP-635, 2026-05-30): introspect the real
# ``instrument_fundamentals_snapshot`` table to discover which of the
# ``_SNAP_FIELDS`` columns physically exist in the deployed schema.
#
# WHY this guard exists: ``query_screen`` projects every entry in
# ``_SNAP_FIELDS`` unconditionally (``getattr(snap, sf)``). When the deployed
# DB lags the ORM (e.g. migrations 028 / 030 not yet applied — calendar
# columns ``next_earnings_date`` / ``next_dividend_date`` and the L-4b
# ``insider_net_buy_90d`` column missing), the generated SQL referenced
# non-existent columns and asyncpg raised
# ``UndefinedColumnError: column instrument_fundamentals_snapshot.next_earnings_date does not exist``,
# which surfaced as a 500 to ``/v1/fundamentals/screen`` and triggered the
# BP-623 honest-refusal pattern in rag-chat (see Q2 ``ru_ai_semi_screener``
# benchmark regression, 2026-05-30 run).
#
# We resolve the available column set lazily once per process from the
# AsyncSession's bind metadata. Result is cached in ``_AVAILABLE_SNAP_FIELDS``
# until process restart, which is when migrations would have been re-applied.
_AVAILABLE_SNAP_FIELDS: tuple[str, ...] | None = None


async def _resolve_available_snap_fields(session: AsyncSession) -> tuple[str, ...]:
    """Return the subset of ``_SNAP_FIELDS`` present in the live DB schema.

    Lazy + memoised: first call introspects ``information_schema.columns``;
    subsequent calls reuse the cached tuple. If introspection fails (rare —
    permissions / unexpected schema), we fall back to the full ``_SNAP_FIELDS``
    set and let SQL surface the error normally so we never silently mask a
    real bug behind defensive fallback.
    """
    global _AVAILABLE_SNAP_FIELDS
    if _AVAILABLE_SNAP_FIELDS is not None:
        return _AVAILABLE_SNAP_FIELDS

    try:
        result: Any = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'instrument_fundamentals_snapshot'"
            )
        )
        present = {row[0] for row in result.all()}
        available = tuple(sf for sf in _SNAP_FIELDS if sf in present)
        missing = [sf for sf in _SNAP_FIELDS if sf not in present]
        if missing:
            _log.warning(
                "snap_fields_missing_from_schema",
                missing=missing,
                available_count=len(available),
            )
        _AVAILABLE_SNAP_FIELDS = available
        return available
    except Exception as e:  # pragma: no cover — introspection failure path
        _log.warning("snap_fields_introspect_failed", error=str(e))
        return _SNAP_FIELDS


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

    WHY statement_timeout: the screener query involves multiple correlated
    subqueries (one per filter metric) + three LEFT JOINs on potentially large
    tables. On a cold DB (page cache empty) the planner can choose a nested-loop
    plan that runs in O(n*m) time. An 8 s ceiling converts a 31 s hang into a
    clean database-level cancellation; the router maps the resulting
    ``asyncpg.QueryCanceledError`` → HTTP 504 (handled by FastAPI's exception
    middleware). SET LOCAL restricts the timeout to this transaction only.
    """
    # Apply an 8 s statement timeout for the duration of this read transaction.
    # SET LOCAL is session-safe for pooled connections (reverts at transaction end).
    await session.execute(text("SET LOCAL statement_timeout = '8000'"))

    instr = InstrumentModel
    snap = InstrumentFundamentalsSnapshotModel

    # PLAN-0103 W16 (BP-635): only project snapshot columns the deployed schema
    # actually has. See ``_resolve_available_snap_fields`` for rationale.
    snap_fields_available: tuple[str, ...] = await _resolve_available_snap_fields(session)

    if not filters:
        # No filters — return ALL instruments sorted by symbol, with the most
        # common display metrics populated via LEFT JOIN so the screener table
        # shows real values instead of "—" in the default view.
        # WHY LEFT JOIN (not INNER): we must not exclude instruments that lack
        # some metrics (e.g. crypto instruments have no P/E). LEFT JOIN returns
        # NULL for missing metrics, which the frontend renders as "—".
        m = FundamentalMetricModel

        # WHY these 10 metrics: these are the columns displayed in the screener
        # table's default (no-filter) view. Each metric name must match a row
        # that the metric_extractor actually writes into fundamental_metrics.
        # NOTE: ``revenue_ttm`` (HIGHLIGHTS section) replaces the old
        # ``revenue_usd`` placeholder — ``revenue_usd`` was never populated
        # in the extractor catalog, so the column always returned NULL.
        key_metrics = [
            "market_capitalization",
            "pe_ratio",
            "daily_return",
            "beta",
            "revenue_ttm",
            # PRD-0099: add the five columns the screener table renders so the
            # default view shows real values instead of "—".
            "forward_pe",
            "dividend_yield",
            "roe_ttm",
            "operating_margin_ttm",
            "quarterly_revenue_growth_yoy",
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
        q = QuoteModel

        total_col = func.count().over().label("total_count")
        select_cols: list[Any] = [
            instr.id.label("instrument_id"),
            instr.symbol.label("ticker"),
            instr.name.label("name"),
            instr.exchange.label("exchange"),
            instr.sector.label("sector"),
            total_col,
            # WHY LEFT JOIN on quotes: current_price (quotes.last) is a live
            # value not stored in fundamental_metrics. A LEFT JOIN ensures
            # instruments without a quote row still appear in the result (NULL
            # current_price renders as "—" in the frontend).
            q.last.label("current_price"),
        ]
        for metric_name, sq in key_sqs.items():
            select_cols.append(sq.c.value_numeric.label(metric_name))
        for sf in snap_fields_available:
            select_cols.append(getattr(snap, sf).label(f"snap_{sf}"))

        stmt = select(*select_cols).order_by(instr.symbol.asc()).offset(offset).limit(limit)
        for sq in key_sqs.values():
            stmt = stmt.outerjoin(sq, instr.id == sq.c.instrument_id)
        stmt = stmt.outerjoin(snap, instr.id == snap.instrument_id)
        stmt = stmt.outerjoin(q, instr.id == q.instrument_id)

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
                    **{name: getattr(row, name, None) for name in key_metrics if getattr(row, name, None) is not None},
                    # current_price from quotes LEFT JOIN (None if no quote row)
                    **({"current_price": float(row.current_price)} if row.current_price is not None else {}),
                    **{
                        sf: getattr(row, f"snap_{sf}")
                        for sf in snap_fields_available
                        if getattr(row, f"snap_{sf}", None) is not None
                    },
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
    q = QuoteModel

    filter_select_cols: list[Any] = [
        base.c.instrument_id,
        instr.symbol.label("ticker"),
        instr.name.label("name"),
        instr.exchange.label("exchange"),
        instr.sector.label("sector"),
        func.count().over().label("total_count"),
        # WHY current_price here (mirrors the no-filter branch): quotes.last is a
        # live value not stored in fundamental_metrics. LEFT JOIN ensures instruments
        # without a quote row still appear (NULL current_price → "—" in the frontend).
        q.last.label("current_price"),
    ]
    for metric_name, col in metric_columns:
        filter_select_cols.append(col.label(metric_name))
    for sf in snap_fields_available:
        filter_select_cols.append(getattr(snap, sf).label(f"snap_{sf}"))

    stmt = select(*filter_select_cols)

    for sq in filter_subqueries[1:]:
        stmt = stmt.join(sq, base.c.instrument_id == sq.c.instrument_id)

    # Always JOIN instruments (provides ticker/name/exchange/sector + sector filter)
    stmt = stmt.join(instr, instr.id == base.c.instrument_id)
    stmt = stmt.outerjoin(snap, instr.id == snap.instrument_id)
    # WHY outerjoin quotes: current_price must not exclude instruments with no quote row.
    stmt = stmt.outerjoin(q, instr.id == q.instrument_id)

    # Sector filter (AND logic across all filter entries that specify a sector)
    for sv in (f.sector for f in filters if f.sector is not None):
        stmt = stmt.where(instr.sector == sv)

    # FIX-LIVE-M (2026-05-24): mirror sector with industry — GICS industry
    # (e.g. "Semiconductors") is more selective than sector ("Technology").
    # AND logic across all filter entries that specify an industry.
    for iv in (f.industry for f in filters if f.industry is not None):
        stmt = stmt.where(instr.industry == iv)

    # L-1: instrument-attribute filters — applied as AND predicates against instruments table
    for cv in (f.country for f in filters if f.country is not None):
        stmt = stmt.where(instr.country == cv)
    for ev in (f.exchange for f in filters if f.exchange is not None):
        stmt = stmt.where(instr.exchange == ev)
    if any(f.has_fundamentals is not None for f in filters):
        hf = next(f.has_fundamentals for f in filters if f.has_fundamentals is not None)
        stmt = stmt.where(instr.has_fundamentals == hf)
    if any(f.has_ohlcv is not None for f in filters):
        ho = next(f.has_ohlcv for f in filters if f.has_ohlcv is not None)
        stmt = stmt.where(instr.has_ohlcv == ho)

    # ── Wave L-2: snapshot-column predicates ─────────────────────────────────
    # Numeric min/max filters are applied as ``snap.<col> >= :v`` and
    # ``snap.<col> <= :v`` against the LEFT-JOINed snapshot. Because PostgreSQL
    # evaluates ``NULL >= :v`` to UNKNOWN, instruments without a snapshot row
    # are correctly dropped whenever any L-2 predicate is active. credit_ratings
    # uses an IN(...) predicate. All collapsed across filter entries with the
    # first non-None value (mirrors L-1 has_ohlcv/has_fundamentals collapse).
    numeric_snap_filters: tuple[str, ...] = (
        "avg_volume_30d",
        "eps_ttm",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        # ── Wave L-4a snapshot fields (PLAN-0089) ────────────────────────────
        "analyst_target_price",
        "analyst_consensus_rating",
        "institutional_ownership_pct",
        "short_percent",
        # Wave L-4b: trailing-90d insider net dollar flow (sortable + filterable).
        "insider_net_buy_90d",
    )
    for snap_field in numeric_snap_filters:
        # PLAN-0103 W16 (BP-635): skip predicates against columns the deployed
        # schema lacks. Without this, an L-4b insider_net_buy_90d filter on a
        # pre-030 DB would generate ``UndefinedColumnError``.
        if snap_field not in snap_fields_available:
            continue
        min_attr = f"{snap_field}_min"
        max_attr = f"{snap_field}_max"
        min_val = next((getattr(f, min_attr) for f in filters if getattr(f, min_attr, None) is not None), None)
        max_val = next((getattr(f, max_attr) for f in filters if getattr(f, max_attr, None) is not None), None)
        if min_val is not None:
            stmt = stmt.where(getattr(snap, snap_field) >= min_val)
        if max_val is not None:
            stmt = stmt.where(getattr(snap, snap_field) <= max_val)
    # credit_ratings: IN predicate across non-empty tuple
    ratings = next((f.credit_ratings for f in filters if f.credit_ratings), None)
    if ratings:
        stmt = stmt.where(snap.credit_rating.in_(list(ratings)))

    # ── Wave L-5c: calendar (date) window filters ────────────────────────────
    # "Within next N days" maps to:
    #     WHERE col BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL 'N days'
    #
    # PostgreSQL ``NULL BETWEEN x AND y`` evaluates to UNKNOWN, so rows where
    # the snapshot column is NULL (the common case until L-5b ships) are
    # correctly excluded — same semantic as the L-2 numeric range filters.
    #
    # WHY ``text()`` for the upper bound: SQLAlchemy doesn't expose a
    # type-safe ``INTERVAL`` constructor for a bound integer at this level,
    # and constructing ``func.cast`` would be more obscure than this
    # parameter-bound text fragment. The value is an int validated by the
    # Pydantic schema (ge=0, le=365) — no user-controlled string interpolation.
    calendar_date_filters: tuple[tuple[str, str], ...] = (
        ("next_earnings_within_days", "next_earnings_date"),
        ("next_dividend_within_days", "next_dividend_date"),
    )
    for filter_attr, snap_col in calendar_date_filters:
        # PLAN-0103 W16 (BP-635): skip if the snapshot lacks the calendar
        # column (migration 028 not yet applied on this DB).
        if snap_col not in snap_fields_available:
            continue
        days = next(
            (getattr(f, filter_attr) for f in filters if getattr(f, filter_attr, None) is not None),
            None,
        )
        if days is not None:
            # Inclusive lower bound = today; inclusive upper bound = today + N.
            stmt = stmt.where(getattr(snap, snap_col) >= func.current_date())
            stmt = stmt.where(
                getattr(snap, snap_col)
                <= func.current_date() + text(":n_days * INTERVAL '1 day'").bindparams(n_days=days)
            )

    # Sorting — column resolved from ORM attributes (no raw SQL interpolation)
    sort_col: Any
    if sort_by == "ticker":
        sort_col = instr.symbol
    elif sort_by == "name":
        sort_col = instr.name
    elif sort_by in numeric_snap_filters:
        # Wave L-2: ORDER BY snapshot.<col>; column lookup is by Python attribute
        # name (no raw SQL), so this is safe to call directly without re-validation.
        # PLAN-0103 W16 (BP-635): if the column is missing from the deployed
        # schema, fall back to instrument_id sort rather than 500-ing.
        sort_col = getattr(snap, sort_by) if sort_by in snap_fields_available else None
    elif sort_by in {"next_earnings_date", "next_dividend_date"}:
        # Wave L-5c: ORDER BY snapshot calendar columns (ASC = soonest first).
        # Reuses the same nullslast policy below — instruments with NULL
        # calendar values sort last regardless of direction.
        sort_col = getattr(snap, sort_by) if sort_by in snap_fields_available else None
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
        metrics_dict: dict[str, Any] = {}
        for metric_name, _ in metric_columns:
            metrics_dict[metric_name] = getattr(row, metric_name, None)
        for sf in snap_fields_available:
            v = getattr(row, f"snap_{sf}", None)
            if v is not None:
                metrics_dict[sf] = v
        # WHY current_price here: mirrors the no-filter branch so every
        # ScreenResult carries the live quote price regardless of which code
        # path was taken. NULL means no quote row exists → frontend renders "—".
        cp = getattr(row, "current_price", None)
        if cp is not None:
            metrics_dict["current_price"] = float(cp)
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
