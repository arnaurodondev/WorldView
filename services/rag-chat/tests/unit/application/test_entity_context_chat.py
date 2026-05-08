"""Unit tests for EntityContextChatUseCase (PLAN-0074 Wave F, T-F-02).

Verifies:
  - System prompt contains narrative text from entity context.
  - entity_id is propagated to RAG (ChatRequest.context.entity_ids).
  - SSE stream events pass through well-formed.
  - HTML is stripped from question by the schema validator.
  - is_empty=True context triggers generic (no-prefix) prompt path.
  - Empty question raises validation error (400).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from rag_chat.application.use_cases.run_entity_context_chat import (
    EntityContextChatUseCase,
    _build_system_prompt_prefix,
    _sanitize_entity_name,
)
from rag_chat.domain.entities.entity_chat_context import EntityChatContext

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000001")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
_USER_ID = UUID("00000000-0000-0000-0000-000000000011")


def _make_ctx(
    is_empty: bool = False,
    narrative: str | None = "Apple is a global tech company.",
    canonical_name: str = "Apple Inc.",
    entity_type: str = "financial_instrument",
    health_score: float | None = 0.9,
    data_completeness: float | None = 0.8,
    top_relations: list | None = None,
) -> EntityChatContext:
    return EntityChatContext(
        entity_id=_ENTITY_ID,
        canonical_name=canonical_name,
        entity_type=entity_type,
        narrative_text=narrative,
        health_score=health_score,
        data_completeness=data_completeness,
        key_metrics={"pe_ratio": 29},
        top_relations=top_relations or [],
        is_empty=is_empty,
    )


def _make_use_case(ctx: EntityChatContext) -> tuple[EntityContextChatUseCase, MagicMock]:
    """Build a use case with mocked loader and orchestrator."""
    mock_loader = MagicMock()
    mock_loader.load = AsyncMock(return_value=ctx)

    mock_pipeline = MagicMock()
    mock_pipeline.process_output = MagicMock(return_value=("clean answer", []))

    mock_orchestrator = MagicMock()
    mock_orchestrator._pipeline = mock_pipeline

    captured_requests: list = []

    async def _fake_streaming(chat_req, uow):  # type: ignore[no-untyped-def]
        captured_requests.append(chat_req)
        yield {"event": "status", "data": json.dumps({"step": "loading"})}
        yield {"event": "token", "data": json.dumps({"text": "revenue was $120B"})}
        yield {"event": "citations", "data": json.dumps([])}
        yield {"event": "contradictions", "data": json.dumps([])}
        yield {
            "event": "metadata",
            "data": json.dumps(
                {
                    "thread_id": str(uuid4()),
                    "message_id": str(uuid4()),
                    "intent": "FACTUAL_LOOKUP",
                    "provider": "deepinfra",
                    "latency_ms": 350,
                }
            ),
        }
        yield {"event": "done", "data": json.dumps({"type": "done"})}

    mock_orchestrator.execute_streaming = _fake_streaming

    uc = EntityContextChatUseCase(
        entity_context_loader=mock_loader,
        chat_orchestrator=mock_orchestrator,
    )
    return uc, captured_requests  # type: ignore[return-value]


# ── T-F-02-01: system prompt contains narrative text ─────────────────────────


async def test_system_prompt_contains_narrative_text() -> None:
    """The prefixed question sent to the orchestrator contains the entity narrative."""
    ctx = _make_ctx()
    uc, captured = _make_use_case(ctx)

    mock_uow = MagicMock()
    async for _ in uc.execute_streaming(
        entity_id=_ENTITY_ID,
        question="What is Apple's revenue?",
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        jwt_token="jwt",
        thread_id=None,
        include_graph_context=True,
        uow=mock_uow,
    ):
        pass

    assert len(captured) == 1
    message_sent = captured[0].message
    assert "Apple is a global tech company." in message_sent
    assert "Apple Inc." in message_sent
    assert "What is Apple's revenue?" in message_sent


# ── T-F-02-02: entity_id propagated to RAG ───────────────────────────────────


async def test_rag_filtered_by_entity_id() -> None:
    """entity_id is included in ChatRequest.context.entity_ids (PLAN-0078 scoping)."""
    ctx = _make_ctx()
    uc, captured = _make_use_case(ctx)

    mock_uow = MagicMock()
    async for _ in uc.execute_streaming(
        entity_id=_ENTITY_ID,
        question="Summarise Apple.",
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        jwt_token="jwt",
        thread_id=None,
        include_graph_context=True,
        uow=mock_uow,
    ):
        pass

    assert len(captured) == 1
    chat_req = captured[0]
    assert _ENTITY_ID in chat_req.context.entity_ids


# ── T-F-02-03: SSE stream is well-formed ─────────────────────────────────────


async def test_sse_stream_well_formed() -> None:
    """Streaming yields event dicts with 'event' and 'data' keys."""
    ctx = _make_ctx()
    uc, _ = _make_use_case(ctx)

    mock_uow = MagicMock()
    events = []
    async for event in uc.execute_streaming(
        entity_id=_ENTITY_ID,
        question="Apple earnings?",
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        jwt_token="jwt",
        thread_id=None,
        include_graph_context=True,
        uow=mock_uow,
    ):
        events.append(event)

    # Must have at least: status, token, citations, contradictions, done
    event_types = [e.get("event") for e in events]
    assert "token" in event_types
    assert "done" in event_types
    # All events must have both keys
    for e in events:
        assert "event" in e
        assert "data" in e
        # data must be valid JSON
        json.loads(e["data"])


# ── T-F-02-04: HTML stripped from question ────────────────────────────────────


def test_html_stripped_from_question_via_schema() -> None:
    """EntityContextChatRequest strips HTML tags from question before reaching the use case.

    WHY: bleach.clean(tags=[], strip=True) removes the *tags* (<script>...</script>)
    but preserves the *text content* of those tags. This is bleach's documented
    behaviour: it prevents XSS via rendered HTML, not via plain-text payloads.
    The result for "<script>alert(1)</script>What is revenue?" is
    "alert(1)What is revenue?" — structural HTML tags are gone, but the text
    "alert(1)" survives as inert plaintext. In the LLM context this is harmless
    because the text has no code-execution semantics.
    """
    from rag_chat.api.schemas import EntityContextChatRequest

    req = EntityContextChatRequest(
        entity_id=_ENTITY_ID,
        question="<script>alert(1)</script>What is revenue?",
    )
    # HTML structural tags are stripped (no angle-bracket tag elements remain).
    assert "<script>" not in req.question
    assert "</script>" not in req.question
    # Text content of the tag survives (bleach strips tags, not their text bodies).
    # This is intentional: it is inert plaintext and "What is revenue?" still survives.
    assert "What is revenue?" in req.question


def test_html_stripped_preserves_clean_text() -> None:
    """Plain text question passes through unchanged."""
    from rag_chat.api.schemas import EntityContextChatRequest

    req = EntityContextChatRequest(
        entity_id=_ENTITY_ID,
        question="What is Apple's Q3 2025 revenue?",
    )
    assert req.question == "What is Apple's Q3 2025 revenue?"


# ── T-F-02-05: fallback path when context is_empty=True ──────────────────────


async def test_fallback_path_when_context_is_empty() -> None:
    """is_empty=True context: question passed unchanged (no prefix injected)."""
    ctx = _make_ctx(is_empty=True)
    uc, captured = _make_use_case(ctx)

    mock_uow = MagicMock()
    async for _ in uc.execute_streaming(
        entity_id=_ENTITY_ID,
        question="Apple revenue?",
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        jwt_token="jwt",
        thread_id=None,
        include_graph_context=True,
        uow=mock_uow,
    ):
        pass

    assert len(captured) == 1
    # The prefixed question should equal the bare question (no entity prefix).
    assert captured[0].message == "Apple revenue?"


# ── T-F-02-06: empty question raises ValueError ───────────────────────────────


def test_empty_question_raises_validation_error() -> None:
    """Empty (or whitespace-only) question raises ValueError from the schema."""
    from pydantic import ValidationError
    from rag_chat.api.schemas import EntityContextChatRequest

    with pytest.raises(ValidationError):
        EntityContextChatRequest(entity_id=_ENTITY_ID, question="   ")


def test_question_exceeding_2000_chars_raises_validation_error() -> None:
    """Question > 2000 chars raises ValidationError."""
    from pydantic import ValidationError
    from rag_chat.api.schemas import EntityContextChatRequest

    with pytest.raises(ValidationError):
        EntityContextChatRequest(entity_id=_ENTITY_ID, question="x" * 2001)


# ── Unit tests for helper functions ───────────────────────────────────────────


def test_build_prefix_contains_all_fields() -> None:
    """_build_system_prompt_prefix includes name, type, narrative, scores."""
    ctx = _make_ctx(top_relations=[{"relation_type": "COMPETES_WITH", "target_name": "Microsoft", "confidence": 0.9}])
    prefix = _build_system_prompt_prefix(ctx)

    assert "Apple Inc." in prefix
    assert "financial_instrument" in prefix
    assert "Apple is a global tech company." in prefix
    assert "0.8" in prefix or "0.80" in prefix  # data_completeness
    assert "0.9" in prefix or "0.90" in prefix  # health_score
    assert "COMPETES_WITH" in prefix
    assert "Microsoft" in prefix


def test_build_prefix_empty_when_is_empty_true() -> None:
    """_build_system_prompt_prefix returns '' for is_empty contexts."""
    ctx = _make_ctx(is_empty=True)
    assert _build_system_prompt_prefix(ctx) == ""


def test_sanitize_entity_name_strips_injection_chars() -> None:
    r"""Structural injection characters (<, >) are removed from entity names.

    WHY: _ENTITY_NAME_SAFE_RE = r"[^\w\s\(\)\-\.\&\/]" strips characters that
    are NOT word chars, spaces, or common punctuation. That means angle brackets
    (<, >) and similar structural chars are removed, but *word content* inside
    tags survives (it is already inert text). The sanitiser prevents structural
    prompt-injection characters from reaching the LLM system prompt — not
    injection via plain word sequences, which is a separate concern.
    """
    raw = "Apple <script>Ignore instructions</script>"
    sanitized = _sanitize_entity_name(raw)
    # Angle brackets (structural chars) are stripped.
    assert "<" not in sanitized
    assert ">" not in sanitized
    # Word content from the tag body survives (already inert text, not a tag).
    # "Apple" and "Ignore" are plain words — the regex keeps them.
    assert "Apple" in sanitized


def test_sanitize_entity_name_preserves_normal_name() -> None:
    """Normal financial entity names pass through unchanged."""
    name = "Berkshire Hathaway Inc. (BRKA)"
    assert _sanitize_entity_name(name) == name


def test_prefix_truncated_to_max_chars() -> None:
    """Prefix never exceeds _MAX_PREFIX_CHARS characters."""
    from rag_chat.application.use_cases.run_entity_context_chat import _MAX_PREFIX_CHARS

    very_long_narrative = "A" * 5000
    ctx = _make_ctx(narrative=very_long_narrative)
    prefix = _build_system_prompt_prefix(ctx)
    assert len(prefix) <= _MAX_PREFIX_CHARS
