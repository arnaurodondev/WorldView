"""Canonicalization logic — converts raw provider bytes to canonical JSONL.

Pure data transformation: no I/O, no DB, no object storage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from market_ingestion.domain.enums import DatasetType

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import CanonicalSerializer, ProviderFetchResult
    from market_ingestion.domain.entities.ingestion_task import IngestionTask

# Dataset types that use the passthrough (envelope) serialization path.
# These have no domain canonical model; they are wrapped in a self-describing
# envelope so downstream consumers can identify and parse them without
# needing provider-specific logic.
_PASSTHROUGH_TYPES: frozenset[DatasetType] = frozenset(
    {
        DatasetType.ECONOMIC_EVENTS,
        DatasetType.MACRO_INDICATOR,
        DatasetType.INSIDER_TRANSACTIONS,
        DatasetType.EARNINGS_CALENDAR,
        DatasetType.NEWS_SENTIMENT,
        DatasetType.YIELD_CURVE,
        DatasetType.MARKET_CAP,
    }
)


def canonicalize_task(
    task: IngestionTask,
    fetch_result: ProviderFetchResult,
    serializer: CanonicalSerializer,
) -> tuple[bytes, int]:
    """Convert raw provider bytes to canonical JSONL.

    Returns ``(canonical_bytes, row_count)`` where ``row_count`` is the number
    of records in the output (1 for passthrough/fundamentals, N for OHLCV/quotes).

    Raises
    ------
    ProviderDataError / ValueError / KeyError / TypeError
        Caller must catch and dead-letter the task.
    """
    raw_data = json.loads(fetch_result.raw_data.decode())

    if task.dataset_type == DatasetType.OHLCV:
        # EODHD (and most providers) return a JSON array at the top level.
        bars = raw_data if isinstance(raw_data, list) else raw_data.get("data", [raw_data])
        enriched = [
            {**bar, "symbol": task.symbol, "exchange": task.exchange or "", "source": str(task.provider)}
            for bar in bars
        ]
        canon = serializer.serialize_ohlcv(enriched)
        lines = [line for line in canon.split(b"\n") if line.strip()]
        return canon, len(lines)

    if task.dataset_type == DatasetType.QUOTES:
        # EODHD real-time endpoint returns a single JSON object (not a list).
        # Normalise to a list and remap provider-specific field names to canonical
        # names so CanonicalQuote.from_dict() can parse the result.
        raw_quotes = raw_data if isinstance(raw_data, list) else [raw_data]
        enriched_quotes = [_remap_quote(q, task.symbol, task.exchange or "", str(task.provider)) for q in raw_quotes]
        canon = serializer.serialize_quotes(enriched_quotes)
        lines = [line for line in canon.split(b"\n") if line.strip()]
        return canon, len(lines)

    # Passthrough dataset types — no domain-specific canonical model exists.
    # Wrap raw JSON in a self-describing envelope so downstream consumers
    # can identify and parse the payload without needing provider-specific
    # parsing logic. Returns row_count=1 (one envelope record per task).
    if task.dataset_type in _PASSTHROUGH_TYPES:
        canon = serializer.serialize_passthrough(
            raw_data=raw_data,
            dataset_type=str(task.dataset_type),
            symbol=task.symbol,
            source=str(task.provider),
        )
        return canon, 1

    # FUNDAMENTALS (default)
    # Map raw provider response to the section-keyed canonical format expected
    # by the FundamentalsConsumer in market-data.
    raw_dict = raw_data if isinstance(raw_data, dict) else {}
    sections = _map_fundamentals_sections(raw_dict, symbol=task.symbol, source=str(task.provider))
    # Enrich with task-level metadata (exchange, period/variant, report_date)
    sections["exchange"] = task.exchange or ""
    sections["period"] = task.variant or "annual"
    if "report_date" not in sections or not sections["report_date"]:
        sections["report_date"] = raw_dict.get("report_date") or datetime.now(tz=UTC).date().isoformat()
    canon = serializer.serialize_fundamentals(sections, variant=task.variant)
    return canon, 1


# ---------------------------------------------------------------------------
# Quote remapping helper
# ---------------------------------------------------------------------------


def _remap_quote(raw: dict, symbol: str, exchange: str, source: str) -> dict:
    """Normalise a provider quote dict to CanonicalQuote field names.

    EODHD real-time response uses ``close`` for the last price and carries a
    Unix epoch ``timestamp``.  CanonicalQuote requires ``last`` and an ISO-8601
    ``timestamp`` string, plus ``bid`` / ``ask`` which EODHD does not supply
    (we fall back to ``close``).
    """
    # Resolve last price: prefer explicit "last", fall back to "close"
    last = raw.get("last") or raw.get("close", 0.0)

    if not last:
        # FIX-Q1: Log — do not raise; data may be legitimately halted
        from observability.logging import get_logger  # type: ignore[import-untyped]

        get_logger(__name__).warning(
            "quote_zero_or_missing_price",
            symbol=symbol,
            exchange=exchange,
            raw_keys=list(raw.keys()),
        )
        last = 0.0

    # Convert Unix epoch timestamp to ISO-8601 if necessary
    ts_raw = raw.get("timestamp")
    if isinstance(ts_raw, int | float):
        timestamp = datetime.fromtimestamp(ts_raw, tz=UTC).isoformat()
    else:
        timestamp = str(ts_raw) if ts_raw is not None else datetime.now(tz=UTC).isoformat()

    return {
        "symbol": symbol,
        "exchange": exchange,
        "source": source,
        "bid": raw.get("bid") or last,
        "ask": raw.get("ask") or last,
        "last": last,
        "volume": raw.get("volume", 0),
        "timestamp": timestamp,
        "bid_size": raw.get("bid_size"),
        "ask_size": raw.get("ask_size"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "open": raw.get("open"),
        "prev_close": raw.get("prev_close") or raw.get("previousClose"),
    }


# ---------------------------------------------------------------------------
# Fundamentals section mapping helper
# ---------------------------------------------------------------------------


def _map_fundamentals_sections(raw: dict, symbol: str, source: str) -> dict:
    """Map a full EODHD fundamentals response to the section-keyed canonical format.

    Keys in the returned dict correspond to the ``_SECTION_HANDLERS`` mapping in
    the market-data ``FundamentalsConsumer``.  Missing sections are omitted so
    the consumer skips them cleanly.

    ETF handling: EODHD returns a different top-level structure for ETFs/funds:
    ``['General', 'Technicals', 'ETF_Data']`` instead of the stock sections.
    We build a synthetic ``highlights`` dict from ``ETF_Data`` using the same
    field names the metric_extractor already understands.
    """
    general = raw.get("General") or {}
    instrument_type = (general.get("Type") or "").upper()
    is_etf = instrument_type in ("ETF", "FUND", "MUTUALFUND", "MUTUAL FUND")

    sections: dict = {
        "symbol": symbol,
        "source": source,
    }

    def _add(key: str, value: object) -> None:
        if value:
            sections[key] = value

    if is_etf:
        # WHY separate branch: EODHD ETF responses omit Highlights/Valuation/Financials/
        # Earnings entirely and replace them with ETF_Data. Without this branch, all
        # fundamentals fields for ETFs like QQQ silently remain NULL in the DB.
        etf_data = raw.get("ETF_Data") or {}

        # Build a synthetic highlights dict using the exact key names metric_extractor.py
        # looks for (FundamentalsSection.HIGHLIGHTS metric defs).
        synthetic_highlights: dict = {}

        # Yield → DividendYield (stored as "0.4200" string by EODHD; extractor coerces to float)
        if etf_data.get("Yield") not in (None, "", "0.00", "0"):
            synthetic_highlights["DividendYield"] = etf_data["Yield"]

        # TotalAssets → MarketCapitalization (AUM proxy for ETFs).
        # WHY two key spellings: EODHD uses "TotalAssets" (camelCase without separator)
        # in QQQ/SPY responses. "Total_Assets" and "Portfolio_Net_Assets" are present
        # in some older / non-US fund responses — keep all three as fallback.
        total_assets = (
            etf_data.get("TotalAssets") or etf_data.get("Total_Assets") or etf_data.get("Portfolio_Net_Assets")
        )
        if total_assets:
            synthetic_highlights["MarketCapitalization"] = total_assets

        # NaV → no canonical equivalent; skip
        # Net_Expense_Ratio → no current metric def; skip (future: expense_ratio)

        _add("highlights", synthetic_highlights or None)
        _add("technicals_snapshot", raw.get("Technicals"))
        _add("company_profile", general)
        # ETF_Data contains sector weights and top holdings — store as fund_holders proxy
        # so the data is persisted even if not yet surfaced in the UI
        _add("fund_holders", etf_data if etf_data else None)
    else:
        financials = raw.get("Financials") or {}
        earnings = raw.get("Earnings") or {}
        splits_divs = raw.get("SplitsDividends") or {}

        _add("income_statement", financials.get("Income_Statement"))
        _add("balance_sheet", financials.get("Balance_Sheet"))
        _add("cash_flow", financials.get("Cash_Flow"))
        _add("highlights", raw.get("Highlights"))  # FIX-F10: separated from valuation_ratios
        _add("valuation_ratios", raw.get("Valuation"))  # FIX-F10: Valuation only
        _add("technicals_snapshot", raw.get("Technicals"))
        _add("share_statistics", raw.get("SharesStats"))
        _add("splits_dividends", raw.get("SplitsDividends"))
        _add("analyst_consensus", raw.get("AnalystRatings"))
        _add("earnings_history", earnings.get("History"))
        _add("earnings_trend", earnings.get("Trend"))
        _add("earnings_annual_trend", earnings.get("Annual"))
        _add("dividend_history", splits_divs.get("NumberDividendsByYear"))  # FIX-F5: was "Dividends"
        _add("outstanding_shares", raw.get("outstandingShares"))
        _add("company_profile", general)  # FIX-F4
        _add("institutional_holders", (raw.get("Holders") or {}).get("Institutions"))  # FIX-F6
        _add("fund_holders", (raw.get("Holders") or {}).get("Funds"))  # FIX-F6
        _add("insider_transactions_snapshot", raw.get("InsiderTransactions"))  # FIX-F7

    return sections
