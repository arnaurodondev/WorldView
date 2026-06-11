"""Unit tests for metric_extractor (ROPT-10).

Covers:
- Key alias normalization (PE / pe_ratio / TrailingPE → pe_ratio)
- Numeric coercion (strings, negatives, scientific notation)
- Null / empty / non-coercible values skipped without raising
- Duplicate aliases in one payload resolve deterministically (first alias wins)
- Uncatalogued sections return empty list
- MetricRow fields are populated correctly
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from market_data.domain.enums import FundamentalsSection
from market_data.infrastructure.db.metric_extractor import MetricRow, extract_metrics

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = "instr-extractor-001"
_AS_OF_DATE = date(2024, 9, 30)
_INGESTED_AT = datetime(2024, 10, 1, tzinfo=UTC)
_PERIOD_TYPE = "SNAPSHOT"


def _call(section: FundamentalsSection, data: dict) -> list[MetricRow]:
    return extract_metrics(
        instrument_id=_INSTRUMENT_ID,
        section=section,
        period_type=_PERIOD_TYPE,
        as_of_date=_AS_OF_DATE,
        data=data,
        ingested_at=_INGESTED_AT,
    )


def _metrics(rows: list[MetricRow]) -> dict[str, MetricRow]:
    return {r.metric: r for r in rows}


# ── Key alias normalization ────────────────────────────────────────────────────


def test_pe_ratio_from_pe_alias() -> None:
    """JSONB key 'PE' maps to canonical metric 'pe_ratio'."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": 25.0})
    m = _metrics(rows)
    assert "pe_ratio" in m
    assert m["pe_ratio"].value_numeric == Decimal("25.0")


def test_pe_ratio_from_pe_ratio_alias() -> None:
    """JSONB key 'pe_ratio' (snake_case) maps to 'pe_ratio'."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"pe_ratio": 28.5})
    assert "pe_ratio" in _metrics(rows)


def test_pe_ratio_from_trailing_pe_alias() -> None:
    """JSONB key 'TrailingPE' maps to 'pe_ratio'."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"TrailingPE": 30.2})
    assert "pe_ratio" in _metrics(rows)


def test_revenue_from_total_revenue_camel_alias() -> None:
    """JSONB key 'totalRevenue' maps to 'revenue'."""
    rows = _call(FundamentalsSection.INCOME_STATEMENT, {"totalRevenue": 1_000_000.0})
    assert "revenue" in _metrics(rows)


def test_revenue_from_total_revenue_alias() -> None:
    """JSONB key 'total_revenue' (snake_case) also maps to 'revenue'."""
    rows = _call(FundamentalsSection.INCOME_STATEMENT, {"total_revenue": 2_000_000.0})
    assert "revenue" in _metrics(rows)


def test_target_price_from_target_price() -> None:
    """TargetPrice → target_price with correct numeric value."""
    rows = _call(FundamentalsSection.ANALYST_CONSENSUS, {"TargetPrice": 200.0, "Rating": "Buy"})
    m = _metrics(rows)
    assert "target_price" in m
    assert m["target_price"].value_numeric == Decimal("200.0")


def test_analyst_rating_is_text_metric() -> None:
    """analyst_rating stores value_text (text_only=True)."""
    rows = _call(FundamentalsSection.ANALYST_CONSENSUS, {"Rating": "Hold"})
    m = _metrics(rows)
    assert "analyst_rating" in m
    assert m["analyst_rating"].value_text == "Hold"


def test_pb_ratio_from_pb_alias() -> None:
    """PB → pb_ratio."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PB": 3.5})
    assert "pb_ratio" in _metrics(rows)


def test_forward_pe_from_forward_pe_alias() -> None:
    """ForwardPE maps to canonical metric forward_pe."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"ForwardPE": 22.4})
    assert _metrics(rows)["forward_pe"].value_numeric == Decimal("22.4")


def test_enterprise_value_ebitda_mapping() -> None:
    """EnterpriseValueEbitda maps to enterprise_value_ebitda."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"EnterpriseValueEbitda": 16.8})
    assert _metrics(rows)["enterprise_value_ebitda"].value_numeric == Decimal("16.8")


def test_price_sales_ttm_mapping() -> None:
    """PriceSalesTTM maps to price_sales_ttm."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PriceSalesTTM": 6.1})
    assert _metrics(rows)["price_sales_ttm"].value_numeric == Decimal("6.1")


