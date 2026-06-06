"""Unit tests for SSEEmitter (T-F-3-02)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rag_chat.application.pipeline.sse_emitter import SSEEmitter

pytestmark = pytest.mark.unit


@pytest.fixture
def emitter() -> SSEEmitter:
    return SSEEmitter()


@pytest.mark.unit
def test_sse_status_event(emitter: SSEEmitter) -> None:
    """emit_status returns correct event type and step."""
    result = emitter.emit_status("entity_resolution")
    assert result["event"] == "status"
    data = json.loads(result["data"])
    assert data["step"] == "entity_resolution"


@pytest.mark.unit
def test_sse_token_event(emitter: SSEEmitter) -> None:
    """emit_token returns correct event type and text."""
    result = emitter.emit_token("Hello, ")
    assert result["event"] == "token"
    data = json.loads(result["data"])
    assert data["text"] == "Hello, "


@pytest.mark.unit
def test_sse_delta_alias_matches_token(emitter: SSEEmitter) -> None:
    """emit_delta is wire-compatible with emit_token (PLAN-0099 W1 / BP-595).

    Pins the alias contract — any future change that diverges the two would
    break frontends that only listen for the ``token`` event kind.
    """
    delta = emitter.emit_delta("chunk one ")
    token = emitter.emit_token("chunk one ")
    assert delta == token
    assert delta["event"] == "token"
    assert json.loads(delta["data"])["text"] == "chunk one "


@pytest.mark.unit
def test_sse_citations_event(emitter: SSEEmitter) -> None:
    """emit_citations returns serialized citation list."""
    from unittest.mock import MagicMock

    citation = MagicMock()
    citation.ref = 1
    citation.item_type = "chunk"
    citation.id = str(uuid4())
    citation.title = "Apple 10-K"
    citation.url = None
    citation.source_name = "SEC"
    citation.published_at = datetime(2024, 1, 1, tzinfo=UTC)
    citation.entity_name = "Apple Inc"
    citation.confidence = 0.90

    result = emitter.emit_citations([citation])
    assert result["event"] == "citations"
    data = json.loads(result["data"])
    assert len(data) == 1
    assert data[0]["ref"] == 1
    assert data[0]["title"] == "Apple 10-K"


@pytest.mark.unit
def test_sse_citations_event_never_emits_text_field(emitter: SSEEmitter) -> None:
    """SSE projection MUST NOT include Citation.text — backend-only field (BP-NEW PLAN-0099 W4).

    The domain Citation gained a `text` attribute that stores the full retrieved
    chunk payload so the citation-judge cron can score grounding against the
    actual text (not just the headline). This field is deliberately omitted from
    the SSE wire shape because:
      (a) it would balloon SSE bytes by ~500 tokens per citation;
      (b) the frontend keeps the "Read ↗" link affordance unchanged.

    This test guards the omission — a future refactor that naively adds
    `"text": c.text` to emit_citations would regress the contract.
    """
    from rag_chat.domain.entities.conversation import Citation as RealCitation

    real_citation = RealCitation(
        ref=1,
        item_type="chunk",
        id=str(uuid4()),
        title="Apple 10-K",
        url=None,
        source_name="SEC",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        entity_name="Apple Inc",
        confidence=0.90,
        text="A very long chunk of text that should NEVER leak to the frontend SSE.",
    )

    result = emitter.emit_citations([real_citation])
    payload = json.loads(result["data"])
    # Single-citation payload should contain the existing 9 keys and ZERO text.
    assert "text" not in payload[0], (
        "SSE citations event leaked Citation.text — this is a backend-only field, "
        "intentionally NOT projected to the frontend wire shape."
    )
    # And the omitted value really was set on the source object (sanity check).
    assert real_citation.text is not None


@pytest.mark.unit
def test_sse_contradictions_event(emitter: SSEEmitter) -> None:
    """emit_contradictions returns serialized contradiction list."""
    from rag_chat.domain.entities.conversation import ContradictionRef

    ref = ContradictionRef(
        claim_type="revenue_growth",
        strength=0.75,
        sides=({"text": "Side A"}, {"text": "Side B"}),
    )
    result = emitter.emit_contradictions([ref])
    assert result["event"] == "contradictions"
    data = json.loads(result["data"])
    assert len(data) == 1
    assert data[0]["claim_type"] == "revenue_growth"


@pytest.mark.unit
def test_sse_metadata_event(emitter: SSEEmitter) -> None:
    """emit_metadata returns correct thread/message IDs and latency."""
    thread_id = uuid4()
    message_id = uuid4()

    result = emitter.emit_metadata(thread_id, message_id, "FACTUAL_LOOKUP", "deepinfra", 1234)
    assert result["event"] == "metadata"
    data = json.loads(result["data"])
    assert data["thread_id"] == str(thread_id)
    assert data["intent"] == "FACTUAL_LOOKUP"
    assert data["latency_ms"] == 1234


@pytest.mark.unit
def test_sse_error_event(emitter: SSEEmitter) -> None:
    """emit_error returns error event with code and message."""
    result = emitter.emit_error("RATE_LIMIT_EXCEEDED", "Too many requests")
    assert result["event"] == "error"
    data = json.loads(result["data"])
    assert data["code"] == "RATE_LIMIT_EXCEEDED"
    assert data["message"] == "Too many requests"


# ── PLAN-0099 W1-T03: emit_done phase_timings_ms payload ────────────────────


@pytest.mark.unit
def test_sse_done_event_without_phase_timings(emitter: SSEEmitter) -> None:
    """emit_done() without phase_timings keeps the legacy {"type":"done"} body.

    Backwards compatibility: existing frontends only key on the ``done``
    event name; the data body must NOT introduce required new keys.
    """
    result = emitter.emit_done()
    assert result["event"] == "done"
    data = json.loads(result["data"])
    assert data == {"type": "done"}
    assert "phase_timings_ms" not in data


@pytest.mark.unit
def test_sse_done_event_with_phase_timings(emitter: SSEEmitter) -> None:
    """emit_done(phase_timings_ms=...) attaches the breakdown to the SSE body.

    The chat-eval harness scrapes ``data.phase_timings_ms`` from artifact
    SSE frames so it can decompose end-to-end latency into per-phase
    buckets without parsing stderr logs.
    """
    timings = {
        "check_cache": 1.2,
        "validate_input": 35.0,
        "load_history": 8.4,
        "llm_tool_planning": 4200.0,
        "tool_execution": 1500.0,
        "llm_synthesis_streaming": 7200.0,
        "grounding_validation": 90.0,
        "persist_and_cache": 12.0,
    }
    result = emitter.emit_done(phase_timings_ms=timings)
    assert result["event"] == "done"
    data = json.loads(result["data"])
    assert data["type"] == "done"
    assert data["phase_timings_ms"] == timings


@pytest.mark.unit
def test_sse_done_event_with_empty_timings_omits_key(emitter: SSEEmitter) -> None:
    """An empty dict is omitted (treated identical to None) for legacy parity."""
    result = emitter.emit_done(phase_timings_ms={})
    data = json.loads(result["data"])
    assert "phase_timings_ms" not in data


# ─── PLAN-0107: emit_agent_iteration ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "stage",
    ["planning_tools", "reasoning_over_results", "synthesizing"],
)
def test_sse_agent_iteration_event_shape(emitter: SSEEmitter, stage: str) -> None:
    """emit_agent_iteration produces the exact JSON contract agreed with the frontend.

    The frontend consumer in apps/worldview-web matches on these EXACT field
    names. Any change here is a wire-breaking change that must be coordinated
    cross-repo. Parametrised across all three legal stage strings so a typo
    in any one of them surfaces immediately.
    """
    result = emitter.emit_agent_iteration(
        iteration=2,
        max_iterations=8,
        stage=stage,
        tools_completed_total=5,
        elapsed_ms=12345,
    )
    assert result["event"] == "agent_iteration"
    data = json.loads(result["data"])
    # Exact field set — guards against accidental extra/missing keys.
    assert set(data.keys()) == {
        "iteration",
        "max_iterations",
        "stage",
        "tools_completed_total",
        "elapsed_ms",
    }
    assert data["iteration"] == 2
    assert data["max_iterations"] == 8
    assert data["stage"] == stage
    assert data["tools_completed_total"] == 5
    assert data["elapsed_ms"] == 12345
