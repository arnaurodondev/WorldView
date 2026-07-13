"""Read-side query helpers for the fundamental_metrics table.

Provides timeseries queries (one instrument, one metric, date range) and
screening queries (filter instruments by metric thresholds).

All functions accept an ``AsyncSession`` directly so the caller can pass the
read (replica) session.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import Numeric, and_, func, literal, select, text, union_all

from market_data.application.ports.repositories import MetricDataPoint, ScreenFilter, ScreenResult
from market_data.config import Settings
from market_data.domain.entities import ScreenFieldMetadata
from market_data.infrastructure.db.models.fundamental_metrics import FundamentalMetricModel
from market_data.infrastructure.db.models.fundamentals.technicals_snapshots import TechnicalsSnapshotModel
from market_data.infrastructure.db.models.fundamentals_snapshot import InstrumentFundamentalsSnapshotModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
from market_data.infrastructure.db.models.quotes import QuoteModel
from market_data.infrastructure.db.models.screen_field_metadata import ScreenFieldMetadataModel

# ── Key display metrics (2026-06-10 frontend-audit fix) ─────────────────────
# WHY module-level: these are the columns the screener table renders in EVERY
# view. Previously the list lived inside the no-filter (GET) branch only, so
# the moment any filter was applied (POST branch) the result rows carried ONLY
# the filtered metrics — MKT CAP / P/E / CHG% / REV all rendered as "—"
# (frontend audit 2026-06-10, gap #1). Both branches now project this set:
#   - GET branch: via the scoped-LATERAL subqueries (unchanged mechanism)
#   - POST branch: via a single page-bounded DISTINCT ON enrichment query
#     (see ``_fetch_page_extras``) merged into each row's metrics dict.
# Each name must match a row the metric extractors actually write into
# ``fundamental_metrics`` (e.g. ``revenue_ttm`` from HIGHLIGHTS, the
# ``dist_from_52w_*`` pair from the computed-metrics worker).
_KEY_METRICS: tuple[str, ...] = (
    "market_capitalization",
    "pe_ratio",
    "daily_return",
    "beta",
    "revenue_ttm",
    # PRD-0099: the five columns the screener table renders so the default
    # view shows real values instead of "—".
    "forward_pe",
    "dividend_yield",
    "roe_ttm",
    "operating_margin_ttm",
    "quarterly_revenue_growth_yoy",
    # 2026-06-10 (frontend audit gap #3): 52-week distance metrics in the
    # default view — computed by computed_metrics_worker (L-3), stored as
    # SNAPSHOT-period fundamental_metrics rows.
    "dist_from_52w_high_pct",
    "dist_from_52w_low_pct",
    # 2026-06-11 (backend-gaps wave 3): trailing-return metrics. These were
    # FILTERABLE (screen_field_metadata registers them) but never PROJECTED,
    # so the screener's RETURNS columns always rendered "—". The computed-
    # metrics worker writes them into ``fundamental_metrics`` (592-607
    # instruments as of 2026-06-11). ``return_3y`` is included for forward-
    # compat even though it currently has ZERO rows — the dev universe only
    # carries ~250 daily bars (<1095-day lookback), so the worker skips it;
    # missing metrics are simply absent from the payload (no error path).
    "return_1m",
    "return_3m",
    "return_6m",
    "return_ytd",
    "return_1y",
    "return_3y",
    # L-3 ops follow-up: 30-trading-day annualised realised volatility +
    # per-instrument adjusted-close data-quality flag (1.0 adjusted / 0.0
    # raw-close fallback). Both are SNAPSHOT-period fundamental_metrics rows
    # written by computed_metrics_worker. ``returns_adjustment_quality`` lets
    # the screener badge "unadjusted" instead of silently showing wrong returns.
    "volatility_30d",
    "returns_adjustment_quality",
)

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
    # ── Wave L-5b: intelligence rollup columns (PLAN-0089, migration 035) ────
    # Projected in every screener result so the IB-L5 columns can render
    # without an active filter. Boolean columns (has_active_alert, has_ai_brief)
    # are nullable — NULL means "sync has not yet run for this instrument".
    "news_count_7d",
    "llm_relevance_7d_max",
    "display_relevance_7d_weighted",
    "recent_contradiction_count",
    "has_active_alert",
    "has_ai_brief",
    # Freshness stamp for the intelligence rollup (migration 035). Projected so
    # the IB-L5 stale-data tooltip can show "Intel as of <ts> — N h old" and turn
    # amber when ``now - synced_at`` exceeds the nightly cadence. It is a
    # ``timestamptz`` column; the router serialises ``datetime`` via
    # ``isinstance(v, date)`` (datetime is a subclass of date) → ISO-8601 string.
    # NULL means the rollup has never run for this instrument. NOT sortable /
    # filterable — display-only freshness metadata (so it is intentionally absent
    # from the sort/filter whitelists in the router and query WHERE-clauses).
    "intelligence_rollup_synced_at",
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _screen_statement_timeout_ms() -> int:
    """Return the configured screener statement-timeout ceiling (ms).

    NEW-6 (2026-07-06): the value was previously hardcoded to 8000 in
    ``query_screen``. It now comes from ``Settings.screen_statement_timeout_ms``
    (env ``MARKET_DATA_SCREEN_STATEMENT_TIMEOUT_MS``) so ops can raise the ceiling
    under sustained host contention without a redeploy.

    ``Settings()`` reads the process environment once; the result is memoised for
    the process lifetime (env is fixed per container). Tests that need a different
    ceiling can ``_screen_statement_timeout_ms.cache_clear()`` after patching the
    env, or monkeypatch this function directly.
    """
    return int(Settings().screen_statement_timeout_ms)  # type: ignore[call-arg]


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


async def _fetch_page_extras(
    session: AsyncSession,
    page_ids: list[Any],
    extra_metrics: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Fetch per-instrument display extras for a single result PAGE.

    2026-06-10 frontend-audit fixes (gaps #1/#2/#3). Returns a mapping
    ``str(instrument_id) -> {metric_name: value}`` containing:

    1. The latest value per (instrument, metric) for ``extra_metrics`` — used
       by the POST (filtered) branch to union the ``_KEY_METRICS`` display set
       into rows that previously carried only the filtered metrics.
    2. ``volume`` — the latest 1d OHLCV bar's volume, so the frontend can
       render volume-vs-30d-average (payload previously only shipped
       ``avg_volume_30d`` from the snapshot).
    3. ``high_52w`` / ``low_52w`` — absolute 52-week prices extracted from the
       latest ``technicals_snapshots`` JSONB payload (EODHD ``52WeekHigh`` /
       ``52WeekLow``). The snapshot/key-metrics tables only store the
       DISTANCES (``dist_from_52w_*``); the absolute levels live solely in
       this section table, hence the dedicated lookup.

    PERFORMANCE: every query is bounded to ``instrument_id IN (page_ids)``
    (≤ page limit rows) and rides an existing composite index —
    ``ix_fundamental_metrics_instrument_metric``, the ohlcv_bars PK
    ``(instrument_id, timeframe, bar_date)``, and
    ``ix_technicals_snapshots_instrument_period`` respectively. This mirrors
    the BP-screener500 scoped-subquery approach: never join these against the
    full instruments table.

    FAIL-OPEN: each lookup is individually guarded — these are display-only
    enrichments and must never convert a working screener page into a 500
    (same philosophy as the BP-635 introspection guard above). Failures are
    logged at WARNING with the block name.
    """
    extras: dict[str, dict[str, Any]] = {str(iid): {} for iid in page_ids}
    if not page_ids:
        return extras

    m = FundamentalMetricModel

    # ── 1. Latest key-metric values (POST-branch union, gap #1) ──────────────
    # One UNION-ALL arm per metric, each a single-metric ``DISTINCT ON
    # (instrument_id)`` scan, gives the newest row per (instrument, metric).
    #
    # ── NEW-6 R3 (2026-07-06): why NOT one ``metric IN (...)`` DISTINCT ON ────
    # ROOT CAUSE of the still-504-ing ``sector=Technology + market_cap`` screen
    # (audit 2026-07-06-r1-final-exhaustive-qa.md, NEW-6 PARTIAL): the earlier
    # single-statement form
    #     SELECT DISTINCT ON (instrument_id, metric) …
    #     WHERE instrument_id IN (:page_ids) AND metric IN (:19 key metrics)
    #     ORDER BY instrument_id, metric, as_of_date DESC
    # put TWO ``= ANY`` arrays (19 metrics x 50 page ids) on the covering index
    # ``ix_fundamental_metrics_metric_instr_date_val`` (metric, instrument_id,
    # as_of_date DESC). PostgreSQL's ScalarArrayOp handling re-descends the btree
    # for each of the ~950 (metric, instrument_id) combinations, so the Index
    # Only Scan burned ~13.5 s of pure CPU returning 13,374 history rows only to
    # DISTINCT them down to 828 — the whole screen blew the 8 s statement_timeout
    # (EXPLAIN ANALYZE live: scan 13,530 ms, total 14,316 ms). The
    # market-cap-SORT path (NEW-6 first fix) was fast because the no-metric branch
    # calls ``_fetch_page_extras`` with EMPTY ``extra_metrics`` — it never hit
    # this block; only the metric-FILTER branch (which unions the 19 display
    # metrics) did, so only the sector+metric screen 504'd.
    #
    # FIX: split into one arm per metric. Each arm has a SINGLE scalar
    # ``metric = :m`` leading-column equality + ``instrument_id IN (:page_ids)``,
    # which is the exact fast single-value-leading shape the sort path already
    # rides (~86 ms per metric). PostgreSQL runs the 19 arms as a Parallel Append
    # → end-to-end ~0.6 s (14.3 s -> 0.6 s, ~24x). Result is IDENTICAL: verified
    # live with an ``EXCEPT`` diff of the old vs new form for the
    # ``sector=Technology`` page (828 = 828 rows, symmetric diff 0/0).
    # ``literal(metric_name)`` carries the metric name through so the arms share a
    # (instrument_id, metric, value_numeric) column shape; it is a bound
    # parameter (never string-interpolated) so it is injection-safe.
    if extra_metrics:
        try:
            per_metric_selects: list[Any] = [
                select(
                    m.instrument_id.label("instrument_id"),
                    literal(metric_name).label("metric"),
                    m.value_numeric.label("value_numeric"),
                )
                .where(m.metric == metric_name, m.instrument_id.in_(page_ids))
                .order_by(m.instrument_id, m.as_of_date.desc())
                .distinct(m.instrument_id)
                for metric_name in extra_metrics
            ]
            metric_stmt = union_all(*per_metric_selects)
            metric_rows: Any = await session.execute(metric_stmt)
            for iid, metric_name, value in metric_rows.all():
                if value is not None:
                    extras[str(iid)][metric_name] = value
        except Exception as e:
            _log.warning("screen_page_extras_failed", block="key_metrics", error=str(e))

    # ── 2. Latest daily volume (gap #3) ──────────────────────────────────────
    o = OHLCVBarModel
    try:
        # WHY THE bar_date LOWER BOUND (BP, screener limit=100 cold-cache 504):
        # ohlcv_bars is a TimescaleDB hypertable partitioned into per-time-range
        # chunks. An *unbounded* DISTINCT ON (instrument_id) ORDER BY bar_date
        # DESC has no way to prune chunks, so for each of the up-to-100 page ids
        # the planner index-scans EVERY daily chunk (15 chunks / ~23k rows
        # materialised on the live DB, ~672ms cold) just to throw away all but
        # the newest bar per instrument. The "latest daily bar" is by definition
        # always recent, so we bound bar_date to the last 10 days: that prunes
        # the scan to a single (current) chunk (~tens of ms cold) and is what
        # turns the cold limit=100 page from an intermittent 8s-statement-timeout
        # 504 into a sub-second response. A 10-day window (not 1-2) tolerates
        # long weekends + market holidays so we never miss the latest bar.
        vol_stmt = (
            select(o.instrument_id, o.volume)
            .where(
                o.instrument_id.in_(page_ids),
                o.timeframe == "1d",
                o.bar_date >= func.current_date() - text("interval '10 days'"),
            )
            .order_by(o.instrument_id, o.bar_date.desc())
            .distinct(o.instrument_id)
        )
        vol_rows: Any = await session.execute(vol_stmt)
        for iid, volume in vol_rows.all():
            if volume is not None:
                extras[str(iid)]["volume"] = volume
    except Exception as e:
        _log.warning("screen_page_extras_failed", block="daily_volume", error=str(e))

    # ── 3. Absolute 52-week high/low (gap #2) ────────────────────────────────
    t = TechnicalsSnapshotModel
    try:
        tech_stmt = (
            select(
                t.instrument_id,
                # JSONB ->> returns text; cast to NUMERIC for a typed value.
                t.data["52WeekHigh"].astext.cast(Numeric).label("high_52w"),
                t.data["52WeekLow"].astext.cast(Numeric).label("low_52w"),
            )
            .where(t.instrument_id.in_(page_ids))
            .order_by(t.instrument_id, t.period_end_date.desc())
            .distinct(t.instrument_id)
        )
        tech_rows: Any = await session.execute(tech_stmt)
        for iid, high_52w, low_52w in tech_rows.all():
            if high_52w is not None:
                extras[str(iid)]["high_52w"] = high_52w
            if low_52w is not None:
                extras[str(iid)]["low_52w"] = low_52w
    except Exception as e:
        _log.warning("screen_page_extras_failed", block="technicals_52w", error=str(e))

    return extras


