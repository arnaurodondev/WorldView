"""Tests for S9 intelligence schema group (PLAN-0074 Wave G T-G-01).

Asserts that the four new schema groups expose the required fields so that
schema drift from S7/S8 is caught before it breaks the OpenAPI spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


# ── Schema group 1: intelligence.py ──────────────────────────────────────────


def test_entity_intelligence_public_required_fields() -> None:
    """EntityIntelligencePublic must contain the fields expected by the frontend."""
    from api_gateway.schemas.intelligence import (
        ConfidenceBreakdownPublic,
        EntityIntelligencePublic,
    )

    payload = {
        "entity_id": "01930000-0000-7000-8000-000000000001",
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "confidence_breakdown": {},
    }
    obj = EntityIntelligencePublic(**payload)

    assert str(obj.entity_id) == "01930000-0000-7000-8000-000000000001"
    assert obj.canonical_name == "Apple Inc."
    assert obj.entity_type == "financial_instrument"
    assert isinstance(obj.confidence_breakdown, ConfidenceBreakdownPublic)
    # Optional fields default properly.
    assert obj.health_score is None
    assert obj.current_narrative is None
    assert obj.data_completeness == 0.0


def test_narrative_version_public_required_fields() -> None:
    """NarrativeVersionPublic must expose all history-list fields."""
    from api_gateway.schemas.intelligence import NarrativeVersionPublic

    now = datetime.now(tz=UTC)
    obj = NarrativeVersionPublic(
        version_id=UUID("01930000-0000-7000-8000-000000000002"),
        narrative_text="Apple is a major consumer electronics company.",
        model_id="meta-llama/Meta-Llama-3.1-8B",
        generation_reason="scheduled",
        generated_at=now,
    )

    assert obj.model_id == "meta-llama/Meta-Llama-3.1-8B"
    assert obj.generation_reason == "scheduled"
    assert obj.word_count is None
    assert obj.quality_score is None


def test_confidence_breakdown_public_defaults() -> None:
    """ConfidenceBreakdownPublic should work with an empty dict (all optional)."""
    from api_gateway.schemas.intelligence import ConfidenceBreakdownPublic

    obj = ConfidenceBreakdownPublic()

    assert obj.relation_count == 0
    assert obj.source_distribution == []
    assert obj.confidence_trend == []
    assert obj.mean_support is None


# ── Schema group 2: paths.py ─────────────────────────────────────────────────


def test_entity_paths_response_required_fields() -> None:
    """EntityPathsResponse must expose entity_id, paths, total, freshness_ts."""
    from api_gateway.schemas.paths import EntityPathsResponse

    obj = EntityPathsResponse(
        entity_id=UUID("01930000-0000-7000-8000-000000000003"),
        paths=[],
        total=0,
    )

    assert str(obj.entity_id) == "01930000-0000-7000-8000-000000000003"
    assert obj.paths == []
    assert obj.total == 0
    # Optional field defaults to None.
    assert obj.freshness_ts is None


def test_path_insight_public_required_fields() -> None:
    """PathInsightPublic must expose all insight fields including optional nullables."""
    from datetime import datetime

    from api_gateway.schemas.paths import PathEdgePublic, PathInsightPublic, PathNodePublic

    node = PathNodePublic(
        entity_id=UUID("01930000-0000-7000-8000-000000000010"),
        name="Apple Inc.",
        entity_type="financial_instrument",
    )
    edge = PathEdgePublic(relation_type="SUPPLIES", confidence=0.85)

    obj = PathInsightPublic(
        insight_id=UUID("01930000-0000-7000-8000-000000000011"),
        hop_count=2,
        harmonic_score=0.7,
        diversity_score=0.6,
        surprise_score=0.5,
        composite_score=0.65,
        path_nodes=[node],
        path_edges=[edge],
        explanation_pending=False,
        computed_at=datetime.now(tz=UTC),
    )

    assert obj.hop_count == 2
    assert obj.template_match is None  # optional
    assert obj.llm_explanation is None  # optional


# ── Schema group 3: narratives.py ────────────────────────────────────────────


def test_narrative_list_response_shape() -> None:
    """NarrativeListResponse must wrap versions list and expose next_cursor."""
    from api_gateway.schemas.narratives import NarrativeListResponse

    obj = NarrativeListResponse(
        entity_id="01930000-0000-7000-8000-000000000001",
        versions=[],
        next_cursor=None,
    )

    assert obj.entity_id == "01930000-0000-7000-8000-000000000001"
    assert obj.versions == []
    assert obj.next_cursor is None


def test_narrative_trigger_response_shape() -> None:
    """NarrativeTriggerResponse must expose message and entity_id."""
    from api_gateway.schemas.narratives import NarrativeTriggerResponse

    obj = NarrativeTriggerResponse(
        message="Narrative generation queued",
        entity_id="01930000-0000-7000-8000-000000000001",
    )

    assert obj.message == "Narrative generation queued"
    assert obj.entity_id == "01930000-0000-7000-8000-000000000001"


# ── Schema group 4: entity_chat.py ───────────────────────────────────────────


def test_entity_context_chat_request_valid() -> None:
    """EntityContextChatRequest must accept a valid entity_id + question."""
    from api_gateway.schemas.entity_chat import EntityContextChatRequest

    obj = EntityContextChatRequest(
        entity_id=UUID("01930000-0000-7000-8000-000000000001"),
        question="What is Apple's revenue outlook?",
    )

    assert str(obj.entity_id) == "01930000-0000-7000-8000-000000000001"
    assert obj.question == "What is Apple's revenue outlook?"
    assert obj.conversation_id is None
    assert obj.include_graph_context is True


def test_entity_context_chat_request_rejects_empty_question() -> None:
    """EntityContextChatRequest must reject empty/whitespace questions."""
    from api_gateway.schemas.entity_chat import EntityContextChatRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EntityContextChatRequest(
            entity_id=UUID("01930000-0000-7000-8000-000000000001"),
            question="   ",  # whitespace-only → should fail
        )


def test_entity_context_chat_request_optional_fields() -> None:
    """conversation_id and include_graph_context are optional with sensible defaults."""
    from api_gateway.schemas.entity_chat import EntityContextChatRequest

    obj = EntityContextChatRequest(
        entity_id=UUID("01930000-0000-7000-8000-000000000002"),
        question="What is the risk profile?",
        conversation_id=UUID("01930000-0000-7000-8000-000000000099"),
        include_graph_context=False,
    )

    assert obj.conversation_id == UUID("01930000-0000-7000-8000-000000000099")
    assert obj.include_graph_context is False
