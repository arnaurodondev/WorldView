"""GetFundamentalsHistoryUseCase — earnings-based fundamentals history (PLAN-0066 Wave G).

IMPORTANT (N-10): There is no ``fundamentals_records`` table.  Fundamentals history
is sourced from the earnings_history section of the existing FundamentalsRecord store
(FundamentalsSection.EARNINGS_HISTORY).  The data dict in each record follows the
EODHD EarningsHistory schema and may contain:
  reportDate, date, beforeAfterMarket, currency, epsActual, epsEstimate,
  epsDifference, surprisePercent
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from market_data.application.ports.uow import ReadOnlyUnitOfWork


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
    ) -> dict:
        """Return {"periods": [...], "period_count": int}.

        Each period dict contains:
          period, period_end_date, revenue, gross_profit, net_income,
          eps, pe_ratio, market_cap  (null when not available in source data)
        """
        from market_data.domain.enums import FundamentalsSection

        iid_str = str(instrument_id)

        # Fetch earnings history records (quarterly EPS/surprise data)
        earnings_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.EARNINGS_HISTORY,
        )

        # Fetch income-statement records for revenue/gross_profit/net_income
        income_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.INCOME_STATEMENT,
        )

        # Fetch highlights for market_cap/pe_ratio (TTM snapshot)
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

            # Attempt to build a human-readable period label from the report date
            report_date = data.get("reportDate") or data.get("date") or period_key
            period_label = _period_label(str(report_date))

            result_periods.append(
                {
                    "period": period_label,
                    "period_end_date": period_key,
                    # Income statement fields (prefer income-stmt section, fall back to None)
                    "revenue": _safe_float(inc.get("totalRevenue") or inc.get("revenue")),
                    "gross_profit": _safe_float(inc.get("grossProfit")),
                    "net_income": _safe_float(inc.get("netIncome")),
                    # EPS from earnings section
                    "eps": _safe_float(data.get("epsActual") or data.get("eps")),
                    # PE ratio and market cap from highlights (TTM, not per-period)
                    "pe_ratio": _safe_float(highlights_data.get("PERatio")),
                    "market_cap": _safe_float(highlights_data.get("MarketCapitalization")),
                }
            )

        return {"periods": result_periods, "period_count": len(result_periods)}


def _period_label(report_date: str) -> str:
    """Convert a YYYY-MM-DD date string to a human-readable quarter label.

    Examples:
      "2026-03-31" → "Q1 2026"
      "2025-12-31" → "Q4 2025"
      "bad-value"  → "bad-value" (pass through unchanged)
    """
    try:
        from datetime import date as _date

        dt = _date.fromisoformat(report_date)
        quarter = (dt.month - 1) // 3 + 1
        return f"Q{quarter} {dt.year}"
    except (ValueError, TypeError):
        return report_date
