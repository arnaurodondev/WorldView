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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from market_data.domain.enums import FundamentalsSection
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


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
    if isinstance(val, bool):
        return None

    if isinstance(val, str):
        cleaned = val.strip()
        if cleaned.lower() in {"", "n/a", "na", "none", "null", "nan", "-", "--"}:
            return None
        # Parenthesized negatives are common in finance feeds: (123.4) -> -123.4
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        cleaned = cleaned.replace(",", "")
        try:
            return Decimal(cleaned)
        except (InvalidOperation, ValueError, TypeError):
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
    # WHY TECHNICALS_SNAPSHOT: beta, moving averages, and short interest are stored
    # in the EODHD "Technicals" section.  We add beta + avg_volume_30d here so the
    # backfill script can read them from the fundamental_metrics key-value table
    # when computing the snapshot row (no extra EODHD call required).
    FundamentalsSection.TECHNICALS_SNAPSHOT: [
        _MetricDef("beta", ("Beta", "beta")),
        # EODHD exposes the 30-day average volume as "AverageDailyVolumeLTM"
        # in the Technicals.AverageVolume field (varies by API version).
        # All alias forms are tried in order; first match wins.
        _MetricDef("avg_volume_30d", ("AverageVolume", "averageVolume", "AvgVolume", "avg_volume")),
    ],
    FundamentalsSection.ANALYST_CONSENSUS: [
        _MetricDef("target_price", ("TargetPrice", "targetPrice", "target_price")),
        _MetricDef(
            "analyst_rating",
            ("Rating", "rating"),
            text_only=True,
        ),
        _MetricDef("analyst_buy", ("Buy", "buy")),
        _MetricDef("analyst_hold", ("Hold", "hold")),
        _MetricDef("analyst_sell", ("Sell", "sell")),
        _MetricDef("analyst_strong_buy", ("StrongBuy", "strongBuy", "strong_buy")),
        _MetricDef("analyst_strong_sell", ("StrongSell", "strongSell", "strong_sell")),
    ],
    FundamentalsSection.VALUATION_RATIOS: [
        _MetricDef("pe_ratio", ("TrailingPE", "PE", "pe_ratio", "trailingPE")),
        _MetricDef("pb_ratio", ("PriceBookMRQ", "PB", "price_to_book", "priceBookMRQ")),
        _MetricDef("enterprise_value", ("EnterpriseValue", "enterpriseValue", "enterprise_value")),
        _MetricDef("forward_pe", ("ForwardPE", "forwardPE", "forward_pe")),
        _MetricDef(
            "enterprise_value_ebitda",
            ("EnterpriseValueEbitda", "enterpriseValueEbitda", "enterprise_value_ebitda"),
        ),
        _MetricDef(
            "enterprise_value_revenue",
            ("EnterpriseValueRevenue", "enterpriseValueRevenue", "enterprise_value_revenue"),
        ),
        _MetricDef("price_sales_ttm", ("PriceSalesTTM", "priceSalesTTM", "price_sales_ttm")),
    ],
    FundamentalsSection.HIGHLIGHTS: [
        _MetricDef("revenue_ttm", ("RevenueTTM", "Revenue", "revenueTTM", "revenue")),
        _MetricDef("ebitda_ttm", ("EBITDA", "EBITDAttm", "ebitda", "ebitdaTTM")),
        _MetricDef("eps_ttm", ("EarningsShare", "EPS", "earningsShare", "eps")),
        _MetricDef("roe_ttm", ("ReturnOnEquityTTM", "ROE", "returnOnEquityTTM", "roe")),
        _MetricDef("roa_ttm", ("ReturnOnAssetsTTM", "ROA", "returnOnAssetsTTM", "roa")),
        _MetricDef("book_value", ("BookValue", "bookValue", "book_value")),
        _MetricDef("diluted_eps_ttm", ("DilutedEpsTTM", "dilutedEpsTTM", "diluted_eps_ttm")),
        _MetricDef("dividend_share", ("DividendShare", "dividendShare", "dividend_share")),
        _MetricDef("dividend_yield", ("DividendYield", "dividendYield", "dividend_yield")),
        _MetricDef(
            "eps_estimate_current_quarter",
            ("EPSEstimateCurrentQuarter", "epsEstimateCurrentQuarter", "eps_estimate_current_quarter"),
        ),
        _MetricDef(
            "eps_estimate_current_year",
            ("EPSEstimateCurrentYear", "epsEstimateCurrentYear", "eps_estimate_current_year"),
        ),
        _MetricDef(
            "eps_estimate_next_quarter",
            ("EPSEstimateNextQuarter", "epsEstimateNextQuarter", "eps_estimate_next_quarter"),
        ),
        _MetricDef(
            "eps_estimate_next_year",
            ("EPSEstimateNextYear", "epsEstimateNextYear", "eps_estimate_next_year"),
        ),
        _MetricDef("gross_profit_ttm", ("GrossProfitTTM", "grossProfitTTM", "gross_profit_ttm")),
        _MetricDef(
            "market_capitalization",
            ("MarketCapitalization", "marketCapitalization", "market_capitalization"),
        ),
        _MetricDef(
            "market_capitalization_mln",
            ("MarketCapitalizationMln", "marketCapitalizationMln", "market_capitalization_mln"),
        ),
        _MetricDef(
            "operating_margin_ttm",
            ("OperatingMarginTTM", "operatingMarginTTM", "operating_margin_ttm"),
        ),
        _MetricDef("peg_ratio", ("PEGRatio", "pegRatio", "peg_ratio")),
        _MetricDef("pe_ratio", ("PERatio", "peRatio")),
        _MetricDef("profit_margin", ("ProfitMargin", "profitMargin", "profit_margin")),
        _MetricDef(
            "quarterly_earnings_growth_yoy",
            (
                "QuarterlyEarningsGrowthYOY",
                "quarterlyEarningsGrowthYOY",
                "quarterly_earnings_growth_yoy",
            ),
        ),
        _MetricDef(
            "quarterly_revenue_growth_yoy",
            (
                "QuarterlyRevenueGrowthYOY",
                "quarterlyRevenueGrowthYOY",
                "quarterly_revenue_growth_yoy",
            ),
        ),
        _MetricDef(
            "revenue_per_share_ttm",
            ("RevenuePerShareTTM", "revenuePerShareTTM", "revenue_per_share_ttm"),
        ),
        _MetricDef(
            "wall_street_target_price",
            ("WallStreetTargetPrice", "wallStreetTargetPrice", "wall_street_target_price"),
        ),
    ],
    FundamentalsSection.INCOME_STATEMENT: [
        _MetricDef("revenue", ("totalRevenue", "total_revenue", "TotalRevenue")),
        _MetricDef("net_income", ("netIncome", "net_income", "NetIncome")),
        _MetricDef("eps", ("eps", "EPS", "Eps")),
        _MetricDef("cost_of_revenue", ("costOfRevenue", "cost_of_revenue", "CostOfRevenue")),
        _MetricDef("gross_profit", ("grossProfit", "gross_profit", "GrossProfit")),
        _MetricDef("operating_income", ("operatingIncome", "operating_income", "OperatingIncome")),
        _MetricDef("income_before_tax", ("incomeBeforeTax", "income_before_tax", "IncomeBeforeTax")),
        _MetricDef(
            "income_tax_expense",
            ("incomeTaxExpense", "income_tax_expense", "IncomeTaxExpense"),
        ),
        _MetricDef("interest_expense", ("interestExpense", "interest_expense", "InterestExpense")),
        _MetricDef("interest_income", ("interestIncome", "interest_income", "InterestIncome")),
        _MetricDef("ebit", ("ebit", "EBIT")),
        _MetricDef("ebitda", ("ebitda", "EBITDA")),
        _MetricDef(
            "total_operating_expenses",
            ("totalOperatingExpenses", "total_operating_expenses", "TotalOperatingExpenses"),
        ),
        _MetricDef(
            "total_other_income_expense_net",
            (
                "totalOtherIncomeExpenseNet",
                "total_other_income_expense_net",
                "TotalOtherIncomeExpenseNet",
            ),
        ),
        _MetricDef(
            "research_development",
            ("researchDevelopment", "research_development", "ResearchDevelopment"),
        ),
        _MetricDef(
            "selling_general_administrative",
            (
                "sellingGeneralAdministrative",
                "selling_general_administrative",
                "SellingGeneralAdministrative",
            ),
        ),
        _MetricDef(
            "selling_and_marketing_expenses",
            (
                "sellingAndMarketingExpenses",
                "selling_and_marketing_expenses",
                "SellingAndMarketingExpenses",
            ),
        ),
        _MetricDef(
            "net_income_applicable_to_common_shares",
            (
                "netIncomeApplicableToCommonShares",
                "net_income_applicable_to_common_shares",
                "NetIncomeApplicableToCommonShares",
            ),
        ),
        _MetricDef(
            "net_income_from_continuing_ops",
            (
                "netIncomeFromContinuingOps",
                "net_income_from_continuing_ops",
                "NetIncomeFromContinuingOps",
            ),
        ),
    ],
    FundamentalsSection.BALANCE_SHEET: [
        _MetricDef("total_assets", ("totalAssets", "total_assets", "TotalAssets")),
        _MetricDef("total_equity", ("totalStockholderEquity", "total_equity", "TotalStockholderEquity")),
        _MetricDef("long_term_debt", ("longTermDebt", "long_term_debt", "LongTermDebt")),
        _MetricDef("cash", ("cash", "Cash")),
        _MetricDef(
            "cash_and_equivalents",
            ("cashAndEquivalents", "cash_and_equivalents", "CashAndEquivalents"),
        ),
        _MetricDef(
            "cash_and_short_term_investments",
            (
                "cashAndShortTermInvestments",
                "cash_and_short_term_investments",
                "CashAndShortTermInvestments",
            ),
        ),
        _MetricDef("total_liab", ("totalLiab", "total_liab", "TotalLiab")),
        _MetricDef(
            "total_current_assets",
            ("totalCurrentAssets", "total_current_assets", "TotalCurrentAssets"),
        ),
        _MetricDef(
            "total_current_liabilities",
            ("totalCurrentLiabilities", "total_current_liabilities", "TotalCurrentLiabilities"),
        ),
        _MetricDef("short_term_debt", ("shortTermDebt", "short_term_debt", "ShortTermDebt")),
        _MetricDef(
            "short_long_term_debt",
            ("shortLongTermDebt", "short_long_term_debt", "ShortLongTermDebt"),
        ),
        _MetricDef(
            "short_long_term_debt_total",
            ("shortLongTermDebtTotal", "short_long_term_debt_total", "ShortLongTermDebtTotal"),
        ),
        _MetricDef("accounts_payable", ("accountsPayable", "accounts_payable", "AccountsPayable")),
        _MetricDef("net_receivables", ("netReceivables", "net_receivables", "NetReceivables")),
        _MetricDef("inventory", ("inventory", "Inventory")),
        _MetricDef("retained_earnings", ("retainedEarnings", "retained_earnings", "RetainedEarnings")),
        _MetricDef(
            "property_plant_and_equipment_net",
            (
                "propertyPlantAndEquipmentNet",
                "property_plant_and_equipment_net",
                "PropertyPlantAndEquipmentNet",
            ),
        ),
        _MetricDef(
            "common_stock_shares_outstanding",
            (
                "commonStockSharesOutstanding",
                "common_stock_shares_outstanding",
                "CommonStockSharesOutstanding",
            ),
        ),
        _MetricDef("net_debt", ("netDebt", "net_debt", "NetDebt")),
        _MetricDef(
            "net_working_capital",
            ("netWorkingCapital", "net_working_capital", "NetWorkingCapital"),
        ),
    ],
    FundamentalsSection.CASH_FLOW: [
        _MetricDef(
            "operating_cash_flow",
            (
                "operatingCashFlow",
                "operating_cash_flow",
                "OperatingCashFlow",
                "totalCashFromOperatingActivities",
                "TotalCashFromOperatingActivities",
            ),
        ),
        _MetricDef(
            "capital_expenditures",
            ("capitalExpenditures", "capital_expenditures", "CapitalExpenditures"),
        ),
        _MetricDef("free_cash_flow", ("freeCashFlow", "free_cash_flow", "FreeCashFlow")),
        _MetricDef(
            "total_cash_from_financing_activities",
            (
                "totalCashFromFinancingActivities",
                "total_cash_from_financing_activities",
                "TotalCashFromFinancingActivities",
            ),
        ),
        _MetricDef(
            "total_cashflows_from_investing_activities",
            (
                "totalCashflowsFromInvestingActivities",
                "total_cashflows_from_investing_activities",
                "TotalCashflowsFromInvestingActivities",
            ),
        ),
        _MetricDef("dividends_paid", ("dividendsPaid", "dividends_paid", "DividendsPaid")),
        _MetricDef("net_borrowings", ("netBorrowings", "net_borrowings", "NetBorrowings")),
        _MetricDef("depreciation", ("depreciation", "Depreciation")),
        # WHY: The following 6 metrics were silently dropped on every EODHD ingest
        # cycle despite being present in every fundamentals payload.  They are
        # high-value inputs for the fundamentals screener and FCF quality analysis:
        #   stock_based_compensation  — non-cash SBC add-back in OCF reconciliation
        #   end_period_cash_flow      — end-of-period cash balance (cash waterfall)
        #   begin_period_cash_flow    — beginning-of-period cash balance (delta check)
        #   change_in_working_capital — working capital change in OCF (quality signal)
        #   sale_purchase_of_stock    — net share buybacks / issuances (capital return)
        #   net_income_cash_flow      — net income OCF reconciliation starting line
        # No schema change needed: fundamental_metrics is a generic key-value store.
        # Historical data can be backfilled from cash_flow_statements.data (83 434 rows
        # present as of 2026-06-06) by re-running the extractor against that JSONB.
        _MetricDef("stock_based_compensation", ("stockBasedCompensation",)),
        _MetricDef("end_period_cash_flow", ("endPeriodCashFlow",)),
        _MetricDef("begin_period_cash_flow", ("beginPeriodCashFlow",)),
        _MetricDef("change_in_working_capital", ("changeInWorkingCapital",)),
        _MetricDef("sale_purchase_of_stock", ("salePurchaseOfStock",)),
        # EODHD field name is changeToNetincome (lowercase 'i') — not a typo.
        _MetricDef("net_income_cash_flow", ("changeToNetincome",)),
    ],
}