# ── Attribute / snapshot WHERE predicates (shared) ───────────────────────────
# WHY a module-level tuple: the numeric snapshot-range fields are referenced by
# BOTH the metric-filtered branch and (post CAT-B B1 fix) the no-metric branch,
# so they must be defined once. Each entry has matching ``<field>_min`` /
# ``<field>_max`` attributes on ``ScreenFilter`` and a same-named column on
# ``instrument_fundamentals_snapshot``.
_NUMERIC_SNAP_FILTERS: tuple[str, ...] = (
    "avg_volume_30d",
    "eps_ttm",
    "free_cash_flow",
    "fcf_margin",
    "interest_coverage",
    "net_debt_to_ebitda",
    # ── Wave L-4a snapshot fields (PLAN-0089) ────────────────────────────────
    "analyst_target_price",
    "analyst_consensus_rating",
    "institutional_ownership_pct",
    "short_percent",
    # Wave L-4b: trailing-90d insider net dollar flow (sortable + filterable).
    "insider_net_buy_90d",
    # ── Wave L-5b: intelligence rollup numeric fields (PLAN-0089) ─────────────
    "news_count_7d",
    "llm_relevance_7d_max",
    "display_relevance_7d_weighted",
    "recent_contradiction_count",
)


def _filters_need_snapshot(filters: list[ScreenFilter], snap_fields_available: tuple[str, ...]) -> bool:
    """Return True when ANY filter carries a snapshot-column predicate.

    Used by the no-metric branch (CAT-B B1 fix) to decide whether to JOIN
    ``instrument_fundamentals_snapshot`` before applying the snapshot WHERE
    predicates. The metric-filtered branch always LEFT-JOINs the snapshot for
    projection, so it never needs this guard.
    """
    for snap_field in _NUMERIC_SNAP_FILTERS:
        if snap_field not in snap_fields_available:
            continue
        if any(getattr(f, f"{snap_field}_min", None) is not None for f in filters):
            return True
        if any(getattr(f, f"{snap_field}_max", None) is not None for f in filters):
            return True
    if any(f.credit_ratings for f in filters) and "credit_rating" in snap_fields_available:
        return True
    for filter_attr, snap_col in (
        ("next_earnings_within_days", "next_earnings_date"),
        ("next_dividend_within_days", "next_dividend_date"),
    ):
        if snap_col not in snap_fields_available:
            continue
        if any(getattr(f, filter_attr, None) is not None for f in filters):
            return True
    for bool_field in ("has_active_alert", "has_ai_brief"):
        if bool_field not in snap_fields_available:
            continue
        if any(getattr(f, bool_field, None) is not None for f in filters):
            return True
    return False


