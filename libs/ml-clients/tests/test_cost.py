"""Tests for cost estimation utilities (PLAN-0033 T-A-1-02; PLAN-0117 T-A-1-04)."""

from __future__ import annotations

import pytest
from ml_clients.cost import estimate_cost, estimate_tokens_from_text
from ml_clients.pricing import compute_cost

# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_estimate_cost_deepinfra_qwen3() -> None:
    """1000 in + 500 out with DeepInfra Qwen3-32B."""
    # input:  1000 / 1_000_000 * 0.08  = 0.00008
    # output:  500 / 1_000_000 * 0.28  = 0.00014
    # total  = 0.00022
    result = estimate_cost("deepinfra", "Qwen/Qwen3-32B", 1000, 500)
    assert abs(result - 0.00022) < 1e-9


@pytest.mark.unit
def test_estimate_cost_deepinfra_qwen3_1m_tokens() -> None:
    """1M in + 1M out = 0.08 + 0.28 = 0.36."""
    result = estimate_cost("deepinfra", "Qwen/Qwen3-32B", 1_000_000, 1_000_000)
    assert abs(result - 0.36) < 1e-9


@pytest.mark.unit
def test_estimate_cost_deepinfra_v4_flash() -> None:
    """1M in + 1M out with DeepSeek-V4-Flash = 0.14 + 0.28 = 0.42."""
    result = estimate_cost("deepinfra", "deepseek-ai/DeepSeek-V4-Flash", 1_000_000, 1_000_000)
    assert abs(result - 0.42) < 1e-9


@pytest.mark.unit
def test_estimate_cost_gemini() -> None:
    """Gemini flash-lite pricing: $0.075 input + $0.30 output per 1M."""
    # 100k in + 50k out
    # input:  100_000 / 1_000_000 * 0.075 = 0.0075
    # output:  50_000 / 1_000_000 * 0.30  = 0.015
    # total  = 0.0225
    result = estimate_cost("gemini", "gemini-3.1-flash-lite", 100_000, 50_000)
    assert abs(result - 0.0225) < 1e-9


@pytest.mark.unit
def test_estimate_cost_ollama_any_model() -> None:
    """Ollama is always $0.0 regardless of model."""
    assert estimate_cost("ollama", "qwen2.5:3b", 9999, 9999) == 0.0
    assert estimate_cost("ollama", "bge-large:latest", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost("ollama", "completely-unknown-model", 100, 100) == 0.0


@pytest.mark.unit
def test_estimate_cost_unknown_provider() -> None:
    """Unknown provider returns 0.0 — no exception raised."""
    assert estimate_cost("unknown_provider", "some-model", 100, 100) == 0.0


@pytest.mark.unit
def test_estimate_cost_unknown_model_known_provider() -> None:
    """Known provider but unknown (non-wildcard) model returns 0.0."""
    # deepinfra has exact-match entries only — unknown model → 0.0
    result = estimate_cost("deepinfra", "gpt-4o-mini", 1000, 500)
    assert result == 0.0


@pytest.mark.unit
def test_estimate_cost_openrouter() -> None:
    """OpenRouter deepseek fallback model pricing ($0.69/$2.19 per 1M)."""
    result = estimate_cost("openrouter", "deepseek/deepseek-r1-distill-qwen-32b", 1_000_000, 1_000_000)
    assert abs(result - 2.88) < 1e-9


@pytest.mark.unit
def test_estimate_cost_zero_tokens() -> None:
    """Zero token counts give $0 cost (e.g. on failed calls)."""
    assert estimate_cost("gemini", "gemini-3.1-flash-lite", 0, 0) == 0.0


# ---------------------------------------------------------------------------
# estimate_tokens_from_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_estimate_tokens_from_text_100_words() -> None:
    """100-word text → ceil(100 / 0.75) = 134 tokens."""
    text = " ".join(["word"] * 100)
    result = estimate_tokens_from_text(text)
    import math

    expected = math.ceil(100 / 0.75)  # 134
    assert result == expected


@pytest.mark.unit
def test_estimate_tokens_from_text_empty() -> None:
    """Empty string → minimum of 1."""
    assert estimate_tokens_from_text("") == 1


@pytest.mark.unit
def test_estimate_tokens_from_text_single_word() -> None:
    """Single word → ceil(1 / 0.75) = 2 tokens."""
    result = estimate_tokens_from_text("hello")
    assert result == 2


@pytest.mark.unit
def test_estimate_tokens_from_text_whitespace_only() -> None:
    """String with only whitespace → minimum of 1 (split produces no words)."""
    assert estimate_tokens_from_text("   ") == 1


# ---------------------------------------------------------------------------
# PLAN-0117 T-A-1-04 — cost.py now DELEGATES to pricing.compute_cost.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cost_py_delegates_to_pricing() -> None:
    """``estimate_cost`` returns exactly ``float(compute_cost(model_id, ...))``.

    The ``provider`` argument is ignored (a model_id uniquely determines
    pricing) — passing a nonsense provider must not change the result.
    """
    for model_id, a, b in (
        ("Qwen/Qwen3-32B", 1000, 500),
        ("deepseek-ai/DeepSeek-V4-Flash", 1_000_000, 1_000_000),
        ("gemini-3.1-flash-lite", 100_000, 50_000),
        ("openai/gpt-oss-120b", 2000, 1000),
    ):
        expected = float(compute_cost(model_id, a, b))
        assert estimate_cost("deepinfra", model_id, a, b) == expected
        # provider is ignored — an arbitrary/wrong provider yields the same value
        assert estimate_cost("totally-made-up-provider", model_id, a, b) == expected


@pytest.mark.unit
def test_cost_py_no_independent_pricing_map() -> None:
    """The legacy independent ``PRICING`` map is retired (FR-4a unification)."""
    import ml_clients.cost as cost_mod

    assert not hasattr(cost_mod, "PRICING")
