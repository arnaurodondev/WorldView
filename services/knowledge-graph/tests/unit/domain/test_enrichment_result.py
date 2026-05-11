"""Unit tests for EnrichmentResult, EnrichmentSource, and compute_data_completeness."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from knowledge_graph.domain.enrichment_result import (
    EnrichmentSource,
    compute_data_completeness,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)


class TestEnrichmentSourceEnum:
    def test_str_values(self) -> None:
        assert EnrichmentSource.MARKET_DATA == "market_data"
        assert EnrichmentSource.EODHD == "eodhd"
        assert EnrichmentSource.LLM == "llm"
        assert EnrichmentSource.NONE == "none"

    def test_is_str_subclass(self) -> None:
        assert isinstance(EnrichmentSource.LLM, str)


class TestComputeDataCompletenessFinancialInstrument:
    def test_all_ten_fields_present_returns_one(self) -> None:
        meta: dict[str, object] = {
            "sector": "Technology",
            "industry": "Software",
            "country": "USA",
            "exchange": "NASDAQ",
            "isin": "US0378331005",
            "ticker": "AAPL",
            "employee_count": 164000,
            "founded_year": 1976,
            "headquarters_country": "United States",
        }
        score = compute_data_completeness("financial_instrument", "A description.", meta)
        assert score == 1.0

    def test_five_of_ten_fields_returns_half(self) -> None:
        meta: dict[str, object] = {
            "sector": "Technology",
            "industry": "Software",
            "country": "USA",
        }
        score = compute_data_completeness("financial_instrument", "A description.", meta)
        assert score == pytest.approx(0.4)  # description + 3 meta = 4/10

    def test_partial_five_fields(self) -> None:
        meta: dict[str, object] = {
            "sector": "Technology",
            "industry": "Software",
            "country": "USA",
            "exchange": "NYSE",
        }
        score = compute_data_completeness("financial_instrument", "Desc.", meta)
        assert score == pytest.approx(0.5)  # 5/10

    def test_zero_fields_returns_zero(self) -> None:
        score = compute_data_completeness("financial_instrument", None, {})
        assert score == 0.0

    def test_empty_string_treated_as_absent(self) -> None:
        meta: dict[str, object] = {
            "sector": "",
            "industry": "Software",
        }
        score = compute_data_completeness("financial_instrument", "", meta)
        assert score == pytest.approx(0.1)  # only industry counts = 1/10

    def test_company_type_uses_same_formula(self) -> None:
        meta: dict[str, object] = {"sector": "Finance"}
        score_fi = compute_data_completeness("financial_instrument", "Desc.", meta)
        score_co = compute_data_completeness("company", "Desc.", meta)
        assert score_fi == score_co


class TestComputeDataCompletenessPerson:
    def test_all_four_fields_returns_one(self) -> None:
        meta: dict[str, object] = {
            "role": "CEO",
            "organization": "Apple Inc.",
            "nationality": "American",
        }
        score = compute_data_completeness("person", "Tim Cook biography.", meta)
        assert score == 1.0

    def test_partial_two_of_four(self) -> None:
        meta: dict[str, object] = {"role": "CFO"}
        score = compute_data_completeness("person", "A description.", meta)
        assert score == pytest.approx(0.5)  # 2/4

    def test_zero_fields(self) -> None:
        score = compute_data_completeness("person", None, {})
        assert score == 0.0


class TestComputeDataCompletenessConceptEventLocation:
    def test_description_only_returns_half(self) -> None:
        score = compute_data_completeness("concept", "Definition text.", {})
        assert score == pytest.approx(0.5)

    def test_both_fields_returns_one(self) -> None:
        score = compute_data_completeness("event", "An event description.", {"category": "macro"})
        assert score == 1.0

    def test_zero_fields(self) -> None:
        score = compute_data_completeness("location", None, {})
        assert score == 0.0

    def test_unknown_type_uses_two_field_formula(self) -> None:
        score = compute_data_completeness("other", "Desc.", {})
        assert score == pytest.approx(0.5)
