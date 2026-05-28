"""Fundamentals snapshot derivation and write helper for market-data.

WHY THIS MODULE EXISTS (PLAN-0050 F-Q1-03):
  ``instrument_fundamentals_snapshot`` was always empty in continuous operation
  because only the one-shot backfill script populated it.  This module ports the
  pure derivation logic from the backfill script into market-data so the
  FundamentalsConsumer can UPSERT a fresh snapshot row on every ingest cycle —
  making the snapshot table eventually consistent with the section tables
  without requiring a manual backfill run.

DESIGN DECISIONS:
  - The derivation helpers (_safe_float, _try_keys, derive_fundamentals_snapshot)
    are duplicated from ``services/market-ingestion/scripts/backfill_fundamentals.py``
    rather than imported across service boundaries (Rule 9: no cross-service imports).
  - The UPSERT uses SQLAlchemy ``text()`` rather than ORM to keep the session
    interface simple — the consumer already has the write session via the UoW
    and adding a full repository just for one UPSERT would be over-engineered.
  - Financial statement sections (income_statement, cash_flow, balance_sheet) are
    stored nested as ``{quarterly: {date: row}, yearly: {date: row}}``.  We use
    the most recent yearly entry for snapshot derivation (trailing-twelve-months
    semantics); if no yearly entry exists, we fall back to the most recent
    quarterly entry.
  - Called as best-effort: any exception is caught and logged, never propagated
    (snapshot failure must not dead-letter the fundamentals Kafka message).
"""

from __future__ import annotations

from datetime import date as _date_cls
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


# ── Derivation helpers (mirror of backfill_fundamentals.py) ──────────────────


