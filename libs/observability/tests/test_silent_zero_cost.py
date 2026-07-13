"""FR-7b silent-zero cost tripwire tests (PLAN-0117 W5, T-A-5-02).

Covers the pure predicate :func:`is_silent_zero_cost` and the counter emitter
:func:`record_silent_zero_cost`, including the REQUIRED exemptions:
``cost_source in {'local', 'aggregate', 'provider'}`` must NOT trip (all three
are legitimately $0 — ``provider`` is the provider's own authoritative figure),
while a ``pricematrix`` or ``None`` row with tokens>0 and $0 MUST trip (that is
the RC-1/2/3 "we failed to price a paid call" regression this guard targets).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from observability.metrics import (
    LLM_USAGE_SILENT_ZERO_COST,
    is_silent_zero_cost,
    record_silent_zero_cost,
)


def _counter_value(service: str, model_id: str) -> float:
    """Read the current value of the global silent-zero counter for a label set."""
    return LLM_USAGE_SILENT_ZERO_COST.labels(service=service, model_id=model_id)._value.get()


# ── predicate ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_predicate_trips_on_paid_zero_with_tokens() -> None:
    """tokens>0 & $0 & WE-failed-to-price source (pricematrix / None) → silent-zero."""
    assert is_silent_zero_cost(tokens_in=100, tokens_out=50, estimated_cost_usd=0, cost_source="pricematrix")
    # None cost_source (legacy/un-migrated caller) is NOT exempt.
    assert is_silent_zero_cost(tokens_in=10, tokens_out=0, estimated_cost_usd=0.0, cost_source=None)


@pytest.mark.unit
def test_predicate_exempts_local_aggregate_and_provider() -> None:
    """local (Ollama/GLiNER), aggregate (S8 wrapper), and provider (authoritative
    provider-reported $0, e.g. free-tier) $0 rows are ALL legitimate — M-1 fix."""
    assert not is_silent_zero_cost(tokens_in=100, tokens_out=50, estimated_cost_usd=0, cost_source="local")
    assert not is_silent_zero_cost(tokens_in=100, tokens_out=50, estimated_cost_usd=0, cost_source="aggregate")
    # provider-reported $0 is authoritative (DeepInfra self-reports); do NOT cry wolf.
    assert not is_silent_zero_cost(tokens_in=1, tokens_out=0, estimated_cost_usd=Decimal("0"), cost_source="provider")


@pytest.mark.unit
def test_predicate_ignores_zero_tokens_and_nonzero_cost() -> None:
    """No tokens → not a silent zero; non-zero cost → not a silent zero."""
    assert not is_silent_zero_cost(tokens_in=0, tokens_out=0, estimated_cost_usd=0, cost_source="pricematrix")
    assert not is_silent_zero_cost(
        tokens_in=100, tokens_out=50, estimated_cost_usd=Decimal("0.01"), cost_source="provider"
    )


# ── emitter (increments the global counter) ──────────────────────────────────


@pytest.mark.unit
def test_emitter_increments_on_paid_silent_zero() -> None:
    """A paid silent-zero row bumps the counter by exactly 1."""
    before = _counter_value("nlp-pipeline", "Qwen/Qwen3-235B-A22B-Instruct-2507")
    record_silent_zero_cost(
        "nlp-pipeline",
        model_id="Qwen/Qwen3-235B-A22B-Instruct-2507",
        tokens_in=1000,
        tokens_out=200,
        estimated_cost_usd=0.0,
        cost_source="pricematrix",
    )
    after = _counter_value("nlp-pipeline", "Qwen/Qwen3-235B-A22B-Instruct-2507")
    assert after == before + 1


@pytest.mark.unit
def test_emitter_does_not_increment_for_local() -> None:
    """A local $0 row leaves the counter unchanged (exemption)."""
    before = _counter_value("knowledge-graph", "bge-large:latest")
    record_silent_zero_cost(
        "knowledge-graph",
        model_id="bge-large:latest",
        tokens_in=500,
        tokens_out=0,
        estimated_cost_usd=0,
        cost_source="local",
    )
    assert _counter_value("knowledge-graph", "bge-large:latest") == before


@pytest.mark.unit
def test_emitter_does_not_increment_for_aggregate() -> None:
    """An aggregate wrapper $0 row (S8 chat_with_tools) leaves the counter unchanged."""
    before = _counter_value("rag-chat", "deepseek-ai/DeepSeek-V4-Flash-Thinking")
    record_silent_zero_cost(
        "rag-chat",
        model_id="deepseek-ai/DeepSeek-V4-Flash-Thinking",
        tokens_in=42000,
        tokens_out=8000,
        estimated_cost_usd=0.0,
        cost_source="aggregate",
    )
    assert _counter_value("rag-chat", "deepseek-ai/DeepSeek-V4-Flash-Thinking") == before


@pytest.mark.unit
def test_emitter_never_raises_on_bad_input() -> None:
    """Best-effort: a non-numeric cost must not raise (NFR-1)."""
    # Should simply be a no-op (non-numeric cost is not provably zero).
    record_silent_zero_cost(
        "rag-chat",
        model_id="x",
        tokens_in=10,
        tokens_out=10,
        estimated_cost_usd="not-a-number",
        cost_source="provider",
    )