def test_analyst_counts_are_projected() -> None:
    """Buy/Hold/Sell/StrongBuy/StrongSell all map to analyst_* metrics."""
    rows = _call(
        FundamentalsSection.ANALYST_CONSENSUS,
        {
            "Buy": 20,
            "Hold": 5,
            "Sell": 2,
            "StrongBuy": 12,
            "StrongSell": 1,
        },
    )
    metrics = _metrics(rows)
    assert metrics["analyst_buy"].value_numeric == Decimal("20")
    assert metrics["analyst_hold"].value_numeric == Decimal("5")
    assert metrics["analyst_sell"].value_numeric == Decimal("2")
    assert metrics["analyst_strong_buy"].value_numeric == Decimal("12")
    assert metrics["analyst_strong_sell"].value_numeric == Decimal("1")


def test_highlights_expanded_metrics_mapping() -> None:
    """Expanded highlights metrics are extracted with canonical names."""
    rows = _call(
        FundamentalsSection.HIGHLIGHTS,
        {
            "BookValue": 12.34,
            "DilutedEpsTTM": 3.21,
            "DividendYield": 0.017,
            "EPSEstimateCurrentQuarter": 1.23,
            "GrossProfitTTM": 999999,
            "MarketCapitalization": 123456789,
            "OperatingMarginTTM": 0.24,
            "PEGRatio": 1.7,
            "ProfitMargin": 0.31,
            "QuarterlyRevenueGrowthYOY": 0.18,
            "RevenuePerShareTTM": 25.9,
            "WallStreetTargetPrice": 210.0,
        },
    )
    metrics = _metrics(rows)
    assert metrics["book_value"].value_numeric == Decimal("12.34")
    assert metrics["diluted_eps_ttm"].value_numeric == Decimal("3.21")
    assert metrics["dividend_yield"].value_numeric == Decimal("0.017")
    assert metrics["eps_estimate_current_quarter"].value_numeric == Decimal("1.23")
    assert metrics["gross_profit_ttm"].value_numeric == Decimal("999999")
    assert metrics["market_capitalization"].value_numeric == Decimal("123456789")
    assert metrics["operating_margin_ttm"].value_numeric == Decimal("0.24")
    assert metrics["peg_ratio"].value_numeric == Decimal("1.7")
    assert metrics["profit_margin"].value_numeric == Decimal("0.31")
    assert metrics["quarterly_revenue_growth_yoy"].value_numeric == Decimal("0.18")
    assert metrics["revenue_per_share_ttm"].value_numeric == Decimal("25.9")
    assert metrics["wall_street_target_price"].value_numeric == Decimal("210.0")


def test_income_statement_expanded_metrics_mapping() -> None:
    """Expanded income statement fields are projected."""
    rows = _call(
        FundamentalsSection.INCOME_STATEMENT,
        {
            "costOfRevenue": 10,
            "grossProfit": 20,
            "operatingIncome": 30,
            "incomeBeforeTax": 40,
            "incomeTaxExpense": 5,
            "interestExpense": 2,
            "interestIncome": 1,
            "totalOperatingExpenses": 15,
            "netIncomeFromContinuingOps": 11,
        },
    )
    metrics = _metrics(rows)
    assert metrics["cost_of_revenue"].value_numeric == Decimal("10")
    assert metrics["gross_profit"].value_numeric == Decimal("20")
    assert metrics["operating_income"].value_numeric == Decimal("30")
    assert metrics["income_before_tax"].value_numeric == Decimal("40")
    assert metrics["income_tax_expense"].value_numeric == Decimal("5")
    assert metrics["interest_expense"].value_numeric == Decimal("2")
    assert metrics["interest_income"].value_numeric == Decimal("1")
    assert metrics["total_operating_expenses"].value_numeric == Decimal("15")
    assert metrics["net_income_from_continuing_ops"].value_numeric == Decimal("11")


