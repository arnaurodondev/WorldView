"""FR-7a priceability guardrail tests (PLAN-0117 W5, T-A-5-01).

Asserts that EVERY model id the platform can emit has a cost path — a
:data:`MODEL_PRICING` entry, a provider-cost provider (DeepInfra), or a
:data:`LOCAL_FREE_MODELS` entry. A configured model without a pricing path would
be logged at $0 (the RC-1/RC-2/RC-3 silent-zero regression). Includes the
mandatory NEGATIVE test proving the check fails on an injected unpriced model.
"""

from __future__ import annotations

import pytest
from ml_clients.model_registry import (
    PLATFORM_MODEL_REGISTRY,
    registry_model_pairs,
    unpriceable_models,
    warn_unpriceable_models,
)
from ml_clients.pricing import is_priceable


@pytest.mark.unit
def test_all_configured_models_priceable() -> None:
    """CI GATE: every model in the platform registry must be priceable.

    If this fails, a configured model shipped without a pricing path — add it to
    ``pricing.MODEL_PRICING`` or ``LOCAL_FREE_MODELS`` (the failure message lists
    exactly which model + provider is unpriced).
    """
    bad = unpriceable_models(registry_model_pairs())
    assert bad == [], (
        "Unpriceable configured models (would log $0 → silent-zero): "
        f"{bad}. Add each to libs/ml-clients/pricing.MODEL_PRICING or LOCAL_FREE_MODELS."
    )


@pytest.mark.unit
def test_registry_is_non_empty_and_covers_all_services() -> None:
    """The registry must actually enumerate models for every LLM-emitting service."""
    services = {m.service for m in PLATFORM_MODEL_REGISTRY}
    assert {"nlp-pipeline", "knowledge-graph", "rag-chat", "api-gateway", "ml-clients"} <= services
    assert len(PLATFORM_MODEL_REGISTRY) >= 20


@pytest.mark.unit
def test_priceability_check_fails_on_injected_unpriced_model() -> None:
    """NEGATIVE: injecting an unpriced, non-DeepInfra, non-local model → check reports it.

    Proves the guard is a real tripwire (not vacuously green): an OpenRouter model
    absent from the matrix has NO cost path.
    """
    injected = ("acme/totally-unpriced-42b", "openrouter")
    assert is_priceable(*injected[:1], provider=injected[1]) is False
    bad = unpriceable_models([*registry_model_pairs(), injected])
    assert injected in bad


@pytest.mark.unit
def test_local_provider_model_not_in_allowlist_is_unpriceable() -> None:
    """An Ollama tag absent from LOCAL_FREE_MODELS is NOT priceable (allow-list is explicit)."""
    # ``is_priceable`` uses the explicit LOCAL_FREE_MODELS allow-list (not the
    # provider), so a novel local tag must be catalogued or it flags.
    assert is_priceable("some-new-ollama-tag:latest", provider="ollama") is False


@pytest.mark.unit
def test_warn_unpriceable_models_returns_offenders_and_never_raises() -> None:
    """The startup helper returns the offending pairs and never raises."""
    # All-priceable input → empty list, no warning.
    assert warn_unpriceable_models("test-svc", [("Qwen/Qwen3-32B", "deepinfra")]) == []
    # One bad pair → returned (and a WARNING is logged, best-effort).
    bad = warn_unpriceable_models("test-svc", [("acme/unpriced", "openrouter")])
    assert ("acme/unpriced", "openrouter") in bad
