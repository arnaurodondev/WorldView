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
def test_qwen3_235b_pricing_is_conservative_fallback() -> None:
    """Qwen3-235B fallback pricing is a non-undercounting conservative estimate.

    Regression guard for the LLM-cost audit (2026-07-16): the prior 0.071/0.10
    entry 3x-undercounted the matrix FALLBACK (used when DeepInfra omits
    usage.estimated_cost). Prod ground truth was ~$0.24/Mtok blended on the S6
    extraction mix. NOTE 0.13/0.60 is NOT the DeepInfra published list rate (that
    is ~0.09/0.55 as of 2026-07-16); it is the repo's internal eval-doc value,
    chosen as a middle ground because provider billing runs ~2x list (reasoning
    tokens at effort=medium). Pin it so the fallback can never silently drift
    back to the low numbers.
    """
    entry = MODEL_PRICING["Qwen/Qwen3-235B-A22B-Instruct-2507"]
    assert entry.input_per_million == Decimal("0.13")
    assert entry.output_per_million == Decimal("0.60")
    # 1M in + 1M out => 0.13 + 0.60 = 0.73 USD (exact Decimal, no float drift).
    assert compute_cost("Qwen/Qwen3-235B-A22B-Instruct-2507", 1_000_000, 1_000_000) == Decimal("0.73")


@pytest.mark.unit
def test_model_pricing_is_frozen() -> None:
    """ModelPricing instances are immutable — accidental mutation must raise."""
    entry = MODEL_PRICING["meta-llama/Meta-Llama-3.1-8B-Instruct"]
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        entry.input_per_million = Decimal("999")  # type: ignore[misc]


@pytest.mark.unit
def test_compute_cost_per_call_pricing_ignores_token_counts() -> None:
    """Per-call billed models (Cohere Rerank) return flat per_call_usd.

    PLAN-0107 follow-up: ``rerank-english-v3.0`` is the canonical per-call
    entry. Cost MUST be the flat per_call_usd (Decimal("0.002")) regardless
    of how many "tokens" the caller passes — token columns are ignored.
    """
    # Any non-zero tokens_in trips the "successful call" branch — value is
    # always the flat per_call_usd amount.
    result_1 = compute_cost("rerank-english-v3.0", 1, 0)
    result_2 = compute_cost("rerank-english-v3.0", 9999, 9999)
    assert result_1 == Decimal("0.002")
    assert result_2 == Decimal("0.002")


@pytest.mark.unit
def test_compute_cost_per_call_pricing_zero_tokens_is_failed_call() -> None:
    """Failed per-call requests (tokens_in == 0 AND tokens_out == 0) cost 0.

    Callers signal a failed Cohere request by passing tokens_in=0 — we
    must NOT charge them the flat fee. This mirrors the per-token path
    where 0 tokens = 0 cost.
    """
    assert compute_cost("rerank-english-v3.0", 0, 0) == Decimal("0")


@pytest.mark.unit
def test_compute_cost_token_billed_models_unchanged_by_per_call_field() -> None:
    """Adding ``per_call_usd`` to the dataclass must not affect existing entries.

    The existing per-token Llama-8B entry has ``per_call_usd=None`` so the
    original (tokens/1M)*price math still applies — guardrail against
    accidental regression from the dataclass extension.
    """
    # Same expectation as the historical ``test_compute_cost_known_model``.
    assert compute_cost("meta-llama/Meta-Llama-3.1-8B-Instruct", 1_000_000, 1_000_000) == Decimal("0.110")


@pytest.mark.unit
def test_unknown_constructor_marks_entry_with_negative_sentinel() -> None:
    """``ModelPricing.UNKNOWN`` produces a recognisable sentinel."""
    sentinel = ModelPricing.UNKNOWN("some-model", notes="testing")
    # We rely on the negative sentinel inside compute_cost to detect UNKNOWN.
    assert sentinel.input_per_million < 0
    assert sentinel.output_per_million < 0


# ---------------------------------------------------------------------------
# PLAN-0117 T-A-1-03 — new matrix entries + priceability primitives.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pricing_has_gpt_oss_and_qwen35_9b() -> None:
    """FR-5: the three genuinely-missing models are now priced (non-negative)."""
    for model_id in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "Qwen/Qwen3.5-9B"):
        assert model_id in MODEL_PRICING, f"{model_id} missing from MODEL_PRICING"
        entry = MODEL_PRICING[model_id]
        # Real priced entries, not UNKNOWN sentinels.
        assert entry.input_per_million >= 0
        assert entry.output_per_million >= 0
        assert "2026-07" in entry.notes
        # Priced entries produce a non-zero cost for non-zero tokens.
        assert compute_cost(model_id, 1_000_000, 1_000_000) > Decimal("0")


@pytest.mark.unit
def test_local_free_models_nonempty() -> None:
    """FR-5: ``LOCAL_FREE_MODELS`` is populated with the real configured ids."""
    from ml_clients.pricing import LOCAL_FREE_MODELS

    assert len(LOCAL_FREE_MODELS) > 0
    # Spot-check the two canonical local ids verified from service settings.
    assert "urchade/gliner_large-v2.1" in LOCAL_FREE_MODELS
    assert "qwen3:0.6b" in LOCAL_FREE_MODELS