# Sections in the catalog (for fast membership check)
_CATALOGUED_SECTIONS: frozenset[FundamentalsSection] = frozenset(_METRIC_CATALOG.keys())

# WHY: EODHD Cash_Flow rows always include these three structural / metadata fields
# alongside the numeric metrics.  They are not metrics and should never appear in
# the unmapped_keys warning — excluding them prevents inflating the warning count
# by 3 (21 → 24) on every ingest cycle and eliminates false noise in monitoring.
_CASH_FLOW_ADMIN_KEYS: frozenset[str] = frozenset({"date", "filing_date", "currency_symbol"})


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
    matched_keys: set[str] = set()
    section_value = str(section.value) if hasattr(section, "value") else str(section)

    for metric_def in _METRIC_CATALOG[section]:
        # Try each alias key until we find one present in data
        raw_value: Any = None
        found = False
        for key in metric_def.json_keys:
            if key in data:
                raw_value = data[key]
                found = True
                matched_keys.add(key)
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
            if value_numeric is None:
                # Null or non-coercible numeric value → skip this metric.
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
            ),
        )

    if data:
        # Exclude structural / metadata keys that are never metrics.  For Cash_Flow
        # sections this prevents date, filing_date, and currency_symbol from appearing
        # in the unmapped_keys warning and inflating the count on every ingest cycle.
        unmapped_keys = sorted([k for k in data if k not in matched_keys and k not in _CASH_FLOW_ADMIN_KEYS])
        if unmapped_keys:
            payload = {
                "section": section_value,
                "instrument_id": instrument_id,
                "period_type": period_type,
                "unmapped_keys_count": len(unmapped_keys),
                "unmapped_keys_sample": unmapped_keys[:10],
            }
            if len(unmapped_keys) >= 20:
                logger.warning("metric_extractor.unmapped_keys", **payload)
            else:
                logger.debug("metric_extractor.unmapped_keys", **payload)

    return rows
