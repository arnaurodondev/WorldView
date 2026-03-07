"""Unit tests for contracts.canonical.fundamentals."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from contracts.canonical.fundamentals import CanonicalFundamentals
from contracts.versions import FUNDAMENTAL_SCHEMA_VERSION


class TestCanonicalFundamentals:
    def _make_fundamentals(self) -> CanonicalFundamentals:
        return CanonicalFundamentals(
            symbol="AAPL",
            exchange="NASDAQ",
            period="annual",
            report_date=datetime(2024, 9, 30, tzinfo=UTC),
            source="macrotrends",
        )

    def _make_full_fundamentals(self) -> CanonicalFundamentals:
        return CanonicalFundamentals(
            symbol="AAPL",
            exchange="NASDAQ",
            period="annual",
            report_date=datetime(2024, 9, 30, tzinfo=UTC),
            revenue=391_035_000_000.0,
            net_income=93_736_000_000.0,
            eps=6.11,
            pe_ratio=28.5,
            market_cap=3_400_000_000_000.0,
            debt_to_equity=1.87,
            source="macrotrends",
        )

    def test_schema_version(self) -> None:
        assert self._make_fundamentals().schema_version == FUNDAMENTAL_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert FUNDAMENTAL_SCHEMA_VERSION == 1

    def test_roundtrip_minimal(self) -> None:
        f = self._make_fundamentals()
        restored = CanonicalFundamentals.from_dict(f.to_dict())
        assert restored.symbol == f.symbol
        assert restored.exchange == f.exchange
        assert restored.period == f.period

    def test_roundtrip_full(self) -> None:
        f = self._make_full_fundamentals()
        restored = CanonicalFundamentals.from_dict(f.to_dict())
        assert restored.revenue == f.revenue
        assert restored.net_income == f.net_income
        assert restored.eps == f.eps
        assert restored.pe_ratio == f.pe_ratio
        assert restored.market_cap == f.market_cap
        assert restored.debt_to_equity == f.debt_to_equity

    def test_frozen(self) -> None:
        f = self._make_fundamentals()
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.symbol = "MSFT"  # type: ignore[misc]

    def test_optional_fields_default_none(self) -> None:
        f = self._make_fundamentals()
        assert f.revenue is None
        assert f.net_income is None
        assert f.eps is None
        assert f.pe_ratio is None
        assert f.market_cap is None
        assert f.debt_to_equity is None

    def test_to_dict_keys(self) -> None:
        d = self._make_fundamentals().to_dict()
        expected_keys = {
            "symbol", "exchange", "period", "report_date",
            "revenue", "net_income", "eps", "pe_ratio",
            "market_cap", "debt_to_equity", "source", "schema_version",
        }
        assert set(d.keys()) == expected_keys

    def test_quarterly_period(self) -> None:
        f = CanonicalFundamentals(
            symbol="MSFT",
            exchange="NASDAQ",
            period="quarterly",
            report_date=datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert f.period == "quarterly"
