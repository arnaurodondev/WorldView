"""Unit tests for Block 11: relation type canonicalization."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_repo(
    exact_return: object = None,
    ann_return: object = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.find_exact = AsyncMock(return_value=exact_return)
    repo.find_by_embedding = AsyncMock(return_value=ann_return)
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def _make_embedding_client(vec: list[float] | None = None) -> AsyncMock:
    client = AsyncMock()
    client.embed = AsyncMock(return_value=vec or [0.1, 0.2, 0.3])
    return client


_EXACT_ROW: dict[str, object] = {
    "type_id": uuid4(),
    "canonical_type": "employs",
    "semantic_mode": "RELATION_STATE",
    "decay_class": "STANDARD",
    "base_confidence": 0.70,
    "decay_alpha": 0.000950,
}

_SOFT_ROW: dict[str, object] = {
    "type_id": uuid4(),
    "canonical_type": "board_member_of",
    "semantic_mode": "RELATION_STATE",
    "decay_class": "DURABLE",
    "base_confidence": 0.65,
    "cosine_distance": 0.28,
}


# ---------------------------------------------------------------------------
# Step 1: Exact match
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_match_returns_canonical_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        registry = _make_registry_repo(exact_return=_EXACT_ROW)
        result = asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type == "employs"
        assert result.step == "exact"

    def test_exact_match_does_not_call_embedding(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        registry = _make_registry_repo(exact_return=_EXACT_ROW)
        emb = _make_embedding_client()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=registry,
                outbox_repo=_make_outbox_repo(),
                embedding_client=emb,
            )
        )
        emb.embed.assert_not_called()

    def test_exact_match_does_not_emit_proposal(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=_EXACT_ROW),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_not_called()

    def test_exact_match_returns_correct_decay_alpha(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="employs",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=_EXACT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.decay_alpha == pytest.approx(0.000950)


# ---------------------------------------------------------------------------
# Step 2: ANN soft-map
# ---------------------------------------------------------------------------


class TestSoftMap:
    def test_soft_map_returns_closest_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type == "board_member_of"
        assert result.step == "soft_mapped"

    def test_soft_map_calls_embedding(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        emb = _make_embedding_client()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=_make_outbox_repo(),
                embedding_client=emb,
            )
        )
        emb.embed.assert_called_once_with("serves_on_board_of")

    def test_soft_map_does_not_emit_proposal(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="serves_on_board_of",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=_SOFT_ROW),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_not_called()


# ---------------------------------------------------------------------------
# Step 3: Propose (no match)
# ---------------------------------------------------------------------------


class TestPropose:
    def test_propose_returns_none_canonical_type(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        result = asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.canonical_type is None
        assert result.step == "proposed"

    def test_propose_does_not_raise(self) -> None:
        """Unknown types MUST NOT raise — they emit a proposal and return None."""
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        # Should not raise
        result = asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=uuid4(),
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=_make_outbox_repo(),
                embedding_client=_make_embedding_client(),
            )
        )
        assert result.step == "proposed"

    def test_propose_emits_to_outbox(self) -> None:
        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="RELATION_STATE",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        outbox.append.assert_called_once()
        call_kwargs = outbox.append.call_args.kwargs
        assert call_kwargs["topic"] == "relation.type.proposed.v1"

    def test_propose_payload_contains_proposed_type(self) -> None:
        import json

        from knowledge_graph.application.blocks.canonicalization import (
            canonicalize_relation_type,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            canonicalize_relation_type(
                raw_type="invented_by",
                semantic_mode_hint="TEMPORAL_CLAIM",
                subject_entity_id=uuid4(),
                object_entity_id=uuid4(),
                source_doc_id=None,
                registry_repo=_make_registry_repo(exact_return=None, ann_return=None),
                outbox_repo=outbox,
                embedding_client=_make_embedding_client(),
            )
        )
        raw_payload = outbox.append.call_args.kwargs["payload_avro"]
        payload = json.loads(raw_payload)
        assert payload["proposed_type"] == "invented_by"
        assert payload["semantic_mode"] == "TEMPORAL_CLAIM"
