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
