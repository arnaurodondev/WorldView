"""Unit tests for scripts/backfill_fundamentals.py — derive_fundamentals_snapshot.

WHY THESE TESTS EXIST (PLAN-0050 T-D-4-06):
  The derive_fundamentals_snapshot function contains non-trivial derivation logic
  (FCF = op_cf - |capex|, FCF margin = FCF / revenue, interest coverage = EBIT /
  |interest_expense|, net_debt_to_ebitda = net_debt / EBITDA).  Unit tests here
  guard against regression in the math and null-safe handling without requiring a
  live database connection.

WHY IMPORT FROM scripts/ (not a service module):
  backfill_fundamentals.py is a standalone script (not a service package module).
  We import it directly via sys.path manipulation so it can be tested without
  installing it as a package — consistent with the pattern used in other
  ingestion one-shot scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# WHY: The script lives in services/market-ingestion/scripts/, not in the
# installed package.  We insert the scripts/ directory so Python can find it.
# WHY parents[2]: test file is at tests/unit/test_backfill_fundamentals.py;
# parents[0] = tests/unit/, parents[1] = tests/, parents[2] = market-ingestion/
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from backfill_fundamentals import _safe_float, derive_fundamentals_snapshot

pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_highlights(**kwargs: object) -> dict:
    """Return a minimal EODHD Highlights JSONB blob (all real-world keys present)."""
    return {
        "EarningsShare": 6.11,  # eps_ttm
        "RevenueTTM": 394_328_000_000,  # revenue for fcf_margin
        "EBITDA": 125_000_000_000,  # for net_debt_to_ebitda
        **kwargs,
    }


def _default_cash_flow(**kwargs: object) -> dict:
    return {
        "operatingCashFlow": 110_543_000_000,
        "capitalExpenditures": -11_455_000_000,  # EODHD stores as negative
        **kwargs,
    }


def _default_income(**kwargs: object) -> dict:
    return {
        "ebit": 119_437_000_000,
        "interestExpense": -3_933_000_000,  # EODHD stores as negative
        **kwargs,
    }


def _default_balance(**kwargs: object) -> dict:
    return {
        "netDebt": 96_000_000_000,
        **kwargs,
    }


def _default_technicals(**kwargs: object) -> dict:
    return {
        "Beta": 1.29,
        "AverageVolume": 56_000_000,
        **kwargs,
    }


# ── _safe_float unit tests ────────────────────────────────────────────────────


class TestSafeFloat:
    """_safe_float — coercion from EODHD JSONB values (strings, nulls, negatives)."""

    def test_none_returns_none(self) -> None:
        assert _safe_float(None) is None

    def test_bool_returns_none(self) -> None:
        # EODHD sometimes returns True/False for missing numeric fields
        assert _safe_float(True) is None
        assert _safe_float(False) is None

    def test_int_coerced_to_float(self) -> None:
        assert _safe_float(42) == 42.0

    def test_float_passthrough(self) -> None:
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_numeric_string(self) -> None:
        assert _safe_float("1.25") == pytest.approx(1.25)

    def test_na_string_returns_none(self) -> None:
        for sentinel in ("N/A", "NA", "None", "null", "NaN", "-", "--", ""):
            assert _safe_float(sentinel) is None, f"Expected None for {sentinel!r}"

    def test_parenthesized_negative(self) -> None:
        """EODHD uses (1234.5) to represent -1234.5 in some JSONB blobs."""
        assert _safe_float("(11455000000)") == pytest.approx(-11_455_000_000.0)

    def test_comma_separated_number(self) -> None:
        assert _safe_float("56,000,000") == pytest.approx(56_000_000.0)

    def test_unknown_type_returns_none(self) -> None:
        assert _safe_float([1, 2, 3]) is None  # type: ignore[arg-type]

    def test_negative_string(self) -> None:
        assert _safe_float("-3933000000") == pytest.approx(-3_933_000_000.0)


# ── derive_fundamentals_snapshot math tests ───────────────────────────────────


class TestDeriveFundamentalsSnapshot:
    """Happy-path and edge-case tests for the 10 snapshot field derivations."""

    def _call(self, **overrides: dict) -> dict:
        """Build a default AAPL-like call, apply overrides per section."""
        return derive_fundamentals_snapshot(
            highlights=overrides.get("highlights", _default_highlights()),  # type: ignore[arg-type]
            cash_flow=overrides.get("cash_flow", _default_cash_flow()),  # type: ignore[arg-type]
            income=overrides.get("income", _default_income()),  # type: ignore[arg-type]
            balance=overrides.get("balance", _default_balance()),  # type: ignore[arg-type]
            technicals=overrides.get("technicals", _default_technicals()),  # type: ignore[arg-type]
        )

    # ── EPS TTM ───────────────────────────────────────────────────────────────

    def test_eps_ttm_from_earnings_share(self) -> None:
        result = self._call()
        assert result["eps_ttm"] == pytest.approx(6.11)

    def test_eps_ttm_fallback_key(self) -> None:
        """Falls back to DilutedEpsTTM when EarningsShare is missing."""
        result = self._call(highlights=_default_highlights(EarningsShare=None, DilutedEpsTTM=5.89))
        assert result["eps_ttm"] == pytest.approx(5.89)

    def test_eps_ttm_null_when_missing(self) -> None:
        result = self._call(highlights=_default_highlights(EarningsShare=None))
        # DilutedEpsTTM also absent from default → None
        assert result["eps_ttm"] is None

    # ── Beta ──────────────────────────────────────────────────────────────────

    def test_beta_extracted(self) -> None:
        result = self._call()
        assert result["beta"] == pytest.approx(1.29)

    def test_beta_null_when_missing(self) -> None:
        result = self._call(technicals={})
        assert result["beta"] is None

    # ── Avg Volume ────────────────────────────────────────────────────────────

    def test_avg_volume_30d_integer(self) -> None:
        result = self._call()
        assert result["avg_volume_30d"] == 56_000_000
        assert isinstance(result["avg_volume_30d"], int)

    def test_avg_volume_30d_null_when_missing(self) -> None:
        result = self._call(technicals={"Beta": 1.29})
        assert result["avg_volume_30d"] is None

    # ── Operating Cash Flow ───────────────────────────────────────────────────

    def test_operating_cf_positive(self) -> None:
        result = self._call()
        assert result["operating_cash_flow"] == pytest.approx(110_543_000_000.0)

    def test_operating_cf_alt_key(self) -> None:
        result = self._call(cash_flow={"totalCashFromOperatingActivities": 90_000_000_000})
        assert result["operating_cash_flow"] == pytest.approx(90_000_000_000.0)

    def test_operating_cf_null_when_missing(self) -> None:
        result = self._call(cash_flow={})
        assert result["operating_cash_flow"] is None

    # ── CapEx ─────────────────────────────────────────────────────────────────

    def test_capex_stored_as_positive(self) -> None:
        """EODHD reports capex as negative; we store the absolute value."""
        result = self._call()
        assert result["capex"] == pytest.approx(11_455_000_000.0)

    def test_capex_already_positive(self) -> None:
        """If EODHD reports capex as positive (some instruments), abs() is still correct."""
        result = self._call(cash_flow={"capitalExpenditures": 5_000_000_000})
        assert result["capex"] == pytest.approx(5_000_000_000.0)

    def test_capex_null_when_missing(self) -> None:
        result = self._call(cash_flow={"operatingCashFlow": 100_000_000})
        assert result["capex"] is None

    # ── Free Cash Flow ────────────────────────────────────────────────────────

    def test_free_cash_flow_derived(self) -> None:
        """FCF = operating_cf - |capex|.  Both values available → derived correctly."""
        result = self._call()
        # 110_543_000_000 - 11_455_000_000 = 99_088_000_000
        assert result["free_cash_flow"] == pytest.approx(99_088_000_000.0)

    def test_free_cash_flow_null_when_capex_missing(self) -> None:
        result = self._call(cash_flow={"operatingCashFlow": 100_000_000_000})
        assert result["free_cash_flow"] is None

    def test_free_cash_flow_null_when_op_cf_missing(self) -> None:
        result = self._call(cash_flow={"capitalExpenditures": -5_000_000_000})
        assert result["free_cash_flow"] is None

    def test_free_cash_flow_can_be_negative(self) -> None:
        """Companies burning cash: FCF < 0 is valid."""
        result = self._call(
            cash_flow={
                "operatingCashFlow": 1_000_000_000,
                "capitalExpenditures": -5_000_000_000,
            }
        )
        # 1B - 5B = -4B
        assert result["free_cash_flow"] == pytest.approx(-4_000_000_000.0)

    # ── FCF Margin ────────────────────────────────────────────────────────────

    def test_fcf_margin_derived(self) -> None:
        """FCF margin = FCF / revenue TTM."""
        result = self._call()
        expected = 99_088_000_000 / 394_328_000_000
        assert result["fcf_margin"] == pytest.approx(expected, rel=1e-4)

    def test_fcf_margin_null_when_revenue_zero(self) -> None:
        result = self._call(highlights=_default_highlights(RevenueTTM=0))
        assert result["fcf_margin"] is None

    def test_fcf_margin_null_when_revenue_missing(self) -> None:
        highlights = {"EarningsShare": 6.11, "EBITDA": 100_000_000_000}
        result = self._call(highlights=highlights)  # no RevenueTTM
        assert result["fcf_margin"] is None

    def test_fcf_margin_null_when_fcf_null(self) -> None:
        result = self._call(cash_flow={"operatingCashFlow": 100_000_000_000})  # no capex
        assert result["fcf_margin"] is None

    # ── Interest Coverage ─────────────────────────────────────────────────────

    def test_interest_coverage_derived(self) -> None:
        """interest_coverage = EBIT / |interest_expense|."""
        result = self._call()
        expected = 119_437_000_000 / abs(-3_933_000_000)
        assert result["interest_coverage"] == pytest.approx(expected, rel=1e-4)

    def test_interest_coverage_uses_abs_interest_expense(self) -> None:
        """Interest expense sign convention: abs() prevents negative coverage ratio."""
        result = self._call(income={"ebit": 10_000_000_000, "interestExpense": -500_000_000})
        assert result["interest_coverage"] == pytest.approx(20.0)

    def test_interest_coverage_null_when_interest_zero(self) -> None:
        result = self._call(income={"ebit": 10_000_000_000, "interestExpense": 0})
        assert result["interest_coverage"] is None

    def test_interest_coverage_null_when_ebit_missing(self) -> None:
        result = self._call(income={"interestExpense": -500_000_000})
        assert result["interest_coverage"] is None

    # ── Net Debt / EBITDA ─────────────────────────────────────────────────────

    def test_net_debt_to_ebitda_from_balance_net_debt(self) -> None:
        """Pre-computed netDebt from balance sheet preferred over derived."""
        result = self._call()
        expected = 96_000_000_000 / 125_000_000_000
        assert result["net_debt_to_ebitda"] == pytest.approx(expected, rel=1e-4)

    def test_net_debt_to_ebitda_derived_from_debt_minus_cash(self) -> None:
        """Falls back to total_debt - cash when netDebt not in balance sheet."""
        result = self._call(
            balance={
                "shortLongTermDebtTotal": 120_000_000_000,
                "cashAndEquivalents": 30_000_000_000,
            }
        )
        expected = (120_000_000_000 - 30_000_000_000) / 125_000_000_000
        assert result["net_debt_to_ebitda"] == pytest.approx(expected, rel=1e-4)

    def test_net_debt_to_ebitda_null_when_ebitda_zero(self) -> None:
        result = self._call(highlights=_default_highlights(EBITDA=0))
        assert result["net_debt_to_ebitda"] is None

    def test_net_debt_to_ebitda_null_when_ebitda_negative(self) -> None:
        """Negative EBITDA makes the ratio misleading → return None."""
        result = self._call(highlights=_default_highlights(EBITDA=-5_000_000_000))
        assert result["net_debt_to_ebitda"] is None

    def test_net_debt_to_ebitda_negative_means_net_cash(self) -> None:
        """Negative net_debt_to_ebitda means net cash (total_debt < cash).  Valid."""
        result = self._call(balance={"netDebt": -20_000_000_000})
        assert result["net_debt_to_ebitda"] is not None
        assert result["net_debt_to_ebitda"] < 0

    # ── Credit Rating ─────────────────────────────────────────────────────────

    def test_credit_rating_always_null(self) -> None:
        """credit_rating is always NULL — EODHD does not expose S&P/Moody's ratings."""
        result = self._call()
        assert result["credit_rating"] is None

    # ── Return shape ──────────────────────────────────────────────────────────

    def test_return_has_all_10_keys(self) -> None:
        result = self._call()
        expected_keys = {
            "eps_ttm",
            "beta",
            "avg_volume_30d",
            "operating_cash_flow",
            "capex",
            "free_cash_flow",
            "fcf_margin",
            "interest_coverage",
            "net_debt_to_ebitda",
            "credit_rating",
        }
        assert set(result.keys()) == expected_keys

    def test_all_null_inputs_produce_all_null_outputs(self) -> None:
        """Empty dicts produce all-null snapshot — no crashes."""
        result = derive_fundamentals_snapshot(
            highlights={},
            cash_flow={},
            income={},
            balance={},
            technicals={},
        )
        for key, val in result.items():
            assert val is None, f"Expected None for {key}, got {val!r}"
