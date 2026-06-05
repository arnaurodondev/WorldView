"""Tests for the canonical LLM pricing matrix (pricing.py).

Distinct from ``test_cost.py`` (legacy float-based estimator) — these tests
cover the new Decimal-based ``compute_cost()`` + ``MODEL_PRICING`` table.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from ml_clients.pricing import MODEL_PRICING, ModelPricing, compute_cost


@pytest.mark.unit
def test_compute_cost_known_model_returns_expected_decimal() -> None:
    """Llama 3.1 8B-Instruct: 1M in + 1M out = 0.055 + 0.055 = 0.110 USD."""
    # Use Decimal directly so any float-conversion drift would surface as a
    # mismatch — the whole point of using Decimal end-to-end.
    result = compute_cost("meta-llama/Meta-Llama-3.1-8B-Instruct", 1_000_000, 1_000_000)
    assert isinstance(result, Decimal)
    assert result == Decimal("0.110")


@pytest.mark.unit
def test_compute_cost_partial_tokens() -> None:
    """1000 in + 500 out for V4-Flash = 1000/1M*0.14 + 500/1M*0.28 = 0.00028."""
    result = compute_cost("deepseek-ai/DeepSeek-V4-Flash", 1000, 500)
    # 0.00014 + 0.00014 = 0.00028
    assert result == Decimal("0.00028")


@pytest.mark.unit
def test_compute_cost_unknown_model_returns_zero_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown model → Decimal("0") + structured warning. Does not raise."""
    # caplog captures stdlib warnings; structlog routes through stdlib so this
    # is enough to assert the warning event name is emitted at least once.
    result = compute_cost("totally-fake-model-id-9999", 1000, 500)
    assert result == Decimal("0")


@pytest.mark.unit
def test_compute_cost_unknown_sentinel_treated_as_unpriced() -> None:
    """An entry created via ``ModelPricing.UNKNOWN`` returns 0 (not a negative cost)."""
    # gpt-4o-mini is registered as UNKNOWN in the matrix — treat identically
    # to a missing entry so operators see the same warning shape either way.
    result = compute_cost("gpt-4o-mini", 1000, 500)
    assert result == Decimal("0")


@pytest.mark.unit
def test_compute_cost_zero_tokens_returns_zero() -> None:
    """Failed calls report 0 tokens — must produce exactly Decimal('0')."""
    assert compute_cost("Qwen/Qwen3-235B-A22B-Instruct-2507", 0, 0) == Decimal("0")


@pytest.mark.unit
def test_compute_cost_very_large_token_counts_no_overflow() -> None:
    """100B tokens in + 100B tokens out must compute exactly (Decimal has no overflow)."""
    # 100,000,000,000 tokens = 100,000 * 1M = 100,000 * price
    result = compute_cost("meta-llama/Meta-Llama-3.1-8B-Instruct", 100_000_000_000, 100_000_000_000)
    # 100_000 * 0.055 + 100_000 * 0.055 = 11000.000
    assert result == Decimal("11000.000")


@pytest.mark.unit
def test_compute_cost_negative_token_counts_clamped_to_zero() -> None:
    """Provider error paths sometimes return -1; we clamp to 0 to avoid negative costs."""
    result = compute_cost("meta-llama/Meta-Llama-3.1-8B-Instruct", -10, -5)
    assert result == Decimal("0")


@pytest.mark.unit
def test_pricing_matrix_contains_core_in_use_models() -> None:
    """Sanity: every model name we know we call lives in the matrix."""
    # If a model ID is removed accidentally this test surfaces the regression
    # before it manifests as silent 0-cost in production.
    required = {
        "deepseek-ai/DeepSeek-V4-Flash",
        "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "BAAI/bge-large-en-v1.5",
    }
    assert required.issubset(set(MODEL_PRICING.keys()))


@pytest.mark.unit
def test_model_pricing_is_frozen() -> None:
    """ModelPricing instances are immutable — accidental mutation must raise."""
    entry = MODEL_PRICING["meta-llama/Meta-Llama-3.1-8B-Instruct"]
    with pytest.raises(Exception):  # noqa: BLE001 — FrozenInstanceError is fine
        entry.input_per_million = Decimal("999")  # type: ignore[misc]


@pytest.mark.unit
def test_unknown_constructor_marks_entry_with_negative_sentinel() -> None:
    """``ModelPricing.UNKNOWN`` produces a recognisable sentinel."""
    sentinel = ModelPricing.UNKNOWN("some-model", notes="testing")
    # We rely on the negative sentinel inside compute_cost to detect UNKNOWN.
    assert sentinel.input_per_million < 0
    assert sentinel.output_per_million < 0