def test_balance_sheet_expanded_metrics_mapping() -> None:
    """Expanded balance-sheet fields are projected."""
    rows = _call(
        FundamentalsSection.BALANCE_SHEET,
        {
            "cash": 1,
            "cashAndEquivalents": 2,
            "cashAndShortTermInvestments": 3,
            "totalLiab": 4,
            "totalCurrentAssets": 5,
            "totalCurrentLiabilities": 6,
            "shortTermDebt": 7,
            "accountsPayable": 8,
            "netReceivables": 9,
            "propertyPlantAndEquipmentNet": 10,
            "commonStockSharesOutstanding": 11,
            "netDebt": 12,
            "netWorkingCapital": 13,
        },
    )
    metrics = _metrics(rows)
    assert metrics["cash"].value_numeric == Decimal("1")
    assert metrics["cash_and_equivalents"].value_numeric == Decimal("2")
    assert metrics["cash_and_short_term_investments"].value_numeric == Decimal("3")
    assert metrics["total_liab"].value_numeric == Decimal("4")
    assert metrics["total_current_assets"].value_numeric == Decimal("5")
    assert metrics["total_current_liabilities"].value_numeric == Decimal("6")
    assert metrics["short_term_debt"].value_numeric == Decimal("7")
    assert metrics["accounts_payable"].value_numeric == Decimal("8")
    assert metrics["net_receivables"].value_numeric == Decimal("9")
    assert metrics["property_plant_and_equipment_net"].value_numeric == Decimal("10")
    assert metrics["common_stock_shares_outstanding"].value_numeric == Decimal("11")
    assert metrics["net_debt"].value_numeric == Decimal("12")
    assert metrics["net_working_capital"].value_numeric == Decimal("13")


def test_cash_flow_operating_cash_flow_alias_total_cash_from_ops() -> None:
    """totalCashFromOperatingActivities populates operating_cash_flow."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"totalCashFromOperatingActivities": 54321})
    metrics = _metrics(rows)
    assert metrics["operating_cash_flow"].value_numeric == Decimal("54321")


def test_cash_flow_expanded_metrics_mapping() -> None:
    """Expanded cash-flow fields are projected."""
    rows = _call(
        FundamentalsSection.CASH_FLOW,
        {
            "capitalExpenditures": -100,
            "freeCashFlow": 200,
            "totalCashFromFinancingActivities": 300,
            "totalCashflowsFromInvestingActivities": 400,
            "dividendsPaid": -50,
            "netBorrowings": 75,
            "depreciation": 88,
        },
    )
    metrics = _metrics(rows)
    assert metrics["capital_expenditures"].value_numeric == Decimal("-100")
    assert metrics["free_cash_flow"].value_numeric == Decimal("200")
    assert metrics["total_cash_from_financing_activities"].value_numeric == Decimal("300")
    assert metrics["total_cashflows_from_investing_activities"].value_numeric == Decimal("400")
    assert metrics["dividends_paid"].value_numeric == Decimal("-50")
    assert metrics["net_borrowings"].value_numeric == Decimal("75")
    assert metrics["depreciation"].value_numeric == Decimal("88")


# ── First alias wins (deterministic duplicate resolution) ─────────────────────


def test_first_alias_wins_when_multiple_present() -> None:
    """When both 'TrailingPE' and 'PE' are in data, only one row is produced."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"TrailingPE": 25.0, "PE": 30.0})
    pe_rows = [r for r in rows if r.metric == "pe_ratio"]
    # Exactly one row per metric, value from the first matching alias (TrailingPE)
    assert len(pe_rows) == 1
    assert pe_rows[0].value_numeric == Decimal("25.0")


def test_first_alias_wins_income_statement() -> None:
    """totalRevenue takes priority over total_revenue (first in alias list)."""
    rows = _call(
        FundamentalsSection.INCOME_STATEMENT,
        {"totalRevenue": 500_000.0, "total_revenue": 999_000.0},
    )
    rev_rows = [r for r in rows if r.metric == "revenue"]
    assert len(rev_rows) == 1
    assert rev_rows[0].value_numeric == Decimal("500000.0")


# ── Numeric coercion ──────────────────────────────────────────────────────────


def test_integer_string_coerced() -> None:
    """String '123' is coerced to Decimal('123')."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": "123"})
    assert _metrics(rows)["pe_ratio"].value_numeric == Decimal("123")


def test_decimal_string_coerced() -> None:
    """String '123.45' is coerced to Decimal."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": "123.45"})
    assert _metrics(rows)["pe_ratio"].value_numeric == Decimal("123.45")


