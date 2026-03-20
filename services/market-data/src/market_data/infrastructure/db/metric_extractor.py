"""Metric extractor: maps fundamentals section JSONB data to narrow metric rows.

Extracts a fixed catalog of metrics from ``FundamentalsRecord.data`` using
known EODHD JSONB keys (with alias support for provider key variants).
Produces ``MetricRow`` tuples ready for upsert into ``fundamental_metrics``.

Numeric coercion: values may arrive as native numbers, numeric strings, or
null.  The extractor attempts ``Decimal(str(val))`` and falls back to ``None``
for non-coercible values.  Textual metrics (e.g. ``analyst_rating``) are
stored in ``value_text`` and optionally parsed to ``value_numeric``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from market_data.domain.enums import FundamentalsSection

if TYPE_CHECKING:
    from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class MetricRow:
    """A single metric value ready for upsert into fundamental_metrics."""

    instrument_id: str
    as_of_date: date
    metric: str
    value_numeric: Decimal | None
    value_text: str | None
    period_type: str
    section: str
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class _MetricDef:
    """Definition of a metric to extract from a section's JSONB data."""

    metric_name: str
    json_keys: tuple[str, ...]  # alias list; first match wins
    text_only: bool = False  # store in value_text, attempt numeric parse


def _coerce_numeric(val: Any) -> Decimal | None:
    """Attempt to coerce a value to Decimal.  Returns None on failure."""
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


# ── Metric catalog ────────────────────────────────────────────────────────────
# Map from FundamentalsSection → list of metric definitions.
# Each definition specifies the canonical metric name and the EODHD JSONB
# key aliases to try (first match wins).

_METRIC_CATALOG: dict[FundamentalsSection, list[_MetricDef]] = {
    FundamentalsSection.ANALYST_CONSENSUS: [
        _MetricDef("target_price", ("TargetPrice", "targetPrice", "target_price")),
        _MetricDef(
            "analyst_rating",
            ("Rating", "rating"),
            text_only=True,
        ),
    ],
    FundamentalsSection.VALUATION_RATIOS: [
        _MetricDef("pe_ratio", ("TrailingPE", "PE", "pe_ratio", "trailingPE")),
        _MetricDef("pb_ratio", ("PriceBookMRQ", "PB", "price_to_book", "priceBookMRQ")),
        _MetricDef("enterprise_value", ("EnterpriseValue", "enterpriseValue", "enterprise_value")),
    ],
    FundamentalsSection.HIGHLIGHTS: [
        _MetricDef("revenue_ttm", ("RevenueTTM", "Revenue", "revenueTTM", "revenue")),
        _MetricDef("ebitda_ttm", ("EBITDA", "EBITDAttm", "ebitda", "ebitdaTTM")),
        _MetricDef("eps_ttm", ("EarningsShare", "EPS", "earningsShare", "eps")),
        _MetricDef("roe_ttm", ("ReturnOnEquityTTM", "ROE", "returnOnEquityTTM", "roe")),
        _MetricDef("roa_ttm", ("ReturnOnAssetsTTM", "ROA", "returnOnAssetsTTM", "roa")),
    ],
    FundamentalsSection.INCOME_STATEMENT: [
        _MetricDef("revenue", ("totalRevenue", "total_revenue", "TotalRevenue")),
        _MetricDef("net_income", ("netIncome", "net_income", "NetIncome")),
        _MetricDef("eps", ("eps", "EPS", "Eps")),
    ],
    FundamentalsSection.BALANCE_SHEET: [
        _MetricDef("total_assets", ("totalAssets", "total_assets", "TotalAssets")),
        _MetricDef("total_equity", ("totalStockholderEquity", "total_equity", "TotalStockholderEquity")),
        _MetricDef("long_term_debt", ("longTermDebt", "long_term_debt", "LongTermDebt")),
    ],
    FundamentalsSection.CASH_FLOW: [
        _MetricDef("operating_cash_flow", ("operatingCashFlow", "operating_cash_flow", "OperatingCashFlow")),
    ],
}

# Sections in the catalog (for fast membership check)
_CATALOGUED_SECTIONS: frozenset[FundamentalsSection] = frozenset(_METRIC_CATALOG.keys())


def extract_metrics(
    instrument_id: str,
    section: FundamentalsSection,
    period_type: str,
    as_of_date: date,
    data: dict[str, Any],
    ingested_at: datetime,
) -> list[MetricRow]:
    """Extract metric rows from a single fundamentals record's JSONB data.

    Returns an empty list if the section is not in the metric catalog or
    if no catalogued keys are present in ``data``.
    """
    if section not in _CATALOGUED_SECTIONS:
        return []

    rows: list[MetricRow] = []
    section_value = str(section.value) if hasattr(section, "value") else str(section)

    for metric_def in _METRIC_CATALOG[section]:
        # Try each alias key until we find one present in data
        raw_value: Any = None
        found = False
        for key in metric_def.json_keys:
            if key in data:
                raw_value = data[key]
                found = True
                break

        if not found:
            continue

        value_numeric: Decimal | None = None
        value_text: str | None = None

        if metric_def.text_only:
            value_text = str(raw_value) if raw_value is not None else None
            value_numeric = _coerce_numeric(raw_value)  # attempt numeric parse
        else:
            value_numeric = _coerce_numeric(raw_value)
            if value_numeric is None and raw_value is not None:
                # Non-coercible numeric → skip this metric
                continue

        rows.append(
            MetricRow(
                instrument_id=instrument_id,
                as_of_date=as_of_date,
                metric=metric_def.metric_name,
                value_numeric=value_numeric,
                value_text=value_text,
                period_type=period_type,
                section=section_value,
                ingested_at=ingested_at,
            )
        )

    return rows
