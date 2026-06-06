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
        period_type: str = "quarterly",
    ) -> dict:
        """Return {"periods": [...], "period_count": int}.

        Each period dict contains:
          period, period_end_date, revenue, gross_profit, net_income,
          eps, pe_ratio, market_cap, period_type  (nullable per-cell)

        ``period_type`` selects the periodicity of the returned rows. Accepted
        values: ``"quarterly"`` (default — safest, matches the LLM's almost-
        always-quarter ask) or ``"annual"``. F-LIVE-P (2026-05-26): before this
        knob existed the use case always derived rows from EARNINGS_HISTORY
        (quarterly-only) and JOINed an income_statement filter pinned to
        QUARTERLY. That suppressed the ANNUAL-leak symptom, but it also meant
        callers asking for annual data could never get it. Now the use case
        explicitly picks per ``period_type`` and never mixes the two.

        FIX-LIVE-P observability: ``requested_quarter`` is an optional canonical
        quarter label such as ``"Q4 FY2026"`` extracted from an upstream intent
        layer (e.g. rag-chat).  When supplied, this method emits a structured
        ``fundamentals_quarterly_missing`` warning if the returned periods do
        not include that quarter, so operators can distinguish "data not yet
        ingested" from "labelling bug" in production logs.
        """
        from market_data.domain.enums import FundamentalsSection, PeriodType

        # F-LIVE-P: normalise to upper-case StrEnum value. Invalid values fall
        # back to QUARTERLY (the safer default) instead of raising — the API
        # layer is responsible for input validation; the use case stays robust
        # to surprise input from any future caller.
        period_type_norm = (period_type or "quarterly").upper()
        if period_type_norm not in {"QUARTERLY", "ANNUAL"}:
            log.warning(
                "fundamentals_history_unknown_period_type",
                requested=period_type,
                fallback="QUARTERLY",
            )
            period_type_norm = "QUARTERLY"
        selected_period_type = PeriodType(period_type_norm)

        iid_str = str(instrument_id)

        # FIX-LIVE-P: resolve the instrument's fiscal_year_end_month so we can
        # label periods correctly. None when unknown — _period_label falls back
        # to calendar-year labels and emits a separate warning.
        instrument = await self._uow.instruments_read.find_by_id(iid_str)
        ticker = instrument.symbol if instrument is not None else iid_str
        fiscal_year_end_month = instrument.fiscal_year_end_month if instrument is not None else None

        # Fetch earnings history records (quarterly EPS/surprise data — EODHD
        # contract: EARNINGS_HISTORY is quarterly-only, no annual variant).
        # We only need this section for the QUARTERLY response shape, where
        # EPS/surprise drives the per-period dict; for ANNUAL we drive the
        # response from income_statement directly (see below).
        earnings_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.EARNINGS_HISTORY,
        )

        # Fetch income-statement records for revenue/gross_profit/net_income.
        # F-LIVE-P (2026-05-26): pin to the explicit ``selected_period_type``
        # so the use case NEVER mixes annual and quarterly rows in one
        # response.  Pre-F-LIVE-P (PLAN-0095 T-W1-02) this was hard-pinned to
        # QUARTERLY which suppressed the well-known $34.639B AMD Q1 FY2026
        # leak but also made annual queries impossible.  The selector now
        # forwards the caller's choice; the API layer (and rag-chat tool
        # schema) validates the value so the only legal inputs that reach
        # here are QUARTERLY or ANNUAL.
        income_records = await self._uow.fundamentals_read.find_by_section(
            iid_str,
            FundamentalsSection.INCOME_STATEMENT,
            period_type=selected_period_type,
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

        # F-LIVE-P (2026-05-26): pick the driver section by the explicit
        # period_type. EARNINGS_HISTORY only carries quarterly EPS/surprise
        # rows in EODHD's contract, so for ANNUAL we drive the response from
        # the income_statement rows we already fetched (revenue / net_income
        # are populated; EPS is sourced from income_statement.epsActual when
        # present, else None — that is correct, not a bug).
        driver_records = earnings_records if selected_period_type == PeriodType.QUARTERLY else income_records

        # PLAN-0103 W22 / BP-639: drop EODHD's future-dated pre-report
        # placeholder rows.
        #
        # WHY: EODHD's EARNINGS_HISTORY section pre-emits a row for the next
        # scheduled report date with NULL EPS so the column structure is
        # stable for downstream consumers. After DESC-sort + slice [:1] these
        # placeholders win, the downstream LLM sees a "row" with every metric
        # as "—" and FABRICATES values (audit
        # ``2026-06-01-chat-quality-aapl-pe-investigation.md`` — AAPL P/E
        # fabricated as 37.7x because the only returned row was the
        # 2026-06-30 placeholder with EPS=NULL).
        #
        # Defensive predicate: a row is a "future placeholder" only if BOTH
        # (a) ``period_end`` is strictly in the future relative to today
        # (UTC), AND (b) the driver metric for the section is null. For
        # QUARTERLY (earnings_history) the driver metric is ``epsActual``;
        # for ANNUAL (income_statement) the driver metric is
        # ``totalRevenue``/``revenue``. We do NOT drop a legitimately-late
        # filing that lacks an unrelated optional field, only the
        # all-null-driver placeholder pattern.
        from datetime import UTC as _UTC
        from datetime import datetime as _datetime

        today_utc = _datetime.now(tz=_UTC).date()

        def _is_future_placeholder(rec: object) -> bool:
            # rec.period_end is a tz-aware datetime; comparing dates is
            # sufficient (we don't care about intraday for "is this in the
            # future").
            pe_date = rec.period_end.date()  # type: ignore[attr-defined]
            if pe_date <= today_utc:
                return False
            data = rec.data if isinstance(rec.data, dict) else {}  # type: ignore[attr-defined]
            if selected_period_type == PeriodType.QUARTERLY:
                driver_value = data.get("epsActual")
            else:
                driver_value = data.get("totalRevenue") or data.get("revenue")
            return driver_value is None or driver_value == "" or driver_value == "None"

        filtered_driver_records = []
        for rec in driver_records:
            if _is_future_placeholder(rec):
                log.info(
                    "fundamentals_future_placeholder_dropped",
                    symbol=ticker,
                    period_end=rec.period_end.strftime("%Y-%m-%d"),
                    period_type=selected_period_type.value,
                )
                continue
            filtered_driver_records.append(rec)

        # PLAN-0103 W25 / BP-640: snapshot-vs-period-row P/E injection fix.
        #
        # The HIGHLIGHTS section is a single live/TTM snapshot — there is no
        # per-period stream of PERatio/MarketCapitalization. Pre-W25 we
        # injected ``highlights_data['PERatio']`` into EVERY period row's
        # ``pe_ratio`` field, which caused the AAPL P/E benchmark question
        # (and GOOGL P/E in Round 2) to fail two different ways:
        #   * If the answer cell came back populated the LLM quoted the TTM
        #     P/E as if it were the row's quarterly P/E (fabrication).
        #   * If the row had been dropped by W22's future-placeholder filter
        #     the LLM refused — because the only remaining rows had revenue/
        #     EPS populated but ``pe_ratio`` empty (per-period P/E doesn't
        #     exist as a fundamentals concept).
        #
        # Fix: build a separate ``current_snapshot`` block (see route handler
        # + ``CurrentSnapshot`` schema) and STOP injecting snapshot fields
        # into per-period rows. Periods keep flow/operating metrics ONLY.
        # The snapshot lives as a sibling field in the response so the LLM
        # can cleanly choose "current P/E?" → snapshot vs "quarterly trend?"
        # → periods.

        # Sort driver records by period_end DESC then slice
        sorted_records = sorted(filtered_driver_records, key=lambda r: r.period_end, reverse=True)
        selected = sorted_records[:periods]
        # Re-sort ASC for response ordering
        selected = list(reversed(selected))

        result_periods = []
        for rec in selected:
            period_key = rec.period_end.strftime("%Y-%m-%d")
            data = rec.data if isinstance(rec.data, dict) else {}
            inc = income_by_period.get(period_key, {})
            # For ANNUAL the driver IS the income_statement row, so the local
            # ``data`` dict already has revenue/netIncome. Mirror it into
            # ``inc`` so the field-extraction block below works uniformly.
            if selected_period_type == PeriodType.ANNUAL and not inc:
                inc = data

            # F-NEW-013: derive the quarter label from `period_end` (the fiscal
            # period the data COVERS) — NOT from `reportDate`/`date` (the FILING
            # date, which lands ~1 month later and shifts every label by one
            # quarter for issuers whose filing spills into the next calendar
            # quarter — universal blast radius pre-fix). `_period_label`'s
            # docstring explicitly says it expects period_end as input; the bug
            # was at the call site, not in the helper.
            # FIX-LIVE-P: pass fiscal_year_end_month so issuers with non-calendar
            # fiscal years (NVDA=1, AAPL=9, MSFT=6) get correctly labelled fiscal
            # quarters instead of calendar quarters.
            period_label = _period_label(
                period_key,
                fiscal_year_end_month=fiscal_year_end_month,
                ticker=ticker,
            )

            result_periods.append(
                {
                    "period": period_label,
                    "period_end_date": period_key,
                    # PLAN-0097 T-W1-01 (BP-577) + F-LIVE-P (2026-05-26):
                    # explicit periodicity label on every row so the rag-chat
                    # tool layer (and ultimately the LLM) can never quote a
                    # TTM/ANNUAL value in a quarterly context without seeing
                    # the mismatch. The value mirrors the caller's request and
                    # the actual SQL filter applied above, so by construction
                    # every row in ``result_periods`` shares the same
                    # ``period_type``.
                    "period_type": selected_period_type.value,
                    # Income statement fields (prefer income-stmt section, fall back to None)
                    "revenue": _safe_float(inc.get("totalRevenue") or inc.get("revenue")),
                    "gross_profit": _safe_float(inc.get("grossProfit")),
                    "net_income": _safe_float(inc.get("netIncome")),
                    "eps": _safe_float(data.get("epsActual") or data.get("eps")),
                    # PLAN-0103 W25 / BP-640: ``pe_ratio`` and ``market_cap``
                    # are NULL on every period row. The TTM snapshot lives in
                    # the sibling ``current_snapshot`` block. Per-row fields
                    # remain in the schema for forward compatibility but no
                    # longer carry snapshot leakage that the LLM could quote
                    # as a per-period figure.
                    "pe_ratio": None,
                    "market_cap": None,
                }
            )

        # PLAN-0103 W25 / BP-640: build the live-valuation snapshot block.
        # ``most_recent`` (computed above) is the latest HIGHLIGHTS row by
        # ``period_end``; ``highlights_data`` is its raw dict.  We populate
        # whichever EODHD keys are present and leave the rest as None — the
        # CurrentSnapshot schema is fully nullable so partial coverage (ETFs,
        # newly-listed issuers) is rendered honestly rather than fabricated.
        #
        # ``as_of`` is the ``period_end`` of the source highlights row. EODHD
        # stamps these with the date the snapshot was captured; we expose it
        # so the LLM can quote "P/E as-of YYYY-MM-DD" instead of inventing
        # "today". When the section had zero rows, ``current_snapshot`` is
        # None and downstream callers handle that as "no snapshot available".
        current_snapshot: dict | None = None
        if highlights_records:
            most_recent_hl = max(highlights_records, key=lambda r: r.period_end)
            current_snapshot = {
                "pe_ratio": _safe_float(highlights_data.get("PERatio")),
                "ev_ebitda": _safe_float(
                    highlights_data.get("EVToEBITDA") or highlights_data.get("EnterpriseValueEbitda")
                ),
                "market_cap_usd": _safe_float(highlights_data.get("MarketCapitalization")),
                "price_to_book": _safe_float(highlights_data.get("PriceBookMRQ")),
                "dividend_yield": _safe_float(highlights_data.get("DividendYield")),
                # PLAN-0104 W30 / BP-649: forward valuation metrics were
                # already parsed by metric_extractor but dropped on the way
                # out of the use case. Surface them now so the rag-chat
                # snapshot renderer (handlers/market.py) can answer
                # "forward P/E" / "PEG" questions without fabrication.
                "forward_pe": _safe_float(highlights_data.get("ForwardPE")),
                "peg_ratio": _safe_float(highlights_data.get("PEGRatio")),
                # ``period_end`` is a tz-aware datetime; expose just the date
                # portion so the API model (date field) accepts it cleanly.
                "as_of": most_recent_hl.period_end.date(),
                "source": "highlights",
            }

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

        return {
            "periods": result_periods,
            "period_count": len(result_periods),
            # PLAN-0103 W25 / BP-640: TTM/live snapshot block — None when the
            # HIGHLIGHTS section was empty for this instrument.
            "current_snapshot": current_snapshot,
        }


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