def test_numeric_string_with_commas_and_whitespace_coerced() -> None:
    """String ' 1,234.56 ' is coerced to Decimal('1234.56')."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": " 1,234.56 "})
    assert _metrics(rows)["pe_ratio"].value_numeric == Decimal("1234.56")


def test_parenthesized_negative_string_coerced() -> None:
    """Finance-style '(123.45)' is coerced to Decimal('-123.45')."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": "(123.45)"})
    assert _metrics(rows)["pe_ratio"].value_numeric == Decimal("-123.45")


def test_negative_value_coerced() -> None:
    """Negative numeric value is stored as negative Decimal."""
    rows = _call(FundamentalsSection.INCOME_STATEMENT, {"netIncome": -5_000_000.0})
    assert _metrics(rows)["net_income"].value_numeric == Decimal("-5000000.0")


def test_scientific_notation_string_coerced() -> None:
    """Scientific notation string '1.23e9' is coerced to Decimal."""
    rows = _call(FundamentalsSection.HIGHLIGHTS, {"Revenue": "1.23e9"})
    assert _metrics(rows)["revenue_ttm"].value_numeric == Decimal("1.23e9")


def test_native_int_coerced() -> None:
    """Native Python int is coerced to Decimal."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": 20})
    assert _metrics(rows)["pe_ratio"].value_numeric == Decimal("20")


def test_zero_value_kept() -> None:
    """Zero numeric value is stored (not skipped)."""
    rows = _call(FundamentalsSection.INCOME_STATEMENT, {"netIncome": 0})
    assert "net_income" in _metrics(rows)
    assert _metrics(rows)["net_income"].value_numeric == Decimal("0")


# ── Null / empty / unparseable values skipped ─────────────────────────────────


def test_null_value_skips_numeric_metric() -> None:
    """None value produces no row for a non-text metric."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": None})
    assert not any(r.metric == "pe_ratio" for r in rows)


def test_empty_data_dict_returns_no_rows() -> None:
    """Empty data dict produces no rows."""
    assert _call(FundamentalsSection.HIGHLIGHTS, {}) == []


