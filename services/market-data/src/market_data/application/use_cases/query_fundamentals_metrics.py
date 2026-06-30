"""Unified fundamentals metric query use case (PLAN-0104 W32).

WHY a new use case (additive, alongside ``GetFundamentalsHistoryUseCase``):
the legacy history endpoint returns a fixed 6-column projection (revenue,
gross_profit, net_income, eps, pe_ratio, market_cap). The rag-chat LLM
increasingly asks for richer metrics — gross margin, operating margin,
forward P/E, PEG, FCF yield, consensus EPS for current/next year, EV/EBITDA
— that all derive from the same underlying ``FundamentalsRecord`` rows but
were never surfaced. Rather than adding N narrow per-metric tools (and
bloating the LLM's tool-planning surface), this use case parameterises the
projection: the caller declares ``metrics=["revenue","gross_margin",
"forward_pe","consensus_eps_curr_year"]`` and gets back a single typed
response.

Backwards-compatibility: the legacy ``GetFundamentalsHistoryUseCase`` keeps
its exact contract — this is an additive sibling, NOT a refactor.

Coverage flags: every requested metric carries an ``"ok" | "partial" |
"missing"`` flag so the LLM can decide whether to quote a trend (ok),
caveat it (partial), or refuse (missing) instead of fabricating from a
half-empty series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

log = structlog.get_logger(__name__)


# ── Canonical metric registry ────────────────────────────────────────────────
#
# Each entry maps OUR canonical metric name to:
#   * the EODHD section it lives in (or "derived"),
#   * the JSONB key aliases to try (first match wins), and
#   * for derived metrics, the computation hook.
#
# WHY align names with metric_extractor.py: that file is the SCHEMA the
# screener/backfill speaks. Aligning the LLM-visible metric vocabulary on
# the same names means the screener prompt and the new query_fundamentals
# tool share one mental model.


# ── Per-period (flow) metrics — read from INCOME_STATEMENT / EARNINGS_HISTORY
_PER_PERIOD_METRICS: dict[str, tuple[str, tuple[str, ...]]] = {
    # Top line + bottom line — sourced from income_statement section.
    "revenue": ("income_statement", ("totalRevenue", "revenue", "Revenue")),
    "gross_profit": ("income_statement", ("grossProfit", "gross_profit", "GrossProfit")),
    "operating_income": ("income_statement", ("operatingIncome", "operating_income", "OperatingIncome")),
    "net_income": ("income_statement", ("netIncome", "net_income", "NetIncome")),
    "ebit": ("income_statement", ("ebit", "EBIT")),
    "ebitda": ("income_statement", ("ebitda", "EBITDA")),
    "cost_of_revenue": ("income_statement", ("costOfRevenue", "cost_of_revenue", "CostOfRevenue")),
    "research_development": ("income_statement", ("researchDevelopment", "ResearchDevelopment")),
    # EPS sourced from earnings_history (preferred) with income_statement fallback.
    "eps": ("earnings_history", ("epsActual", "eps", "EPS")),
    # Cash flow (annual EODHD contract; values can be missing for quarterly rows).
    "operating_cash_flow": (
        "cash_flow",
        ("totalCashFromOperatingActivities", "operatingCashFlow", "OperatingCashFlow"),
    ),
    "capital_expenditures": ("cash_flow", ("capitalExpenditures", "CapitalExpenditures")),
    "free_cash_flow": ("cash_flow", ("freeCashFlow", "FreeCashFlow")),
}

# ── Derived (per-period) metrics — computed from PER_PERIOD raw values
# Each value: (dependencies, computation lambda). Returned None if any dep None.
_DERIVED_PER_PERIOD: dict[str, tuple[tuple[str, ...], Any]] = {
    "gross_margin": (("gross_profit", "revenue"), lambda gp, rev: gp / rev if rev else None),
    "operating_margin": (("operating_income", "revenue"), lambda oi, rev: oi / rev if rev else None),
    "net_margin": (("net_income", "revenue"), lambda ni, rev: ni / rev if rev else None),
    "ebitda_margin": (("ebitda", "revenue"), lambda eb, rev: eb / rev if rev else None),
    # FCF yield is computed against market cap (a SNAPSHOT field). The dependency
    # is therefore mixed — the resolver handles the snapshot lookup downstream.
}


# ── Snapshot (TTM/live) metrics — read from HIGHLIGHTS section
_SNAPSHOT_METRICS: dict[str, tuple[str, ...]] = {
    # Valuation ratios
    "pe_ratio": ("PERatio", "peRatio"),
    "forward_pe": ("ForwardPE", "forwardPE"),
    "peg_ratio": ("PEGRatio", "pegRatio"),
    "ev_ebitda": ("EVToEBITDA", "EnterpriseValueEbitda", "enterpriseValueEbitda"),
    "ev_revenue": ("EnterpriseValueRevenue", "enterpriseValueRevenue"),
    "price_to_book": ("PriceBookMRQ", "priceBookMRQ"),
    "price_to_sales_ttm": ("PriceSalesTTM", "priceSalesTTM"),
    # Snapshot scalars
    "market_cap": ("MarketCapitalization", "marketCapitalization"),
    "ebitda_ttm": ("EBITDA", "EBITDAttm"),
    "revenue_ttm": ("RevenueTTM", "revenueTTM"),
    "gross_profit_ttm": ("GrossProfitTTM", "grossProfitTTM"),
    "eps_ttm": ("EarningsShare", "EPS", "earningsShare"),
    "diluted_eps_ttm": ("DilutedEpsTTM", "dilutedEpsTTM"),
    "dividend_yield": ("DividendYield", "dividendYield"),
    "dividend_share": ("DividendShare", "dividendShare"),
    "book_value": ("BookValue", "bookValue"),
    "roe_ttm": ("ReturnOnEquityTTM", "returnOnEquityTTM"),
    "roa_ttm": ("ReturnOnAssetsTTM", "returnOnAssetsTTM"),
    "operating_margin_ttm": ("OperatingMarginTTM", "operatingMarginTTM"),
    "profit_margin_ttm": ("ProfitMargin", "profitMargin"),
    "quarterly_revenue_growth_yoy": ("QuarterlyRevenueGrowthYOY", "quarterlyRevenueGrowthYOY"),
    "quarterly_earnings_growth_yoy": ("QuarterlyEarningsGrowthYOY", "quarterlyEarningsGrowthYOY"),
    # Consensus / forward estimates (EODHD HIGHLIGHTS scalars)
    "consensus_eps_curr_quarter": ("EPSEstimateCurrentQuarter", "epsEstimateCurrentQuarter"),
    "consensus_eps_next_quarter": ("EPSEstimateNextQuarter", "epsEstimateNextQuarter"),
    "consensus_eps_curr_year": ("EPSEstimateCurrentYear", "epsEstimateCurrentYear"),
    "consensus_eps_next_year": ("EPSEstimateNextYear", "epsEstimateNextYear"),
    "wall_street_target_price": ("WallStreetTargetPrice", "wallStreetTargetPrice"),
}

# ── Derived snapshot metrics (computed from HIGHLIGHTS scalars)
# fcf_yield ≈ free_cash_flow_ttm / market_cap — but FCF TTM is not a single
# scalar in EODHD's HIGHLIGHTS section. Approximate from the most recent
# annual CASH_FLOW row when available.
_DERIVED_SNAPSHOT: tuple[str, ...] = ("fcf_yield",)


# Union of every metric name the tool understands.
KNOWN_METRICS: frozenset[str] = frozenset(
    set(_PER_PERIOD_METRICS) | set(_DERIVED_PER_PERIOD) | set(_SNAPSHOT_METRICS) | set(_DERIVED_SNAPSHOT)
)


CoverageFlag = Literal["ok", "partial", "missing"]


@dataclass(frozen=True, slots=True)
class _MetricSeries:
    """Raw extracted series for a single metric across periods + snapshot."""

    per_period: dict[str, float | None]  # period_label → value
    snapshot: float | None


def _safe_float(value: Any) -> float | None:
    """Convert a value to ``float``. Returns ``None`` on empty / non-numeric."""
    if value is None or value == "" or value == "None":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_alias(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    """First-match-wins alias lookup against an EODHD JSONB blob."""
    for key in aliases:
        if key in data:
            return data[key]
    return None


class QueryFundamentalsUseCase:
    """Parameterised fundamentals projection over a metric registry (W32).

    The use case fetches at most four sections (INCOME_STATEMENT,
    EARNINGS_HISTORY, CASH_FLOW, HIGHLIGHTS) ONCE, then projects them into
    the caller-requested metric set. Sections with no requested metrics are
    skipped, so the worst-case query touches exactly the sections it needs.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: UUID,
        metrics: list[str],
        *,
        periods: int = 8,
        period_type: str = "quarterly",
        include_snapshot: bool = True,
    ) -> dict[str, Any]:
        """Return the unified metric projection.

        Response shape::

            {
              "metrics_by_period": [
                {"period_end": "2026-03-31", "period_label": "Q2 FY2026",
                 "revenue": 95e9, "gross_margin": 0.44, ...},
                ...
              ],
              "snapshot": {"forward_pe": 27.8, "peg_ratio": 2.15, ...} | None,
              "coverage": {"revenue": "ok", "forward_pe": "missing", ...}
            }

        ``coverage`` semantics:
          * ``ok``     — every requested period had this metric populated.
          * ``partial`` — at least one period populated, at least one missing.
          * ``missing`` — every requested period missing (and the snapshot
            value, if applicable, was also None).

        Unknown metric names are echoed in ``coverage`` as ``"missing"`` rather
        than rejected — the LLM may speculate metric names the registry has
        not yet been taught, and a silent ``"missing"`` is friendlier than a
        500.
        """
        from market_data.application.use_cases.get_fundamentals_history import is_future_placeholder_row
        from market_data.domain.enums import FundamentalsSection, PeriodType

        if not metrics:
            return {"metrics_by_period": [], "snapshot": None, "coverage": {}}

        # PLAN-0104 W39: when the caller asks for ``revenue`` (a very common
        # trend question), auto-include the three margin derivations so the
        # LLM can compose a "margin trend" answer without an extra round-trip.
        # WHY only when revenue is requested: revenue is the denominator for
        # all three margins, so we know the row will already need to load it.
        # WHY only add margins (not all derived): a "revenue trend" question
        # naturally invites margin context, but auto-loading EPS / ratios on
        # every revenue call would bloat the response.  We skip the auto-add
        # if the caller already passed any of the three explicitly.
        auto_margins: list[str] = []
        if "revenue" in metrics:
            for derived in ("gross_margin", "operating_margin", "net_margin"):
                if derived not in metrics:
                    auto_margins.append(derived)
        # Cheap copy so the caller's list is not mutated under their feet.
        metrics = list(metrics) + auto_margins

        period_type_norm = (period_type or "quarterly").upper()
        if period_type_norm not in {"QUARTERLY", "ANNUAL"}:
            period_type_norm = "QUARTERLY"
        selected_period_type = PeriodType(period_type_norm)

        iid_str = str(instrument_id)
        instrument = await self._uow.instruments_read.find_by_id(iid_str)
        ticker = instrument.symbol if instrument is not None else iid_str
        fye = instrument.fiscal_year_end_month if instrument is not None else None

        # Determine which sections we actually need to fetch.
        needed_per_period = {m for m in metrics if m in _PER_PERIOD_METRICS}
        needed_derived = {m for m in metrics if m in _DERIVED_PER_PERIOD}
        # Derived metrics require their raw dependencies to be loaded too.
        for m in needed_derived:
            deps = _DERIVED_PER_PERIOD[m][0]
            for d in deps:
                if d in _PER_PERIOD_METRICS:
                    needed_per_period.add(d)
        needed_snapshot = {m for m in metrics if m in _SNAPSHOT_METRICS}
        needed_derived_snapshot = {m for m in metrics if m in _DERIVED_SNAPSHOT}
        # fcf_yield depends on market_cap + cash_flow.
        if "fcf_yield" in needed_derived_snapshot:
            needed_snapshot.add("market_cap")

        sections_to_fetch: set[FundamentalsSection] = set()
        for raw in needed_per_period:
            sec_name = _PER_PERIOD_METRICS[raw][0]
            if sec_name == "income_statement":
                sections_to_fetch.add(FundamentalsSection.INCOME_STATEMENT)
            elif sec_name == "earnings_history":
                sections_to_fetch.add(FundamentalsSection.EARNINGS_HISTORY)
            elif sec_name == "cash_flow":
                sections_to_fetch.add(FundamentalsSection.CASH_FLOW)
        if needed_snapshot or include_snapshot:
            sections_to_fetch.add(FundamentalsSection.HIGHLIGHTS)
        if "fcf_yield" in needed_derived_snapshot:
            sections_to_fetch.add(FundamentalsSection.CASH_FLOW)

        # ── Fetch all required sections concurrently-ish (sequential here for
        # simplicity; UoW dispatch is already async).
        records_by_section: dict[FundamentalsSection, list[Any]] = {}
        for section in sections_to_fetch:
            # INCOME_STATEMENT honours the period_type filter so quarterly vs
            # annual rows never mix. EARNINGS_HISTORY/HIGHLIGHTS/CASH_FLOW are
            # by-contract single-shape sections — we pass no filter.
            if section == FundamentalsSection.INCOME_STATEMENT:
                records_by_section[section] = await self._uow.fundamentals_read.find_by_section(
                    iid_str, section, period_type=selected_period_type
                )
            else:
                records_by_section[section] = await self._uow.fundamentals_read.find_by_section(iid_str, section)

        # ── Build the period axis. We mirror GetFundamentalsHistoryUseCase's
        # driver-section choice: EARNINGS_HISTORY for QUARTERLY, INCOME_STATEMENT
        # for ANNUAL. If the driver section was not loaded (caller didn't ask
        # for any per-period metric), default to income_statement so we still
        # have a period axis to anchor derived metrics to.
        if selected_period_type == PeriodType.QUARTERLY:
            driver_records = records_by_section.get(FundamentalsSection.EARNINGS_HISTORY) or records_by_section.get(
                FundamentalsSection.INCOME_STATEMENT, []
            )
        else:
            driver_records = records_by_section.get(FundamentalsSection.INCOME_STATEMENT, [])

        # RC-1 fix (2026-06-28): drop EODHD future-dated pre-report placeholder
        # rows BEFORE slicing — the exact filter ``GetFundamentalsHistoryUseCase``
        # already applies. Without it, the next-quarter placeholder (null
        # epsActual/revenue, e.g. TSLA 2026-06-30) wins a period slot, evicts the
        # oldest real quarter, AND drags every metric's coverage flag to
        # ``partial``. The rag-chat ``_handle_query_fundamentals`` handler only
        # emits grounding fields for ``ok``-coverage metrics, so a single
        # placeholder row was stripping ALL numeric grounding — the chat answer's
        # ``grounding_sample`` then carried only ``ticker`` and the judge floored
        # otherwise-correct quarters as fabricated (docs/audits/
        # 2026-06-28-grounding-floor-rootcause.md RC-1).
        filtered_driver_records = [
            rec for rec in driver_records if not is_future_placeholder_row(rec, selected_period_type)
        ]
        # Slice newest-first then reverse to ASC for caller-friendly ordering.
        sorted_records = sorted(filtered_driver_records, key=lambda r: r.period_end, reverse=True)[:periods]
        selected = list(reversed(sorted_records))

        # Build lookup maps by ISO period_end so per-metric extraction is O(1).
        income_by_key: dict[str, dict] = {}
        for rec in records_by_section.get(FundamentalsSection.INCOME_STATEMENT, []):
            key = rec.period_end.strftime("%Y-%m-%d")
            income_by_key[key] = rec.data if isinstance(rec.data, dict) else {}
        cash_by_key: dict[str, dict] = {}
        for rec in records_by_section.get(FundamentalsSection.CASH_FLOW, []):
            key = rec.period_end.strftime("%Y-%m-%d")
            cash_by_key[key] = rec.data if isinstance(rec.data, dict) else {}

        # Highlights snapshot (most-recent wins).
        highlights_data: dict[str, Any] = {}
        highlights_as_of: str | None = None
        highlights_recs = records_by_section.get(FundamentalsSection.HIGHLIGHTS, [])
        if highlights_recs:
            most_recent = max(highlights_recs, key=lambda r: r.period_end)
            highlights_data = most_recent.data if isinstance(most_recent.data, dict) else {}
            highlights_as_of = most_recent.period_end.date().isoformat()

        # ── Build per-period rows.
        from market_data.application.use_cases.get_fundamentals_history import _period_label

        metrics_by_period: list[dict[str, Any]] = []
        for rec in selected:
            period_key = rec.period_end.strftime("%Y-%m-%d")
            data = rec.data if isinstance(rec.data, dict) else {}
            # F-NEW-013: derive the quarter label from ``period_end`` (the
            # fiscal period the data COVERS) — NOT from ``reportDate`` / ``date``
            # (the SEC filing date, which lands ~1 month later and shifts every
            # label by one quarter for issuers whose filing spills into the
            # next calendar quarter). Mirrors the matching fix in
            # ``get_fundamentals_history.execute``.
            label = _period_label(period_key, fiscal_year_end_month=fye, ticker=ticker)

            # BugFix B (2026-06-06): defense-in-depth invariant — every row
            # served by this use case MUST carry a non-empty period_label.
            # The schema (FundamentalsQueryPeriodRow) declares
            # ``period_label: str`` (non-Optional) so a None would 500 via
            # Pydantic; an empty string would silently produce the rag-chat
            # "Period →  Period" rendering bug. Synthesise a calendar-quarter
            # fallback if the helper ever returns a falsy value. period_key is
            # the strftime("%Y-%m-%d") of a NOT-NULL DB timestamp so this is
            # safe — the guard exists purely to make a future regression in
            # _period_label loud and visible instead of silent.
            if not label or not str(label).strip():
                log.warning(
                    "period_label_empty_fallback_synthesised",
                    ticker=ticker,
                    period_end=period_key,
                )
                try:
                    from datetime import date as _date_fb

                    _dt_fb = _date_fb.fromisoformat(period_key)
                    _q_fb = (_dt_fb.month - 1) // 3 + 1
                    label = f"Q{_q_fb} {_dt_fb.year}"
                except (ValueError, TypeError):
                    label = "Unknown Period"

            row: dict[str, Any] = {
                "period_end": period_key,
                "period_label": label,
                "period_type": selected_period_type.value,
            }

            # Resolve raw per-period metrics.
            raw_values: dict[str, float | None] = {}
            for m in needed_per_period:
                sec_name, aliases = _PER_PERIOD_METRICS[m]
                if sec_name == "earnings_history":
                    val = _pick_alias(data, aliases)
                elif sec_name == "income_statement":
                    val = _pick_alias(income_by_key.get(period_key, {}), aliases)
                elif sec_name == "cash_flow":
                    val = _pick_alias(cash_by_key.get(period_key, {}), aliases)
                else:
                    val = None
                raw_values[m] = _safe_float(val)

            # Only expose metrics the caller actually asked for (deps may have
            # been loaded transitively — don't leak them into the row).
            for m in metrics:
                if m in raw_values:
                    row[m] = raw_values[m]

            # Derived per-period metrics.
            for m in needed_derived:
                deps, fn = _DERIVED_PER_PERIOD[m]
                dep_vals = [raw_values.get(d) for d in deps]
                if any(v is None for v in dep_vals):
                    row[m] = None
                else:
                    try:
                        row[m] = fn(*dep_vals)
                    except (TypeError, ZeroDivisionError, ValueError):
                        row[m] = None

            metrics_by_period.append(row)

        # ── Build snapshot.
        snapshot: dict[str, Any] | None = None
        if include_snapshot or needed_snapshot or needed_derived_snapshot:
            snap: dict[str, Any] = {}
            for m in metrics:
                if m in _SNAPSHOT_METRICS:
                    snap[m] = _safe_float(_pick_alias(highlights_data, _SNAPSHOT_METRICS[m]))
            # Derived snapshot metrics
            if "fcf_yield" in needed_derived_snapshot:
                mcap = _safe_float(_pick_alias(highlights_data, _SNAPSHOT_METRICS["market_cap"]))
                # Use the most-recent annual FCF from CASH_FLOW
                annual_fcf: float | None = None
                annual_recs = sorted(
                    records_by_section.get(FundamentalsSection.CASH_FLOW, []),
                    key=lambda r: r.period_end,
                    reverse=True,
                )
                for rec in annual_recs:
                    rec_data = rec.data if isinstance(rec.data, dict) else {}
                    fcf = _safe_float(_pick_alias(rec_data, _PER_PERIOD_METRICS["free_cash_flow"][1]))
                    if fcf is not None:
                        annual_fcf = fcf
                        break
                snap["fcf_yield"] = (annual_fcf / mcap) if (annual_fcf is not None and mcap) else None
            if include_snapshot and highlights_as_of:
                snap["as_of"] = highlights_as_of
                snap["source"] = "highlights"
            snapshot = snap or None

        # ── Compute coverage flags.
        coverage: dict[str, CoverageFlag] = {}
        for m in metrics:
            if m not in KNOWN_METRICS:
                coverage[m] = "missing"
                continue
            if m in _PER_PERIOD_METRICS or m in _DERIVED_PER_PERIOD:
                values = [row.get(m) for row in metrics_by_period]
                non_null = sum(1 for v in values if v is not None)
                if not values:
                    coverage[m] = "missing"
                elif non_null == len(values):
                    coverage[m] = "ok"
                elif non_null == 0:
                    coverage[m] = "missing"
                else:
                    coverage[m] = "partial"
            elif m in _SNAPSHOT_METRICS or m in _DERIVED_SNAPSHOT:
                v = (snapshot or {}).get(m)
                coverage[m] = "ok" if v is not None else "missing"
            else:
                coverage[m] = "missing"

        log.info(
            "query_fundamentals_executed",
            ticker=ticker,
            metrics_requested=len(metrics),
            periods_returned=len(metrics_by_period),
            sections_fetched=len(sections_to_fetch),
        )
        return {
            "metrics_by_period": metrics_by_period,
            "snapshot": snapshot,
            "coverage": coverage,
        }
