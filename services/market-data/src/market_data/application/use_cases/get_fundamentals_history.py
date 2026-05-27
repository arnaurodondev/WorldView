"""GetFundamentalsHistoryUseCase — earnings-based fundamentals history (PLAN-0066 Wave G).

IMPORTANT (N-10): There is no ``fundamentals_records`` table.  Fundamentals history
is sourced from the earnings_history section of the existing FundamentalsRecord store
(FundamentalsSection.EARNINGS_HISTORY).  The data dict in each record follows the
EODHD EarningsHistory schema and may contain:
  reportDate, date, beforeAfterMarket, currency, epsActual, epsEstimate,
  epsDifference, surprisePercent

FIX-LIVE-P (2026-05-25): fiscal-quarter labels are now computed from the
instrument's ``fiscal_year_end_month`` (see ``_period_label``). Without this
fix, NVIDIA's Q4FY26 (period_end 2026-01-31) was labelled "Q1 2026" because
the calendar month determined the quarter — wrong for any issuer whose
fiscal year is not calendar-aligned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork

log = structlog.get_logger(__name__)


class GetFundamentalsHistoryUseCase:
    """Return earnings-based quarterly fundamentals history for an instrument.

    WHY earnings_history: there is no separate fundamentals_records table.
    The EODHD ingest pipeline stores quarterly earnings data as
    FundamentalsRecord rows with section=EARNINGS_HISTORY.  Each row's
    ``data`` dict contains the available fields for that period.

    We also pull HIGHLIGHTS for the current-period snapshot fields
    (MarketCapitalization, PERatio) when available.
    """

    def __init__(self, uow: ReadOnlyUnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        instrument_id: UUID,
        periods: int = 8,
        *,
        requested_quarter: str | None = None,
    ) -> dict:
        """Return {"periods": [...], "period_count": int}.

        Each period dict contains:
          period, period_end_date, revenue, gross_profit, net_income,
          eps, pe_ratio, market_cap  (null when not available in source data)

        FIX-LIVE-P observability: ``requested_quarter`` is an optional canonical
        quarter label such as ``"Q4 FY2026"`` extracted from an upstream intent
        layer (e.g. rag-chat).  When supplied, this method emits a structured
        ``fundamentals_quarterly_missing`` warning if the returned periods do
        not include that quarter, so operators can distinguish "data not yet
        ingested" from "labelling bug" in production logs.
        """
        from market_data.domain.enums import FundamentalsSection, PeriodType

        iid_str = str(instrument_id)

        # FIX-LIVE-P: resolve the instrument's fiscal_year_end_month so we can
        # label periods correctly. None when unknown — _period_label falls back
        # to calendar-year labels and emits a separate warning.
        instrument = await self._uow.instruments_read.find_by_id(iid_str)
        ticker = instrument.symbol if instrument is not None else iid_str
        fiscal_year_end_month = instrument.fiscal_year_end_month if instrument is not None else None

        # Fetch earnings history records (quarterly EPS/surprise data)
        earnings_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.EARNINGS_HISTORY,
        )

        # Fetch income-statement records for revenue/gross_profit/net_income.
        # PLAN-0095 T-W1-02 (BP-559): pin to QUARTERLY so a same-period ANNUAL
        # row never shadows the quarterly figure. Without this filter the JOIN
        # below by ``period_end`` can match an annual row whose revenue is 4x
        # the quarterly value (AMD/NVDA Q1FY26 returned $34B instead of $7B).
        income_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.INCOME_STATEMENT,
            period_type=PeriodType.QUARTERLY,
        )

        # Fetch highlights for market_cap/pe_ratio (TTM snapshot).
        #
        # PLAN-0097 T-W1-01 (BP-577): HIGHLIGHTS rows are TTM-only by EODHD
        # contract (no QUARTERLY/ANNUAL variants exist for this section). We
        # intentionally do NOT pass period_type here because the column may be
        # populated as ANNUAL in legacy rows (see audit
        # ``2026-05-27-plan-0097-data-integrity-investigation.md`` §A1) and a
        # strict ``QUARTERLY`` filter would shadow valid data. Instead we
        # extract ONLY snapshot-safe scalar fields (PERatio, MarketCapitalization)
        # downstream, and every returned row in ``result_periods`` carries an
        # explicit ``period_type`` label so callers can never quote a TTM
        # value as a quarterly figure without seeing it tagged as such.
        highlights_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.HIGHLIGHTS,
        )

        # Build lookup from period_end → income-statement data for JOIN
        income_by_period: dict[str, dict] = {}
        for rec in income_records:
            key = rec.period_end.strftime("%Y-%m-%d")
            income_by_period[key] = rec.data if isinstance(rec.data, dict) else {}

        # Build highlights snapshot (most-recent record wins)
        highlights_data: dict = {}
        if highlights_records:
            most_recent = max(highlights_records, key=lambda r: r.period_end)
            highlights_data = most_recent.data if isinstance(most_recent.data, dict) else {}

        def _safe_float(value: object) -> float | None:
            """Convert a value to float, returning None on failure."""
            if value is None or value == "" or value == "None":
                return None
            try:
                return float(value)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                return None

        # Sort earnings records by period_end DESC then slice
        sorted_records = sorted(earnings_records, key=lambda r: r.period_end, reverse=True)
        selected = sorted_records[:periods]
        # Re-sort ASC for response ordering
        selected = list(reversed(selected))

        result_periods = []
        for rec in selected:
            period_key = rec.period_end.strftime("%Y-%m-%d")
            data = rec.data if isinstance(rec.data, dict) else {}
            inc = income_by_period.get(period_key, {})

            # Attempt to build a human-readable period label from the report date.
            # FIX-LIVE-P: pass fiscal_year_end_month so issuers with non-calendar
            # fiscal years (NVDA=1, AAPL=9, MSFT=6) get correctly labelled fiscal
            # quarters instead of calendar quarters.
            report_date = data.get("reportDate") or data.get("date") or period_key
            period_label = _period_label(
                str(report_date),
                fiscal_year_end_month=fiscal_year_end_month,
                ticker=ticker,
            )

            result_periods.append(
                {
                    "period": period_label,
                    "period_end_date": period_key,
                    # PLAN-0097 T-W1-01 (BP-577): explicit periodicity label on
                    # every row so the rag-chat tool layer (and ultimately the
                    # LLM) can never quote a TTM/ANNUAL value in a quarterly
                    # context without seeing the mismatch. income_records is
                    # filtered to QUARTERLY above (line 87-91), so the revenue
                    # / gross_profit / net_income fields below are guaranteed
                    # quarterly. eps comes from EARNINGS_HISTORY which is
                    # quarterly-only in EODHD's schema.
                    "period_type": "QUARTERLY",
                    # Income statement fields (prefer income-stmt section, fall back to None)
                    "revenue": _safe_float(inc.get("totalRevenue") or inc.get("revenue")),
                    "gross_profit": _safe_float(inc.get("grossProfit")),
                    "net_income": _safe_float(inc.get("netIncome")),
                    # EPS from earnings section
                    "eps": _safe_float(data.get("epsActual") or data.get("eps")),
                    # PE ratio and market cap from highlights (TTM, not per-period).
                    # The TTM-ness of these two fields is documented at the call
                    # site that consumes them (rag-chat MarketHandler). They are
                    # snapshot ratios, not flow metrics, so cannot be confused
                    # with revenue/net_income even if a model misreads them.
                    "pe_ratio": _safe_float(highlights_data.get("PERatio")),
                    "market_cap": _safe_float(highlights_data.get("MarketCapitalization")),
                }
            )

        # FIX-LIVE-P observability: if the caller advertised the user's requested
        # quarter and that quarter is NOT in the returned periods, emit a
        # structured warning so we can monitor "data not yet ingested" gaps
        # (e.g. NVDA Q4FY26 / AMD Q1FY26 on 2026-05-25 — both genuinely missing
        # from the DB; see FIX-LIVE-G follow-up).
        if requested_quarter is not None:
            # period values are always strings as constructed above — narrow for mypy.
            available = [str(p["period"]) for p in result_periods]
            normalised_request = _normalise_quarter_label(requested_quarter)
            normalised_available = {_normalise_quarter_label(p) for p in available}
            if normalised_request not in normalised_available:
                log.warning(
                    "fundamentals_quarterly_missing",
                    ticker=ticker,
                    instrument_id=iid_str,
                    requested_quarter=requested_quarter,
                    available_quarters=available[:5],
                )

        return {"periods": result_periods, "period_count": len(result_periods)}


def _period_label(
    report_date: str,
    *,
    fiscal_year_end_month: int | None = None,
    ticker: str | None = None,
) -> str:
    """Convert a YYYY-MM-DD date string to a human-readable quarter label.

    With ``fiscal_year_end_month`` (1-12), returns a fiscal-quarter label like
    ``"Q4 FY2026"``. Without it, falls back to a calendar-quarter label like
    ``"Q1 2026"`` and emits a structured ``fiscal_year_end_unknown`` warning
    so operators can monitor the gap.

    FIX-LIVE-P (2026-05-25): the calendar-only path was the original bug —
    NVIDIA's 2026-01-31 period (fiscal Q4 FY2026) was being labelled
    "Q1 2026" because the calendar month said so. The fiscal computation
    uses modular arithmetic on the gap between the period's calendar month
    and the issuer's fiscal-year-end month.

    Worked examples (verify cases used in the test suite):
      * NVDA fy_end=1, period 2026-01-31 → Q4 FY2026  (months_into_fy=12 → Q4)
      * AAPL fy_end=9, period 2026-09-30 → Q4 FY2026
      * AAPL fy_end=9, period 2025-12-31 → Q1 FY2026  (Dec is first month after Sept)
      * MSFT fy_end=6, period 2026-06-30 → Q4 FY2026
      * AMD  fy_end=12, period 2026-03-31 → Q1 FY2026  (calendar = fiscal here)
      * Unknown fy_end, period 2026-03-31 → "Q1 2026" + warning

    Returns the original input unchanged on any parse failure (forward-compatible).
    """
    try:
        from datetime import date as _date

        dt = _date.fromisoformat(report_date)
    except (ValueError, TypeError):
        return report_date

    if fiscal_year_end_month is None or not (1 <= fiscal_year_end_month <= 12):
        # No reliable fiscal calendar — emit an observability hook so coverage
        # can be tracked (CRITICAL: ticker may be None when the caller did not
        # plumb it through, which is fine — the warning is still actionable).
        log.warning(
            "fiscal_year_end_unknown",
            ticker=ticker,
            report_date=report_date,
        )
        quarter = (dt.month - 1) // 3 + 1
        return f"Q{quarter} {dt.year}"

    fy_end = fiscal_year_end_month
    # Months into the fiscal year: the month immediately AFTER fy_end is
    # fiscal-month 1; fy_end itself is fiscal-month 12.  Modular arithmetic
    # avoids special-casing fy_end == 12 vs anything else.
    months_into_fy = ((dt.month - fy_end - 1) % 12) + 1
    fiscal_quarter = (months_into_fy - 1) // 3 + 1
    # Fiscal-year naming: FY N ends in calendar month fy_end of year N.
    # So months ≤ fy_end belong to FY equal to the calendar year; months
    # > fy_end belong to the NEXT fiscal year. Example: AAPL fy_end=9,
    # period 2025-12-31 falls in FY2026 (months_into_fy=3 = Q1 FY2026).
    fiscal_year = dt.year if dt.month <= fy_end else dt.year + 1
    return f"Q{fiscal_quarter} FY{fiscal_year}"


def _normalise_quarter_label(label: str) -> str:
    """Normalise a quarter label for set membership comparison.

    Accepts variants like ``"Q4 FY2026"``, ``"Q4 2026"``, ``"q4 fy 2026"``,
    ``"Q4-FY26"`` and collapses to a canonical form ``"Q<n>:<year>"`` where
    ``year`` is the 4-digit year. Tolerant by design — this is used for
    observability only, not for matching user input back to the response.
    """
    import re

    s = label.upper().replace("-", " ").replace("FY", " ").strip()
    # Collapse runs of whitespace
    s = re.sub(r"\s+", " ", s)
    m = re.match(r"Q\s*(\d+)\s+(\d{2,4})", s)
    if m is None:
        return label.upper().strip()
    q, year = m.group(1), m.group(2)
    # Tolerate 2-digit years by assuming 20xx
    if len(year) == 2:
        year = f"20{year}"
    return f"Q{q}:{year}"