def test_non_numeric_string_skipped_for_numeric_metric() -> None:
    """Non-coercible string 'N/A' produces no row for a numeric metric."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": "N/A"})
    assert not any(r.metric == "pe_ratio" for r in rows)


def test_empty_string_skipped_for_numeric_metric() -> None:
    """Empty string '' produces no row for a numeric metric."""
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": ""})
    assert not any(r.metric == "pe_ratio" for r in rows)


def test_missing_key_skipped() -> None:
    """If no alias matches, no row for that metric."""
    rows = _call(FundamentalsSection.INCOME_STATEMENT, {"someOtherField": 100.0})
    assert not any(r.metric == "revenue" for r in rows)


def test_partial_keys_extracts_only_present() -> None:
    """Only present keys produce rows; absent ones are silently skipped."""
    # Only PE present, PB and EnterpriseValue absent
    rows = _call(FundamentalsSection.VALUATION_RATIOS, {"PE": 22.0})
    metrics_present = {r.metric for r in rows}
    assert "pe_ratio" in metrics_present
    assert "pb_ratio" not in metrics_present
    assert "enterprise_value" not in metrics_present


# ── Uncatalogued sections ──────────────────────────────────────────────────────


def test_technicals_snapshot_in_catalog_produces_beta_row() -> None:
    """TECHNICALS_SNAPSHOT is now catalogued (PLAN-0050 Wave D) — Beta + avg_volume_30d
    are extracted for the fundamentals screener and snapshot backfill.
    WHY updated (not deleted): R19 — fix implementation, never delete tests.
    Previously TECHNICALS_SNAPSHOT was uncatalogued; after adding beta/avg_volume_30d
    to _METRIC_CATALOG it produces rows.  The test now asserts the new correct behaviour."""
    rows = _call(FundamentalsSection.TECHNICALS_SNAPSHOT, {"Beta": 1.2, "RSI": 55.0})
    # Beta should be extracted; RSI is not in the catalog so it is dropped
    metrics = {r.metric for r in rows}
    assert "beta" in metrics
    assert "rsi" not in metrics  # RSI not in catalog


def test_uncatalogued_section_returns_empty_earnings_trend() -> None:
    """Sections not in the catalog produce no rows regardless of data content.
    Uses EARNINGS_TREND which remains uncatalogued (forward estimates, not screener metrics)."""
    rows = _call(FundamentalsSection.EARNINGS_TREND, {"earningsEstimate": 1.5})
    assert rows == []


def test_earnings_trend_not_in_catalog() -> None:
    """earnings_trend is not in the metric catalog → empty list."""
    rows = _call(FundamentalsSection.EARNINGS_TREND, {"earningsEstimate": 1.5})
    assert rows == []


def test_splits_dividends_not_in_catalog() -> None:
    """splits_dividends is not in the metric catalog → empty list."""
    rows = _call(FundamentalsSection.SPLITS_DIVIDENDS, {"dividendYield": 0.02})
    assert rows == []


# ── Result shape and field population ─────────────────────────────────────────


def test_metric_row_fields_populated() -> None:
    """All MetricRow fields are populated from the inputs to extract_metrics."""
    rows = _call(FundamentalsSection.HIGHLIGHTS, {"Revenue": 1_000_000.0})
    r = next(r for r in rows if r.metric == "revenue_ttm")
    assert r.instrument_id == _INSTRUMENT_ID
    assert r.as_of_date == _AS_OF_DATE
    assert r.period_type == _PERIOD_TYPE
    assert r.ingested_at == _INGESTED_AT
    assert r.section == "highlights"
    assert r.value_text is None


def test_multiple_metrics_from_highlights() -> None:
    """All 5 catalogued highlights keys produce separate rows."""
    rows = _call(
        FundamentalsSection.HIGHLIGHTS,
        {
            "Revenue": 1e9,
            "EBITDA": 2e8,
            "EarningsShare": 3.5,
            "ReturnOnEquityTTM": 0.2,
            "ReturnOnAssetsTTM": 0.1,
        },
    )
    metrics_present = {r.metric for r in rows}
    assert metrics_present == {"revenue_ttm", "ebitda_ttm", "eps_ttm", "roe_ttm", "roa_ttm"}


def test_all_income_statement_metrics_extracted() -> None:
    """All 3 catalogued income_statement metrics are extracted."""
    rows = _call(
        FundamentalsSection.INCOME_STATEMENT,
        {"totalRevenue": 1e9, "netIncome": 1e8, "eps": 2.5},
    )
    assert {r.metric for r in rows} == {"revenue", "net_income", "eps"}


def test_analyst_consensus_both_metrics_extracted() -> None:
    """Both target_price and analyst_rating are extracted from analyst_consensus."""
    rows = _call(
        FundamentalsSection.ANALYST_CONSENSUS,
        {"TargetPrice": 180.0, "Rating": "Buy"},
    )
    m = _metrics(rows)
    assert "target_price" in m
    assert "analyst_rating" in m
    assert m["target_price"].value_numeric == Decimal("180.0")
    assert m["analyst_rating"].value_text == "Buy"


def test_analyst_rating_numeric_text_has_value_text_and_numeric() -> None:
    """A numeric rating string stored in analyst_rating has both value_text and value_numeric."""
    rows = _call(FundamentalsSection.ANALYST_CONSENSUS, {"Rating": "2.5"})
    m = _metrics(rows)
    assert "analyst_rating" in m
    assert m["analyst_rating"].value_text == "2.5"
    assert m["analyst_rating"].value_numeric == Decimal("2.5")


def test_logs_unmapped_keys_with_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unmapped keys are logged with section/instrument/period fields and key sample."""
    from market_data.infrastructure.db import metric_extractor

    captured: dict[str, object] = {}

    class _FakeLogger:
        def debug(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

        def warning(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

    monkeypatch.setattr(metric_extractor, "logger", _FakeLogger())

    _call(
        FundamentalsSection.VALUATION_RATIOS,
        {
            "PE": 10,
            "UnmappedA": 1,
            "UnmappedB": 2,
            "UnmappedC": 3,
        },
    )

    assert captured.get("event") == "metric_extractor.unmapped_keys"
    assert captured.get("section") == "valuation_ratios"
    assert captured.get("instrument_id") == _INSTRUMENT_ID
    assert captured.get("period_type") == _PERIOD_TYPE
    assert captured.get("unmapped_keys_count") == 3
    assert "UnmappedA" in (captured.get("unmapped_keys_sample") or [])


# ── New cash flow fields (6 high-value mappings) ──────────────────────────────


def test_cash_flow_stock_based_compensation() -> None:
    """stockBasedCompensation → stock_based_compensation (non-cash SBC add-back in OCF)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"stockBasedCompensation": 1_500_000})
    m = _metrics(rows)
    assert "stock_based_compensation" in m
    assert m["stock_based_compensation"].value_numeric == Decimal("1500000")


def test_cash_flow_end_period_cash_flow() -> None:
    """endPeriodCashFlow → end_period_cash_flow (end-of-period cash balance)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"endPeriodCashFlow": 8_000_000})
    m = _metrics(rows)
    assert "end_period_cash_flow" in m
    assert m["end_period_cash_flow"].value_numeric == Decimal("8000000")


