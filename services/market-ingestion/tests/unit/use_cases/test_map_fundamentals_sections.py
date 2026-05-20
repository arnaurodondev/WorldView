"""Unit tests for _map_fundamentals_sections — stock and ETF branches."""

from __future__ import annotations

import pytest
from market_ingestion.application.use_cases.execute_task import _map_fundamentals_sections

pytestmark = pytest.mark.unit

# ── Stock fixture ────────────────────────────────────────────────────────────

_STOCK_RAW: dict = {
    "General": {"Type": "Common Stock", "Name": "Apple Inc."},
    "Highlights": {
        "MarketCapitalization": 3_000_000_000_000,
        "PERatio": 28.5,
        "EarningsShare": 6.43,
        "DividendYield": 0.0055,
    },
    "Valuation": {"PriceBookMRQ": 45.2, "PriceSalesTTM": 8.1},
    "Technicals": {"Beta": 1.23, "AverageVolume": 55_000_000},
    "Financials": {
        "Income_Statement": {"quarterly": {}, "yearly": {}},
        "Balance_Sheet": {"quarterly": {}, "yearly": {}},
        "Cash_Flow": {"quarterly": {}, "yearly": {}},
    },
    "Earnings": {
        "History": {"2024-09-30": {"epsActual": 1.64}},
        "Trend": {"2024-09-30": {"epsEstimate": 1.65}},
        "Annual": {"2024-09-30": {"epsActual": 6.08}},
    },
    "SplitsDividends": {"NumberDividendsByYear": {"2024": {"count": 4}}},
    "SharesStats": {"SharesOutstanding": 15_500_000_000},
    "AnalystRatings": {"Rating": 1.8},
    "outstandingShares": {"annual": {"2024-09-30": {"shares": 15_200_000_000}}},
    "Holders": {
        "Institutions": {"Vanguard": {}},
        "Funds": {},
    },
    "InsiderTransactions": {"0": {}},
}


def test_stock_includes_all_stock_sections() -> None:
    sections = _map_fundamentals_sections(_STOCK_RAW, symbol="AAPL", source="eodhd")

    assert sections["symbol"] == "AAPL"
    assert sections["source"] == "eodhd"
    assert "highlights" in sections
    assert sections["highlights"]["PERatio"] == 28.5
    assert "valuation_ratios" in sections
    assert "income_statement" in sections
    assert "balance_sheet" in sections
    assert "cash_flow" in sections
    assert "technicals_snapshot" in sections
    assert "earnings_history" in sections
    assert "company_profile" in sections


def test_stock_omits_etf_only_path() -> None:
    # ETF_Data must not influence a stock mapping.
    raw = {**_STOCK_RAW, "ETF_Data": {"Yield": "5.00", "Total_Assets": 999}}
    sections = _map_fundamentals_sections(raw, symbol="AAPL", source="eodhd")

    # ETF_Data.Yield must NOT override the stock DividendYield from Highlights
    assert sections["highlights"]["DividendYield"] == 0.0055


# ── ETF fixture ──────────────────────────────────────────────────────────────

_ETF_RAW: dict = {
    "General": {
        "Type": "ETF",
        "Name": "Invesco QQQ Trust",
        "CurrencyCode": "USD",
        "Exchange": "NASDAQ",
    },
    "Technicals": {"Beta": 1.15, "AverageVolume": 40_000_000},
    "ETF_Data": {
        "Yield": "0.4200",
        # WHY TotalAssets (not Total_Assets): EODHD returns camelCase without separator
        # in US ETF responses (confirmed against live QQQ/SPY responses 2026-05-11).
        "TotalAssets": 244_521_498_000,
        "Net_Expense_Ratio": "0.20",
        "NaV": "477.67",
        "Holdings_Count": 101,
        "Top_10_Holdings": {},
    },
}


def test_etf_highlights_contains_dividend_yield_and_market_cap() -> None:
    sections = _map_fundamentals_sections(_ETF_RAW, symbol="QQQ", source="eodhd")

    assert "highlights" in sections
    h = sections["highlights"]
    assert h["DividendYield"] == "0.4200"
    assert h["MarketCapitalization"] == 244_521_498_000


def test_etf_includes_technicals_and_company_profile() -> None:
    sections = _map_fundamentals_sections(_ETF_RAW, symbol="QQQ", source="eodhd")

    assert "technicals_snapshot" in sections
    assert sections["technicals_snapshot"]["Beta"] == 1.15
    assert "company_profile" in sections
    assert sections["company_profile"]["Name"] == "Invesco QQQ Trust"


def test_etf_omits_stock_only_sections() -> None:
    sections = _map_fundamentals_sections(_ETF_RAW, symbol="QQQ", source="eodhd")

    # These sections are stock-only — they MUST NOT appear for an ETF.
    for stock_only_key in (
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "valuation_ratios",
        "earnings_history",
        "earnings_trend",
        "earnings_annual_trend",
        "share_statistics",
        "analyst_consensus",
        "outstanding_shares",
        "institutional_holders",
        "insider_transactions_snapshot",
    ):
        assert stock_only_key not in sections, f"ETF section map must not include '{stock_only_key}'"


def test_etf_zero_yield_excluded_from_highlights() -> None:
    # EODHD returns Yield "0.00" for some ETFs — must not pollute highlights.
    raw = {**_ETF_RAW, "ETF_Data": {**_ETF_RAW["ETF_Data"], "Yield": "0.00"}}
    sections = _map_fundamentals_sections(raw, symbol="SPY", source="eodhd")

    # Highlights should not contain DividendYield when it is "0.00"
    h = sections.get("highlights", {})
    assert "DividendYield" not in h


def test_etf_missing_total_assets_not_in_highlights() -> None:
    raw = {
        "General": {"Type": "ETF", "Name": "Test ETF"},
        "Technicals": {},
        "ETF_Data": {"Yield": "1.20"},  # No TotalAssets / Total_Assets / Portfolio_Net_Assets
    }
    sections = _map_fundamentals_sections(raw, symbol="TEST", source="eodhd")
    assert "MarketCapitalization" not in sections.get("highlights", {})


@pytest.mark.parametrize("type_str", ["FUND", "MUTUALFUND", "Mutual Fund"])
def test_fund_types_treated_as_etf(type_str: str) -> None:
    raw = {
        "General": {"Type": type_str, "Name": "Some Fund"},
        "Technicals": {},
        "ETF_Data": {"Yield": "2.50", "Total_Assets": 1_000_000_000},
    }
    sections = _map_fundamentals_sections(raw, symbol="FUND1", source="eodhd")
    assert "highlights" in sections
    assert sections["highlights"]["DividendYield"] == "2.50"
    assert "income_statement" not in sections