def _apply_attribute_predicates(
    stmt: Any,
    instr: Any,
    snap: Any,
    filters: list[ScreenFilter],
    snap_fields_available: tuple[str, ...],
) -> Any:
    """Apply all non-metric (attribute + snapshot) WHERE predicates to ``stmt``.

    Extracted (2026-06-28, CAT-B B1) so BOTH the metric-filtered branch and the
    no-metric branch share ONE implementation. ``stmt`` must already have
    ``instr`` available and — when any snapshot predicate is present — ``snap``
    joined (callers use ``_filters_need_snapshot`` to decide). Predicates are
    AND-combined across all filter entries; multi-entry fields collapse to the
    first non-None value (mirrors the historical L-1/L-2 behaviour).
    """
    # Sector / industry — GICS taxonomy (industry is more selective than sector).
    for sv in (f.sector for f in filters if f.sector is not None):
        stmt = stmt.where(instr.sector == sv)
    for iv in (f.industry for f in filters if f.industry is not None):
        stmt = stmt.where(instr.industry == iv)
    # L-1: instrument-attribute filters (country / exchange / has_* flags).
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

    # ── Wave L-2/L-4: snapshot numeric range predicates ──────────────────────
    # ``NULL >= :v`` → UNKNOWN, so instruments without a snapshot row are
    # correctly dropped whenever any snapshot predicate is active. PLAN-0103 W16
    # (BP-635): skip predicates against columns the deployed schema lacks.
    for snap_field in _NUMERIC_SNAP_FILTERS:
        if snap_field not in snap_fields_available:
            continue
        min_val = next(
            (getattr(f, f"{snap_field}_min") for f in filters if getattr(f, f"{snap_field}_min", None) is not None),
            None,
        )
        max_val = next(
            (getattr(f, f"{snap_field}_max") for f in filters if getattr(f, f"{snap_field}_max", None) is not None),
            None,
        )
        if min_val is not None:
            stmt = stmt.where(getattr(snap, snap_field) >= min_val)
        if max_val is not None:
            stmt = stmt.where(getattr(snap, snap_field) <= max_val)
    # credit_ratings: IN predicate across non-empty tuple.
    ratings = next((f.credit_ratings for f in filters if f.credit_ratings), None)
    if ratings and "credit_rating" in snap_fields_available:
        stmt = stmt.where(snap.credit_rating.in_(list(ratings)))

    # ── Wave L-5c: calendar (date) "within next N days" window predicates ─────
    for filter_attr, snap_col in (
        ("next_earnings_within_days", "next_earnings_date"),
        ("next_dividend_within_days", "next_dividend_date"),
    ):
        if snap_col not in snap_fields_available:
            continue
        days = next(
            (getattr(f, filter_attr) for f in filters if getattr(f, filter_attr, None) is not None),
            None,
        )
        if days is not None:
            stmt = stmt.where(getattr(snap, snap_col) >= func.current_date())
            stmt = stmt.where(
                getattr(snap, snap_col)
                <= func.current_date() + text(":n_days * INTERVAL '1 day'").bindparams(n_days=days)
            )

    # ── Wave L-5b: boolean equality predicates (has_active_alert / has_ai_brief) ──
    for bool_field in ("has_active_alert", "has_ai_brief"):
        if bool_field not in snap_fields_available:
            continue
        val = next(
            (getattr(f, bool_field) for f in filters if getattr(f, bool_field, None) is not None),
            None,
        )
        if val is not None:
            stmt = stmt.where(getattr(snap, bool_field) == val)

    return stmt


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
    # Apply the configured statement timeout for the duration of this read
    # transaction. SET LOCAL is session-safe for pooled connections (reverts at
    # transaction end). The timeout value is an ``int`` from settings — never user
    # input — so interpolating it into the SET statement is injection-safe
    # (statement_timeout is a GUC that cannot be parameterised via bind params).
    timeout_ms = _screen_statement_timeout_ms()
    await session.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}'"))

    # ── Default ORDER BY (2026-06-12, chat-eval root cause #5) ───────────────
    # WHY: before this, an absent ``sort_by`` left BOTH branches sorting by
    # ``symbol`` (alphabetical) and then truncating at ``limit`` — so a
    # "top 5 by market cap" request (no explicit sort) returned the first 5
    # tickers alphabetically (CRM, IBM, …) rather than the genuine top-5
    # (GOOGL/AVGO/META). The LLM then "sorted" only the 20 rows it happened to
    # see, producing a confidently-WRONG ranked list (``iter3_top5_tech_marketcap``).
    #
    # Fix: when the caller does not pin a sort, default to the PRIMARY FILTER
    # METRIC descending when a metric filter is present (so "revenue_growth_yoy
    # ≥ 0.2, biggest first" works without an explicit sort), otherwise to
    # ``market_capitalization`` descending (the natural "biggest companies first"
    # default). The ORDER BY is applied in SQL BEFORE the LIMIT so the true
    # top-N is always in the rendered page. ``sort_by`` is still resolved through
    # ORM attributes / validated subquery columns below — never interpolated.
    if sort_by is None:
        primary_metric = next((f.metric for f in filters if f.metric), None)
        sort_by = primary_metric if primary_metric is not None else "market_capitalization"
        # A default-applied sort is "biggest/highest first" — descending.
        sort_order = "desc"

    instr = InstrumentModel
    snap = InstrumentFundamentalsSnapshotModel

    # PLAN-0103 W16 (BP-635): only project snapshot columns the deployed schema
    # actually has. See ``_resolve_available_snap_fields`` for rationale.
    snap_fields_available: tuple[str, ...] = await _resolve_available_snap_fields(session)

    # ── CAT-B B1 (2026-06-28): split metric-bearing vs attribute-only filters ─
    # ``metric`` is now optional, so a filter may carry ONLY an instrument
    # attribute (sector/industry/country/exchange) or a snapshot range. When NO
    # filter carries a ``fundamental_metrics`` metric we route through the
    # no-metric branch below — which applies the attribute/snapshot WHERE
    # predicates against ``instruments`` and still honours ``sort_by`` (e.g.
    # ``market_capitalization``). Previously the API rejected attribute-only
    # filters with a 422; even when they slipped through, the metric-filtered
    # branch's ``base = filter_subqueries[0]`` would IndexError on an empty list.
    metric_filters = [f for f in filters if f.metric is not None]

    if not metric_filters:
        # No metric thresholds — return instruments matching the ATTRIBUTE /
        # SNAPSHOT predicates (or ALL instruments when ``filters`` is empty),
        # sorted by ``sort_by`` (default ``market_capitalization`` DESC). The
        # common display metrics are populated via LEFT JOIN so the screener
        # table shows real values instead of "—" in the default view.
        # WHY LEFT JOIN (not INNER): we must not exclude instruments that lack
        # some metrics (e.g. crypto instruments have no P/E). LEFT JOIN returns
        # NULL for missing metrics, which the frontend renders as "—".
        #
        # Whether the attribute/snapshot predicates need the snapshot JOIN:
        attr_needs_snap = _filters_need_snapshot(filters, snap_fields_available)
        m = FundamentalMetricModel

        # WHY these metrics: the columns displayed in the screener table's
        # default (no-filter) view — see ``_KEY_METRICS`` (module level) for
        # the catalogue rationale. 2026-06-10: now shared with the POST branch
        # so filtered results carry the same display set (audit gap #1).
        key_metrics = list(_KEY_METRICS)

        # ── PERFORMANCE FIX (2026-06-09, BP-screener500) ─────────────────────
        # Original implementation joined 10 LATERAL "latest per metric"
        # subqueries against the full instruments table BEFORE the LIMIT was
        # applied — `count(*) OVER ()` + ORDER BY symbol forced each subquery
        # to scan its full ~23k-row partition of fundamental_metrics (26M rows
        # total). The query consistently hit the 8 s statement_timeout.
        #
        # Fix: 3-step query plan
        #   1. SELECT paged instrument IDs (uses (instruments) PK index, cheap).
        #   2. SELECT COUNT(*) FROM instruments separately (replaces the
        #      window-COUNT — also indexed and fast).
        #   3. Build the metric LEFT JOINs scoped to `instrument_id IN (page_ids)`
        #      so each LATERAL subquery scans 20 rows x 10 metrics instead of
        #      660 x 10. Index ix_fundamental_metrics_instrument_metric
        #      (instrument_id, metric, as_of_date) makes this a 200-row index
        #      seek instead of a 230k-row scan.
        # ── Page-selection ORDER BY (2026-06-12, chat-eval root cause #5) ────
        # WHY this is the heart of the "top-N" fix: the LIMIT/OFFSET that defines
        # which instruments make the page is applied HERE. Previously this query
        # ALWAYS ordered by ``symbol`` and ignored ``sort_by`` entirely, so a
        # "top 5 by market cap" (no filters → this branch) returned the first 5
        # tickers alphabetically, NOT the 5 largest. The metric sort that the
        # SELECT below applied was cosmetic — it only reordered the already-wrong
        # alphabetical page. We now resolve the requested ``sort_by`` to a
        # sortable expression and order the PAGE query by it before LIMIT.
        #
        # ``sort_by`` is one of:
        #   • ``ticker`` / ``name`` — direct instruments columns
        #   • a snapshot column     — LEFT JOIN instrument_fundamentals_snapshot
        #   • a fundamental_metrics metric (default ``market_capitalization``,
        #     plus any ``_KEY_METRICS`` entry) — LEFT JOIN the latest value
        # Anything unrecognised falls back to ``symbol`` ASC (the prior default)
        # so an unknown sort key can never 500 the default screener view.
        page_q = select(instr.id, instr.symbol, instr.name, instr.exchange, instr.sector)

        # CAT-B B1: track whether ``snap`` is already JOINed so we never double-
        # join it (once for a snapshot sort, once for a snapshot WHERE predicate).
        page_has_snap_join = False

        page_sort_col: Any
        if sort_by == "ticker":
            page_sort_col = instr.symbol
        elif sort_by == "name":
            page_sort_col = instr.name
        elif sort_by in snap_fields_available:
            # Snapshot column — LEFT JOIN so instruments without a snapshot row
            # still appear (NULL sorts last via nullslast below).
            page_q = page_q.outerjoin(snap, instr.id == snap.instrument_id)
            page_has_snap_join = True
            page_sort_col = getattr(snap, sort_by)
        elif sort_by is not None and sort_by != "current_price":
            # Treat as a fundamental_metrics metric: LEFT JOIN its latest value.
            # current_price (quotes.last) is intentionally NOT a page-sort target
            # here — it is a display-only enrichment, so it falls through to the
            # symbol default rather than driving which instruments make the page.
            #
            # ── PERFORMANCE FIX (2026-06-12, post-2d71ba1ae regression) ──────────
            # The previous shape built ``page_sort_latest`` as an un-scoped
            #   SELECT instrument_id, MAX(as_of_date) FROM fundamental_metrics
            #   WHERE metric = :m GROUP BY instrument_id
            # and self-JOINed it back for the value. Because the page IDs are not
            # yet known (this very subquery selects them), the GROUP BY had to
            # aggregate the ENTIRE ``metric = 'market_capitalization'`` partition
            # (one row per instrument per snapshot date) BEFORE the LIMIT — exactly
            # the full-scan-before-LIMIT the earlier 3-step fix (afde005a9 /
            # c61e86c0b) removed for the DISPLAY joins. On a cold page cache the
            # planner picked a nested-loop and blew the 8 s statement_timeout →
            # 504 → ``screen_universe`` transport_error (audit Theme B).
            #
            # New shape: a single ``DISTINCT ON (instrument_id)`` scan ordered by
            # ``(instrument_id, as_of_date DESC)``. This drops the aggregate + the
            # self-JOIN (one index pass instead of two), and is backed by the
            # covering index ``ix_fundamental_metrics_metric_instr_date_val``
            # (migration 038): ``(metric, instrument_id, as_of_date DESC) INCLUDE
            # (value_numeric)`` — so the WHERE-metric filter + per-instrument
            # latest pick + value read are an INDEX-ONLY scan. The outer ORDER BY
            # value DESC + LIMIT then sorts only the deduplicated latest-per-
            # instrument set (one row per instrument), never the full history.
            #
            # CORRECTNESS is unchanged: DISTINCT ON (instrument_id) with
            # ORDER BY instrument_id, as_of_date DESC returns the SAME latest row
            # per instrument the MAX(as_of_date) self-JOIN did, so "top 5 by
            # market cap" still ranks on each instrument's most-recent value
            # (GOOGL/AVGO/META-class top-5, never the alphabetical CRM/IBM).
            sort_metric = FundamentalMetricModel
            sort_val_sq = (
                select(
                    sort_metric.instrument_id.label("instrument_id"),
                    sort_metric.value_numeric.label("value_numeric"),
                )
                .where(sort_metric.metric == sort_by)
                # DISTINCT ON keeps the first row per instrument in the ORDER BY;
                # as_of_date DESC makes that "first" row the latest snapshot.
                .order_by(sort_metric.instrument_id, sort_metric.as_of_date.desc())
                .distinct(sort_metric.instrument_id)
                .subquery(name="page_sort_val")
            )
            page_q = page_q.outerjoin(sort_val_sq, instr.id == sort_val_sq.c.instrument_id)
            page_sort_col = sort_val_sq.c.value_numeric
        else:
            page_sort_col = None

        # ── CAT-B B1: apply attribute / snapshot WHERE predicates ────────────
        # When the no-metric branch is reached via attribute-only filters
        # (e.g. ``sector="Technology"``), restrict the page to matching rows.
        # JOIN ``snap`` first if a snapshot predicate is present and it is not
        # already joined for a snapshot sort. Empty ``filters`` → no predicates
        # (the historical "return ALL instruments" default is preserved).
        if attr_needs_snap and not page_has_snap_join:
            page_q = page_q.outerjoin(snap, instr.id == snap.instrument_id)
            page_has_snap_join = True
        if filters:
            page_q = _apply_attribute_predicates(page_q, instr, snap, filters, snap_fields_available)

        if page_sort_col is not None:
            # nullslast(): instruments missing the sort metric sort to the END in
            # BOTH directions (a NULL market cap must never beat a real one).
            # Secondary symbol sort gives a stable, deterministic tie-break.
            page_order = page_sort_col.desc().nullslast() if sort_order == "desc" else page_sort_col.asc().nullslast()
            page_q = page_q.order_by(page_order, instr.symbol.asc())
        else:
            page_q = page_q.order_by(instr.symbol.asc())

        page_q = page_q.offset(offset).limit(limit)
        page_rows = (await session.execute(page_q)).all()
        if not page_rows:
            return [], 0
        # Preserve the page query's sort order through to the response: page_ids
        # is consumed below to scope the metric subqueries, and the final result
        # is re-sorted using this same key so the rendered order matches.
        page_ids = [r.id for r in page_rows]

        # CAT-B B1: the total MUST reflect the same attribute/snapshot
        # predicates as the page query, otherwise pagination over a filtered
        # universe reports the full-table count. Mirror the JOIN + WHEREs.
        total_q = select(func.count()).select_from(instr)
        if attr_needs_snap:
            total_q = total_q.outerjoin(snap, instr.id == snap.instrument_id)
        if filters:
            total_q = _apply_attribute_predicates(total_q, instr, snap, filters, snap_fields_available)
        total_row = await session.execute(total_q)
        total = int(total_row.scalar_one())

        def _latest_metric_sq(metric_name: str, alias: str) -> Any:
            """Subquery: latest value for metric_name per paged instrument.

            NEW-6 (2026-07-06): rewritten from a ``GROUP BY MAX(as_of_date)`` +
            self-JOIN to a single ``DISTINCT ON (instrument_id)`` scan. Scoped to
            ``instrument_id IN page_ids`` (≤ limit rows) it rides
            ``ix_fundamental_metrics_metric_instr_date_val`` (metric, instrument_id,
            as_of_date DESC) INCLUDE (value_numeric) as one bounded index pass —
            one row per paged instrument, no whole-partition aggregate and no
            second self-JOIN pass. Result is identical (latest value per instrument
            for this metric) — see the metric-filter branch below for the live
            result-equivalence proof of the same rewrite.
            """
            return (
                select(
                    m.instrument_id.label("instrument_id"),
                    m.value_numeric.label("value_numeric"),
                )
                .where(m.metric == metric_name, m.instrument_id.in_(page_ids))
                .order_by(m.instrument_id, m.as_of_date.desc())
                .distinct(m.instrument_id)
                .subquery(name=alias)
            )

        key_sqs = {name: _latest_metric_sq(name, f"km_{name}") for name in key_metrics}
        q = QuoteModel

        select_cols: list[Any] = [
            instr.id.label("instrument_id"),
            instr.symbol.label("ticker"),
            instr.name.label("name"),
            instr.exchange.label("exchange"),
            instr.sector.label("sector"),
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

        # NB: no SQL ORDER BY here — the page query above already established
        # the correct sorted top-N order (e.g. market cap DESC). We re-sort the
        # enriched rows in Python by their position in ``page_ids`` so the
        # rendered order matches the page selection exactly (a SQL ORDER BY on
        # this enrichment SELECT would re-sort alphabetically and silently undo
        # the metric sort — the original "top-N" bug).
        stmt = select(*select_cols).where(instr.id.in_(page_ids))
        for sq in key_sqs.values():
            stmt = stmt.outerjoin(sq, instr.id == sq.c.instrument_id)
        stmt = stmt.outerjoin(snap, instr.id == snap.instrument_id)
        stmt = stmt.outerjoin(q, instr.id == q.instrument_id)

        result: Any = await session.execute(stmt)
        rows = result.all()
        if not rows:
            return [], total

        # Restore the page query's sort order (rows come back in arbitrary order
        # because the IN (...) lookup is unordered).
        _page_rank = {iid: idx for idx, iid in enumerate(page_ids)}
        rows = sorted(rows, key=lambda r: _page_rank.get(r.instrument_id, len(page_ids)))

        # 2026-06-10: page-bounded extras — latest daily volume + absolute
        # 52-week high/low (key metrics already projected via the LATERALs
        # above, so ``extra_metrics`` is empty here).
        extras = await _fetch_page_extras(session, page_ids, ())

        return [
            ScreenResult(
                instrument_id=str(row.instrument_id),
                ticker=row.ticker,
                name=row.name,
                exchange=row.exchange,
                sector=row.sector,
                metrics={
                    # WHY extras first: explicit projections below (key metrics,
                    # current_price, snap fields) must win on any name collision.
                    **extras.get(str(row.instrument_id), {}),
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

    # Build a subquery for each METRIC-bearing filter: latest value per
    # instrument for that metric. CAT-B B1: ``filters`` may now also contain
    # attribute-only entries (``metric=None``) — those carry no metric subquery
    # and are applied purely as WHERE predicates via ``_apply_attribute_predicates``
    # below, so we iterate ``metric_filters`` (not ``filters``) here. The branch
    # is only reached when ``metric_filters`` is non-empty.
    filter_subqueries: list[Any] = []
    metric_columns: list[tuple[str, Any]] = []

    for i, f in enumerate(metric_filters):
        alias = f"f{i}"
        # ``metric_filters`` is filtered to non-None metrics; assert narrows the
        # type for mypy so ``metric_columns`` stays ``list[tuple[str, Any]]``.
        assert f.metric is not None
        metric_name = f.metric

        # ── NEW-6 (2026-07-06): latest value per instrument via DISTINCT ON ──────
        # ROOT CAUSE of the ~114 s → statement-timeout screener (audit
        # 2026-07-06-r1-final-exhaustive-qa.md): this per-filter subquery was a
        # whole-partition ``GROUP BY instrument_id MAX(as_of_date)`` aggregate
        # self-JOINed back to read the value at that date. ``EXPLAIN (ANALYZE)`` on
        # the live DB showed the GroupAggregate scanning the entire ``metric = X``
        # partition (~14,183 index rows) in 7,030 ms with 4,689 heap fetches, plus
        # ~1,700 ms planning on stale stats — the whole screen blew the 8 s ceiling.
        #
        # DISTINCT ON (instrument_id) ORDER BY (instrument_id, as_of_date DESC) lets
        # the planner use a SkipScan on the covering index
        # ``ix_fundamental_metrics_metric_instr_date_val`` (metric, instrument_id,
        # as_of_date DESC) INCLUDE (value_numeric): it seeks the SINGLE latest row
        # per instrument (~615 rows) instead of aggregating all 14 k, dropping the
        # branch to ~1.2 s and heap fetches to ~44. Result-equivalence was verified
        # live: OLD vs NEW returned the identical instrument+value set for a
        # ``market_capitalization >= 1e9`` screen (612 = 612, symmetric diff 0/0).
        #
        # SEMANTICS: predicates apply to each instrument's latest row.
        #   • period_type filter: kept as an outer predicate against the latest
        #     row's ``period_type`` — matching the old "latest date, then require
        #     this period_type" behaviour (an instrument whose latest row is a
        #     different period_type is still excluded). We carry ``period_type``
        #     out of the DISTINCT ON so it can be filtered without a re-scan.
        #   • min/max value: applied to the latest row's ``value_numeric``.
        latest_sq = (
            select(
                m.instrument_id.label("instrument_id"),
                m.value_numeric.label("value_numeric"),
                m.period_type.label("period_type"),
            )
            .where(m.metric == metric_name)
            .order_by(m.instrument_id, m.as_of_date.desc())
            .distinct(m.instrument_id)
            .subquery(name=f"{alias}_latest")
        )

        value_sq = select(
            latest_sq.c.instrument_id.label("instrument_id"),
            latest_sq.c.value_numeric.label("value_numeric"),
        )

        conditions = []
        if f.period_type is not None:
            conditions.append(latest_sq.c.period_type == f.period_type)
        if f.min_value is not None:
            conditions.append(latest_sq.c.value_numeric >= f.min_value)
        if f.max_value is not None:
            conditions.append(latest_sq.c.value_numeric <= f.max_value)
        if conditions:
            value_sq = value_sq.where(and_(*conditions))

        sq = value_sq.subquery(name=alias)
        filter_subqueries.append(sq)
        metric_columns.append((metric_name, sq.c.value_numeric))

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

    # ── Attribute + snapshot WHERE predicates (shared helper, CAT-B B1) ──────
    # Sector/industry/country/exchange/has_* + all snapshot numeric/date/bool
    # predicates. ``snap`` is already LEFT-JOINed above so every snapshot
    # predicate is valid. ``numeric_snap_filters`` (used by the sort whitelist
    # below) now aliases the module-level tuple the helper shares.
    numeric_snap_filters: tuple[str, ...] = _NUMERIC_SNAP_FILTERS
    stmt = _apply_attribute_predicates(stmt, instr, snap, filters, snap_fields_available)

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
    elif sort_by in {
        # Wave L-5b: intelligence rollup snapshot columns (sortable).
        "news_count_7d",
        "llm_relevance_7d_max",
        "display_relevance_7d_weighted",
        "recent_contradiction_count",
        "has_active_alert",
        "has_ai_brief",
    }:
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

    # ── 2026-06-10 (frontend audit gap #1, HIGHEST LEVERAGE) ─────────────────
    # Union the ``_KEY_METRICS`` display projection into the filtered branch.
    # Previously this branch projected ONLY the metrics the user filtered on,
    # so applying ANY filter blanked MKT CAP / P/E / CHG% / REV in the UI.
    # The lookup is bounded to this page's instrument IDs (≤ limit rows) —
    # same scoped approach as the GET branch post-BP-screener500. Metrics that
    # are already projected by a filter subquery are excluded so the filter's
    # period_type-scoped value always wins.
    filtered_metric_names = {mn for mn, _ in metric_columns}
    missing_key_metrics = tuple(km for km in _KEY_METRICS if km not in filtered_metric_names)
    page_ids = [row.instrument_id for row in rows]
    extras = await _fetch_page_extras(session, page_ids, missing_key_metrics)

    results = []
    for row in rows:
        # WHY extras seed the dict: explicit projections below (filter metrics,
        # snap fields, current_price) must win on any name collision.
        metrics_dict: dict[str, Any] = dict(extras.get(str(row.instrument_id), {}))
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