def test_cash_flow_begin_period_cash_flow() -> None:
    """beginPeriodCashFlow → begin_period_cash_flow (beginning-of-period cash balance)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"beginPeriodCashFlow": 6_000_000})
    m = _metrics(rows)
    assert "begin_period_cash_flow" in m
    assert m["begin_period_cash_flow"].value_numeric == Decimal("6000000")


def test_cash_flow_change_in_working_capital() -> None:
    """changeInWorkingCapital → change_in_working_capital (OCF quality signal)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"changeInWorkingCapital": -250_000})
    m = _metrics(rows)
    assert "change_in_working_capital" in m
    assert m["change_in_working_capital"].value_numeric == Decimal("-250000")


def test_cash_flow_sale_purchase_of_stock() -> None:
    """salePurchaseOfStock → sale_purchase_of_stock (net share buybacks / issuances)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"salePurchaseOfStock": -3_000_000})
    m = _metrics(rows)
    assert "sale_purchase_of_stock" in m
    assert m["sale_purchase_of_stock"].value_numeric == Decimal("-3000000")


def test_cash_flow_net_income_cash_flow() -> None:
    """changeToNetincome (lowercase 'i') → net_income_cash_flow (OCF reconciliation start)."""
    rows = _call(FundamentalsSection.CASH_FLOW, {"changeToNetincome": 12_000_000})
    m = _metrics(rows)
    assert "net_income_cash_flow" in m
    assert m["net_income_cash_flow"].value_numeric == Decimal("12000000")


def test_cash_flow_all_six_new_metrics_extracted_together() -> None:
    """All 6 new cash flow metrics are extracted when present in the same payload."""
    rows = _call(
        FundamentalsSection.CASH_FLOW,
        {
            "stockBasedCompensation": 100,
            "endPeriodCashFlow": 200,
            "beginPeriodCashFlow": 150,
            "changeInWorkingCapital": -30,
            "salePurchaseOfStock": -50,
            "changeToNetincome": 80,
        },
    )
    metrics = _metrics(rows)
    assert metrics["stock_based_compensation"].value_numeric == Decimal("100")
    assert metrics["end_period_cash_flow"].value_numeric == Decimal("200")
    assert metrics["begin_period_cash_flow"].value_numeric == Decimal("150")
    assert metrics["change_in_working_capital"].value_numeric == Decimal("-30")
    assert metrics["sale_purchase_of_stock"].value_numeric == Decimal("-50")
    assert metrics["net_income_cash_flow"].value_numeric == Decimal("80")


# ── Admin key suppression ─────────────────────────────────────────────────────


def test_cash_flow_admin_keys_not_in_unmapped_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """date, filing_date, and currency_symbol are structural metadata — never metrics.

    They must NOT appear in the unmapped_keys warning payload, and must NOT
    inflate the unmapped_keys_count on every Cash_Flow ingest cycle.
    WHY: EODHD always includes these 3 admin fields alongside numeric metrics;
    without exclusion they appear as false positives in every ingest warning.
    """
    from market_data.infrastructure.db import metric_extractor

    captured: dict[str, object] = {}

    class _FakeLogger:
        def debug(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

        def warning(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

    monkeypatch.setattr(metric_extractor, "logger", _FakeLogger())

    _call(
        FundamentalsSection.CASH_FLOW,
        {
            # Known metric — should be matched, not in unmapped
            "depreciation": 500,
            # Admin / metadata fields — must be silently excluded
            "date": "2024-09-30",
            "filing_date": "2024-11-01",
            "currency_symbol": "USD",
            # A genuinely unknown field — should appear in unmapped
            "someUnknownField": 99,
        },
    )

    # The genuinely unknown field must be flagged
    sample = captured.get("unmapped_keys_sample") or []
    assert "someUnknownField" in sample

    # Admin keys must NOT appear in the warning
    assert "date" not in sample
    assert "filing_date" not in sample
    assert "currency_symbol" not in sample

    # Count must reflect only the genuine unknown, not the 3 admin keys
    assert captured.get("unmapped_keys_count") == 1


# ── New balance sheet fields (10 high-value mappings, 2026-06-11) ─────────────


def test_balance_sheet_ten_new_metrics_extracted_together() -> None:
    """All 10 newly catalogued balance-sheet metrics extract from EODHD camelCase keys.

    These keys appeared in the unmapped_keys warning on every ingest cycle
    despite being present in every Balance_Sheet payload (see the catalog WHY
    comment in metric_extractor.py for the screener value of each).
    """
    rows = _call(
        FundamentalsSection.BALANCE_SHEET,
        {
            "goodWill": 1,
            "intangibleAssets": 2,
            "netTangibleAssets": 3,
            "shortTermInvestments": 4,
            "longTermInvestments": 5,
            "treasuryStock": -6,
            "additionalPaidInCapital": 7,
            "commonStock": 8,
            "accumulatedDepreciation": -9,
            "capitalLeaseObligations": 10,
        },
    )
    metrics = _metrics(rows)
    assert metrics["goodwill"].value_numeric == Decimal("1")
    assert metrics["intangible_assets"].value_numeric == Decimal("2")
    assert metrics["net_tangible_assets"].value_numeric == Decimal("3")
    assert metrics["short_term_investments"].value_numeric == Decimal("4")
    assert metrics["long_term_investments"].value_numeric == Decimal("5")
    assert metrics["treasury_stock"].value_numeric == Decimal("-6")
    assert metrics["additional_paid_in_capital"].value_numeric == Decimal("7")
    assert metrics["common_stock"].value_numeric == Decimal("8")
    assert metrics["accumulated_depreciation"].value_numeric == Decimal("-9")
    assert metrics["capital_lease_obligations"].value_numeric == Decimal("10")


# ── Deliberately-ignored balance sheet keys (warning signal restoration) ──────


def _capture_unmapped_log(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch the module logger and return the dict that captures the log payload."""
    from market_data.infrastructure.db import metric_extractor

    captured: dict[str, object] = {}

    class _FakeLogger:
        def debug(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

        def warning(self, event: str, **kwargs: object) -> None:
            captured["event"] = event
            captured.update(kwargs)

    monkeypatch.setattr(metric_extractor, "logger", _FakeLogger())
    return captured


def test_balance_sheet_ignored_keys_produce_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keys on the deliberate-skip list (_IGNORED_KEYS) never reach the unmapped log.

    WHY: these EODHD fields were reviewed and intentionally not promoted to
    metrics (redundant aggregates / residual buckets).  If they kept appearing
    in unmapped_keys, the warning would fire on EVERY ingest cycle and a
    genuinely new EODHD field would drown in the noise.
    """
    captured = _capture_unmapped_log(monkeypatch)

    _call(
        FundamentalsSection.BALANCE_SHEET,
        {
            # Known metric — matched, not unmapped.
            "totalAssets": 100,
            # Deliberately-ignored keys — must be silently excluded.
            "liabilitiesAndStockholdersEquity": 100,
            "retainedEarningsTotalEquity": 50,
            "propertyPlantEquipment": 40,
            "capitalSurpluse": 30,
            "warrants": 0,
            # Admin keys — also excluded.
            "date": "2024-09-30",
        },
    )

    # Everything present was either matched, ignored, or admin — no log at all.
    assert captured == {}


def test_balance_sheet_unknown_key_still_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuinely NEW EODHD field still surfaces in the unmapped log.

    This is the signal the ignore list exists to protect: when EODHD adds a
    field we have never seen, it must appear in unmapped_keys so a human can
    make a mapping decision.
    """
    captured = _capture_unmapped_log(monkeypatch)

    _call(
        FundamentalsSection.BALANCE_SHEET,
        {
            "totalAssets": 100,
            # Ignored key — excluded.
            "otherAssets": 5,
            # Brand-new field EODHD just invented — must be flagged.
            "someBrandNewEodhdField": 42,
        },
    )

    sample = captured.get("unmapped_keys_sample") or []
    assert "someBrandNewEodhdField" in sample
    assert "otherAssets" not in sample
    assert captured.get("unmapped_keys_count") == 1