@pytest.mark.unit
def test_is_priceable_allowlist() -> None:
    """FR-7: matrix / DeepInfra-provider / local ids are priceable; a bare
    unpriced non-local id on a non-provider-cost provider is NOT."""
    from ml_clients.pricing import is_priceable

    # Matrix entry — priceable regardless of provider.
    assert is_priceable("Qwen/Qwen3-32B", provider="openrouter") is True
    # Local model — priceable via the local allow-list.
    assert is_priceable("qwen3:0.6b", provider="ollama") is True
    # Unpriced id BUT on DeepInfra → provider-cost path makes it priceable.
    assert is_priceable("some-brand-new-deepinfra-model", provider="deepinfra") is True
    # Unpriced, non-local, non-provider-cost provider → silent-zero risk.
    assert is_priceable("some-unpriced-model", provider="gemini") is False
    # UNKNOWN sentinel entries are NOT priceable on a non-provider-cost provider.
    assert is_priceable("gpt-4o-mini", provider="gemini") is False


@pytest.mark.unit
def test_provider_cost_to_decimal_scientific_notation() -> None:
    """FR-1: ``4.1e-07`` → exact Decimal, no binary float drift."""
    from ml_clients.pricing import provider_cost_to_decimal

    result = provider_cost_to_decimal(4.1e-07)
    assert result == Decimal("0.00000041")
    # str(float) bridge avoids the artefact Decimal(4.1e-07) would introduce.
    assert result == Decimal("4.1e-07")


@pytest.mark.unit
def test_provider_cost_to_decimal_edge_cases() -> None:
    """FR-1 / NFR-1: None, malformed, and negative inputs → None (never raise)."""
    from ml_clients.pricing import provider_cost_to_decimal

    assert provider_cost_to_decimal(None) is None
    assert provider_cost_to_decimal("not-a-number") is None
    assert provider_cost_to_decimal(-0.5) is None  # negative sentinel → matrix fallback
    # A valid string / int is parsed.
    assert provider_cost_to_decimal("0.0002") == Decimal("0.0002")
    assert provider_cost_to_decimal(0) == Decimal("0")


# ---------------------------------------------------------------------------
# resolve_cost — the single §2.2 cost-source priority (PLAN-0117 W3, STEP 0)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_cost_provider_branch_wins() -> None:
    """Priority 1: a provider-returned cost is persisted verbatim → 'provider'."""
    from ml_clients.pricing import resolve_cost

    cost, source = resolve_cost(
        "openai/gpt-oss-120b",
        provider="deepinfra",
        tokens_in=1000,
        tokens_out=500,
        provider_estimated_cost=4.1e-07,
    )
    assert source == "provider"
    # Verbatim, not the matrix value — no float drift.
    assert cost == Decimal("0.00000041")


@pytest.mark.unit
def test_resolve_cost_local_by_model_id() -> None:
    """Priority 2a: a known LOCAL_FREE_MODELS id → $0 / 'local', no matrix warn."""
    from ml_clients.pricing import resolve_cost

    cost, source = resolve_cost(
        "qwen3:0.6b",
        provider="ollama",
        tokens_in=1234,
        tokens_out=99,
    )
    assert source == "local"
    assert cost == Decimal("0")


@pytest.mark.unit
def test_resolve_cost_local_by_provider(caplog: pytest.LogCaptureFixture) -> None:
    """Priority 2b: an Ollama-served UNLISTED tag → 'local' WITHOUT a matrix warning.

    This is the guardrail the task calls out: routing a local tag through the
    matrix would emit a spurious ``model_pricing_unknown`` warning.
    """
    import logging

    from ml_clients.pricing import resolve_cost

    with caplog.at_level(logging.WARNING):
        cost, source = resolve_cost(
            "some-unlisted-ollama-tag:latest",
            provider="ollama",
            tokens_in=500,
            tokens_out=0,
        )
    assert source == "local"
    assert cost == Decimal("0")
    assert "model_pricing_unknown" not in caplog.text


@pytest.mark.unit
def test_resolve_cost_pricematrix_branch() -> None:
    """Priority 3: no provider cost + paid model → matrix compute → 'pricematrix'."""
    from ml_clients.pricing import compute_cost, resolve_cost

    cost, source = resolve_cost(
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        provider="deepinfra",
        tokens_in=1_000_000,
        tokens_out=1_000_000,
    )
    assert source == "pricematrix"
    assert cost == compute_cost("Qwen/Qwen3-235B-A22B-Instruct-2507", 1_000_000, 1_000_000)
    assert cost > 0


@pytest.mark.unit
def test_resolve_cost_malformed_provider_cost_falls_back_to_matrix() -> None:
    """A malformed/negative provider cost is ignored → matrix (not 'provider')."""
    from ml_clients.pricing import resolve_cost

    cost, source = resolve_cost(
        "Qwen/Qwen3-32B",
        provider="deepinfra",
        tokens_in=1000,
        tokens_out=500,
        provider_estimated_cost="not-a-number",
    )
    assert source == "pricematrix"
    assert cost > 0