def _safe_float(val: Any, label: str = "") -> float | None:
    """Coerce a JSONB value to float, returning None on failure.

    WHY safe (not strict): EODHD JSONB blobs may contain null, empty string,
    "N/A", or numeric-as-string variants.  Rather than crashing on one bad
    field, we log and continue with NULL.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int | float):
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.lower() in {"", "n/a", "na", "none", "null", "nan", "-", "--"}:
            return None
        # Parenthesized negatives: (1234.5) → -1234.5
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            if label:
                logger.debug("snapshot_writer.coerce_failed", label=label, raw=str(val)[:50])
            return None
    if isinstance(val, Decimal):
        try:
            return float(val)
        except (InvalidOperation, ValueError):
            return None
    return None


def _try_keys(data: dict[str, Any], *keys: str) -> float | None:
    """Try multiple JSONB keys in order; return first coercible non-None value."""
    for key in keys:
        val = data.get(key)
        result = _safe_float(val, label=key)
        if result is not None:
            return result
    return None


# ── Date parsing helper (PLAN-0089 Wave L-5c) ────────────────────────────────


def _safe_date(val: Any, label: str = "") -> _date_cls | None:
    """Coerce a JSONB value to a python ``date``; return None on failure.

    EODHD reports dates as ISO-8601 strings (``"2026-02-12"``). Older payloads
    occasionally embed an ISO datetime (``"2026-02-12T00:00:00"``). Both
    parse identically via ``datetime.fromisoformat`` (Python 3.11+ accepts
    bare ``YYYY-MM-DD``).

    NULL semantics:
      * Empty string / None / common sentinel values → None.
      * Already-a-date / already-a-datetime → coerced cleanly.
      * Unparseable strings → None with a debug log (consistent with
        ``_safe_float``'s policy of "log and continue").
    """
    if val is None:
        return None
    if isinstance(val, _date_cls) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.lower() in {"", "n/a", "na", "none", "null", "0000-00-00", "-"}:
            return None
        # Strip any trailing time portion to be defensive against EODHD
        # mixing "2026-02-12" and "2026-02-12T00:00:00" in the same payload.
        try:
            return datetime.fromisoformat(cleaned).date()
        except ValueError:
            if label:
                logger.debug("snapshot_writer.date_coerce_failed", label=label, raw=cleaned[:50])
            return None
    return None


def _most_recent_financial_row(section_data: Any) -> dict[str, Any]:
    """Extract the most recent row from a nested financial statement section.

    Financial statement sections arrive as:
        {
          "yearly":    {"2023-12-31": {...row...}, "2022-12-31": {...row...}},
          "quarterly": {"2024-09-30": {...row...}, ...}
        }

    We prefer the most recent *yearly* entry (trailing-twelve-months semantics).
    Falls back to the most recent quarterly entry if no yearly data exists.
    Returns {} when section_data is missing or malformed.

    NOTE: Periodicity tracking (PLAN-0095 T-W1-04, BP-542) lives in
    :func:`_most_recent_financial_row_with_period` so existing callers that
    only need the row dict are unchanged.
    """
    row, _periodicity = _most_recent_financial_row_with_period(section_data)
    return row


def _most_recent_financial_row_with_period(section_data: Any) -> tuple[dict[str, Any], str | None]:
    """Extract the most recent row AND the periodicity it was sourced from.

    PLAN-0095 T-W1-04 / BP-542: the snapshot writer needs to record whether
    each derived metric came from a QUARTERLY or ANNUAL source row. This
    helper returns both so the caller can persist the periodicity into the
    new ``period_type_*`` columns on ``instrument_fundamentals_snapshot``.

    Returns:
        Tuple ``(row, periodicity)`` where:
          * ``row`` is the most-recent row dict (``{}`` if none found).
          * ``periodicity`` is ``"ANNUAL"`` when the row came from the
            yearly bucket, ``"QUARTERLY"`` when it came from the quarterly
            bucket, or ``None`` when no row was found.
    """
    if not isinstance(section_data, dict):
        return ({}, None)
    # Map the EODHD bucket label to the canonical PeriodType value name.
    for period_label, periodicity in (("yearly", "ANNUAL"), ("quarterly", "QUARTERLY")):
        sub = section_data.get(period_label)
        if not isinstance(sub, dict) or not sub:
            continue
        # Sort date strings descending — ISO-8601 date strings sort correctly as text
        most_recent_key = max(sub.keys())
        row = sub[most_recent_key]
        return (row if isinstance(row, dict) else {}, periodicity)
    return ({}, None)


def derive_fundamentals_snapshot(
    *,
    highlights: dict[str, Any],
    cash_flow: dict[str, Any],
    income: dict[str, Any],
    balance: dict[str, Any],
    technicals: dict[str, Any],
    splits_dividends: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute all snapshot fields from EODHD section data.

    Args:
        highlights:       Contents of the ``highlights`` section (flat dict).
        cash_flow:        Most-recent row from ``cash_flow`` financial statement.
        income:           Most-recent row from ``income_statement`` financial statement.
        balance:          Most-recent row from ``balance_sheet`` financial statement.
        technicals:       Contents of the ``technicals_snapshot`` section (flat dict).
        splits_dividends: Contents of the ``splits_dividends`` section (flat dict).
                          Wave L-5c: source for ``next_dividend_date``.
                          Optional + defaulted to ``None`` for backward
                          compatibility — older callers that pass only the
                          five original sections keep working.

    Returns a dict with keys matching the ``instrument_fundamentals_snapshot``
    columns.  Values are Python int/float/str/date or None.
    """
    # ── EPS TTM ───────────────────────────────────────────────────────────────
    eps_ttm = _try_keys(highlights, "EarningsShare", "DilutedEpsTTM", "eps", "EPS")

    # ── Beta ──────────────────────────────────────────────────────────────────
    beta = _try_keys(technicals, "Beta", "beta")

    # ── Average volume 30D ────────────────────────────────────────────────────
    # EODHD NOTE: "AverageVolume" present in Technicals for most large-cap US
    # equities; small-cap / foreign listings may lack it → NULL.
    avg_volume_raw = _try_keys(technicals, "AverageVolume", "averageVolume")
    avg_volume_30d: int | None = int(avg_volume_raw) if avg_volume_raw is not None else None

    # ── Operating Cash Flow ───────────────────────────────────────────────────
    operating_cf = _try_keys(
        cash_flow,
        "operatingCashFlow",
        "totalCashFromOperatingActivities",
        "OperatingCashFlow",
    )

    # ── Capital Expenditures (CapEx) ──────────────────────────────────────────
    # WHY abs(): EODHD reports capex as negative (cash outflow).  We store the
    # absolute value for UI clarity; FCF derivation below subtracts it.
    capex_raw = _try_keys(cash_flow, "capitalExpenditures", "CapitalExpenditures")
    capex: float | None = abs(capex_raw) if capex_raw is not None else None

    # ── Free Cash Flow (derived) ──────────────────────────────────────────────
    free_cash_flow: float | None = None
    if operating_cf is not None and capex is not None:
        free_cash_flow = operating_cf - capex

    # ── FCF Margin (derived) ──────────────────────────────────────────────────
    fcf_margin: float | None = None
    if free_cash_flow is not None:
        revenue = _try_keys(highlights, "RevenueTTM", "Revenue", "revenue")
        if revenue and revenue != 0:
            fcf_margin = free_cash_flow / revenue

    # ── Interest Coverage (derived) ───────────────────────────────────────────
    interest_coverage: float | None = None
    ebit = _try_keys(income, "ebit", "EBIT", "operatingIncome")
    interest_expense = _try_keys(income, "interestExpense", "InterestExpense")
    if ebit is not None and interest_expense is not None and interest_expense != 0:
        interest_coverage = ebit / abs(interest_expense)

    # ── Net Debt / EBITDA (derived) ───────────────────────────────────────────
    net_debt_to_ebitda: float | None = None
    ebitda = _try_keys(highlights, "EBITDA", "EBITDAttm", "ebitda")
    if ebitda is not None and ebitda > 0:
        net_debt = _try_keys(balance, "netDebt", "NetDebt")
        if net_debt is None:
            total_debt = _try_keys(balance, "shortLongTermDebtTotal", "shortLongTermDebt", "longTermDebt")
            cash = _try_keys(balance, "cashAndEquivalents", "cash", "Cash")
            if total_debt is not None and cash is not None:
                net_debt = total_debt - cash
        if net_debt is not None:
            net_debt_to_ebitda = net_debt / ebitda

    # ── Credit Rating ─────────────────────────────────────────────────────────
    # EODHD standard Fundamentals endpoint does NOT expose credit ratings.
    # Documented limitation — always NULL until a future data provider is wired.
    credit_rating: str | None = None

    # ── Next Dividend Date (Wave L-5c) ────────────────────────────────────────
    # EODHD ``SplitsDividends`` carries two relevant fields:
    #   * ``DividendDate``    — next *payment* date (preferred for UI).
    #   * ``ExDividendDate``  — next *ex-dividend* date (fallback).
    # We prefer the payment date because the screener UX is "when does the
    # company next pay a dividend" — but the ex-div date is a strict
    # ordering-equivalent fallback (always within a few days of payment).
    # ETFs / non-dividend payers / corrupt rows all resolve to None.
    next_dividend_date: _date_cls | None = None
    if splits_dividends:
        next_dividend_date = _safe_date(splits_dividends.get("DividendDate"), label="DividendDate")
        if next_dividend_date is None:
            next_dividend_date = _safe_date(splits_dividends.get("ExDividendDate"), label="ExDividendDate")

    return {
        "eps_ttm": eps_ttm,
        "beta": beta,
        "avg_volume_30d": avg_volume_30d,
        "operating_cash_flow": operating_cf,
        "capex": capex,
        "free_cash_flow": free_cash_flow,
        "fcf_margin": fcf_margin,
        "interest_coverage": interest_coverage,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "credit_rating": credit_rating,
        # Wave L-5c — populated from EODHD splits_dividends section. Earnings
        # date is NOT populated here because it requires a DB lookup against
        # ``earnings_calendar`` — see :func:`fetch_next_earnings_date`.
        "next_dividend_date": next_dividend_date,
    }


# ── Earnings calendar lookup (PLAN-0089 Wave L-5c) ───────────────────────────

# Read-only SELECT against the ``earnings_calendar`` table — used by the
# snapshot writer to populate ``instrument_fundamentals_snapshot.next_earnings_date``.
#
# Until Wave L-5b lands the worker that populates ``earnings_calendar`` is
# deferred, so this query typically returns NULL today. We still wire the
# read so that on the day L-5b ships, the screener column auto-populates
# without any further code change.
_NEXT_EARNINGS_SQL = text(
    "SELECT MIN(report_date) AS next_date FROM earnings_calendar "
    "WHERE instrument_id = :iid AND report_date >= CURRENT_DATE"
)


async def fetch_next_earnings_date(session: AsyncSession, instrument_id: str) -> _date_cls | None:
    """Return the next future ``report_date`` from ``earnings_calendar``.

    Returns ``None`` when no future row exists for the instrument (the
    typical case until L-5b ships and starts populating the table).

    R12: stays in the infrastructure layer — uses ``AsyncSession`` directly,
    no domain repository indirection because this is a single-cell lookup.
    """
    row = (await session.execute(_NEXT_EARNINGS_SQL, {"iid": instrument_id})).one_or_none()
    if row is None or row.next_date is None:
        return None
    # SQLAlchemy returns python ``date`` for PG DATE; trust the type.
    next_date: _date_cls = row.next_date
    return next_date


# ── DB write helper ───────────────────────────────────────────────────────────

_UPSERT_SQL = text("""
    INSERT INTO instrument_fundamentals_snapshot (
        instrument_id,
        eps_ttm, beta, avg_volume_30d,
        operating_cash_flow, capex, free_cash_flow, fcf_margin,
        interest_coverage, net_debt_to_ebitda, credit_rating,
        period_type_income, period_type_cash_flow, period_type_balance,
        next_earnings_date, next_dividend_date,
        updated_at
    ) VALUES (
        :instrument_id,
        :eps_ttm, :beta, :avg_volume_30d,
        :operating_cash_flow, :capex, :free_cash_flow, :fcf_margin,
        :interest_coverage, :net_debt_to_ebitda, :credit_rating,
        :period_type_income, :period_type_cash_flow, :period_type_balance,
        :next_earnings_date, :next_dividend_date,
        now()
    )
    ON CONFLICT (instrument_id) DO UPDATE SET
        -- F-Q2-03 (PLAN-0050 QA iter-2): COALESCE keeps previously-valid data intact
        -- when a partial EODHD re-poll is missing some sections (e.g. no cash-flow
        -- section → operating_cash_flow, capex, free_cash_flow, fcf_margin would all
        -- be NULL in the new payload).  Plain EXCLUDED.col would silently clobber the
        -- stored value with NULL — a data-loss regression on every partial refresh.
        --
        -- Policy: "prefer the incoming value; fall back to existing if incoming is NULL"
        -- This is the same COALESCE pattern used for prediction_markets.market_slug
        -- (PLAN-0049 iter-1 F-QAC-02) and for document_source_metadata title/url.
        --
        -- updated_at is intentionally unconditional — it tracks when the snapshot was
        -- last *seen* by the ingest pipeline, not when any data field changed.
        eps_ttm             = COALESCE(EXCLUDED.eps_ttm,
                               instrument_fundamentals_snapshot.eps_ttm),
        beta                = COALESCE(EXCLUDED.beta,
                               instrument_fundamentals_snapshot.beta),
        avg_volume_30d      = COALESCE(EXCLUDED.avg_volume_30d,
                               instrument_fundamentals_snapshot.avg_volume_30d),
        operating_cash_flow = COALESCE(EXCLUDED.operating_cash_flow,
                               instrument_fundamentals_snapshot.operating_cash_flow),
        capex               = COALESCE(EXCLUDED.capex,
                               instrument_fundamentals_snapshot.capex),
        free_cash_flow      = COALESCE(EXCLUDED.free_cash_flow,
                               instrument_fundamentals_snapshot.free_cash_flow),
        fcf_margin          = COALESCE(EXCLUDED.fcf_margin,
                               instrument_fundamentals_snapshot.fcf_margin),
        interest_coverage   = COALESCE(EXCLUDED.interest_coverage,
                               instrument_fundamentals_snapshot.interest_coverage),
        net_debt_to_ebitda  = COALESCE(EXCLUDED.net_debt_to_ebitda,
                               instrument_fundamentals_snapshot.net_debt_to_ebitda),
        credit_rating       = COALESCE(EXCLUDED.credit_rating,
                               instrument_fundamentals_snapshot.credit_rating),
        -- PLAN-0095 T-W1-04 / BP-542: track which periodicity each derived
        -- metric was sourced from. COALESCE matches the policy above so a
        -- partial payload (e.g. no income_statement this cycle) does not
        -- wipe out the previously-recorded periodicity tag.
        period_type_income    = COALESCE(EXCLUDED.period_type_income,
                               instrument_fundamentals_snapshot.period_type_income),
        period_type_cash_flow = COALESCE(EXCLUDED.period_type_cash_flow,
                               instrument_fundamentals_snapshot.period_type_cash_flow),
        period_type_balance   = COALESCE(EXCLUDED.period_type_balance,
                               instrument_fundamentals_snapshot.period_type_balance),
        -- PLAN-0089 Wave L-5c: calendar fields use the same COALESCE policy as
        -- every other field — a partial payload (no splits_dividends section,
        -- or no earnings_calendar row this cycle) must not silently clobber
        -- a previously-recorded value with NULL.
        next_earnings_date  = COALESCE(EXCLUDED.next_earnings_date,
                               instrument_fundamentals_snapshot.next_earnings_date),
        next_dividend_date  = COALESCE(EXCLUDED.next_dividend_date,
                               instrument_fundamentals_snapshot.next_dividend_date),
        updated_at          = now()
""")


async def upsert_snapshot(session: AsyncSession, instrument_id: str, snap: dict[str, Any]) -> None:
    """UPSERT one snapshot row into ``instrument_fundamentals_snapshot``.

    WHY ON CONFLICT DO UPDATE: the consumer may process the same fundamentals
    event more than once (Kafka at-least-once).  ON CONFLICT makes this call
    idempotent — a second run updates all columns to the same values.

    Args:
        session:       SQLAlchemy async write session (from UoW._write()).
        instrument_id: UUID string of the instrument (PK).
        snap:          Dict returned by ``derive_fundamentals_snapshot()``.

    PLAN-0095 T-W1-04 / BP-542: the snap dict may carry three optional
    ``period_type_*`` keys recording the periodicity of each source row.
    Missing keys default to ``None`` (preserves existing column value under
    the COALESCE-based UPSERT policy).
    """
    await session.execute(
        _UPSERT_SQL,
        {
            "instrument_id": instrument_id,
            "eps_ttm": snap.get("eps_ttm"),
            "beta": snap.get("beta"),
            "avg_volume_30d": snap.get("avg_volume_30d"),
            "operating_cash_flow": snap.get("operating_cash_flow"),
            "capex": snap.get("capex"),
            "free_cash_flow": snap.get("free_cash_flow"),
            "fcf_margin": snap.get("fcf_margin"),
            "interest_coverage": snap.get("interest_coverage"),
            "net_debt_to_ebitda": snap.get("net_debt_to_ebitda"),
            "credit_rating": snap.get("credit_rating"),
            "period_type_income": snap.get("period_type_income"),
            "period_type_cash_flow": snap.get("period_type_cash_flow"),
            "period_type_balance": snap.get("period_type_balance"),
            # Wave L-5c — both default to None, the COALESCE-based UPSERT
            # policy preserves previously-recorded values on partial payloads.
            "next_earnings_date": snap.get("next_earnings_date"),
            "next_dividend_date": snap.get("next_dividend_date"),
        },
    )
