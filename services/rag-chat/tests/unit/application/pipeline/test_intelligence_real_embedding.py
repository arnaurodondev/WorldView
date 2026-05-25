"""Tests for PLAN-0093 Wave E-4 T-E-4-01 — real query embedding for search_entity_relations.

Replaces the 1024-dim zero placeholder with S6.embed_text(query) so the
ANN search returns semantically-relevant relations first instead of an
arbitrary cluster.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_RESOLVED_ID = UUID("018f0000-0000-7000-8000-0000000000ee")


def _make_block(name: str, **kwargs: Any) -> Any:
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=kwargs)


def _make_relation() -> Any:
    r = MagicMock()
    r.subject = "Microsoft"
    r.relation_type = "ACQUIRED"
    r.object = "Activision"
    r.confidence = 0.95
    r.summary = "Microsoft acquired Activision Blizzard in 2023."
    return r


def _make_s7() -> AsyncMock:
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = [
        {"entity_id": str(_RESOLVED_ID), "alias_text": "Microsoft", "similarity": 0.95}
    ]
    s7.search_relations.return_value = [_make_relation()]
    return s7


def _make_s6(embedding: list[float] | None = None) -> AsyncMock:
    s6 = AsyncMock()
    s6.embed_text.return_value = embedding or [0.1] * 1024
    return s6


class TestRealEmbeddingForSearchEntityRelations:
    @pytest.mark.asyncio
    async def test_real_embedding_used_not_zero_vector(self) -> None:
        """search_entity_relations passes a real query embedding to S7."""
        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        s7 = _make_s7()
        s6 = _make_s6(embedding=[0.42] * 1024)
        handler = IntelligenceHandler(s7=s7, s6=s6, entity_context=None, timeout=5.0)
        block = _make_block("search_entity_relations", entity_name="Microsoft", relation_type="acquired")
        result = await handler._handle_search_entity_relations(block, entity_name="Microsoft", relation_type="acquired")

        # S6.embed_text was called with the relation_type + entity_name as text.
        s6.embed_text.assert_awaited_once()
        # The first positional arg should mention both terms.
        called_args = s6.embed_text.call_args
        text = called_args.args[0] if called_args.args else called_args.kwargs.get("text", "")
        assert "Microsoft" in text and "acquired" in text
        # S7.search_relations received the non-zero vector.
        s7_args = s7.search_relations.call_args
        embedding = s7_args.kwargs["embedding"]
        assert embedding == [0.42] * 1024
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_zero_vector_when_s6_absent(self) -> None:
        """search_entity_relations without S6 → zero vector (legacy behaviour)."""
        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        s7 = _make_s7()
        handler = IntelligenceHandler(s7=s7, s6=None, entity_context=None, timeout=5.0)
        block = _make_block("search_entity_relations", entity_name="Microsoft")
        await handler._handle_search_entity_relations(block, entity_name="Microsoft")
        # When S6 is unwired the handler MUST NOT block — it falls back to
        # the zero vector and S7's entity_id filter alone.
        s7_args = s7.search_relations.call_args
        embedding = s7_args.kwargs["embedding"]
        assert embedding == [0.0] * 1024
