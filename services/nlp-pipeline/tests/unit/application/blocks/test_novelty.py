"""Unit tests for Block 8 — Novelty gate (T-C-3-06)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.novelty import (
    EMBEDDING_SIMILARITY_THRESHOLD,
    MINHASH_SIMILARITY_THRESHOLD,
    _all_entities_near_duplicate,
    _get_minhash_similarity,
    run_novelty_gate,
)
from nlp_pipeline.domain.enums import RoutingTier
from nlp_pipeline.domain.models import RoutingDecision

pytestmark = pytest.mark.unit


def _make_routing_decision(tier: RoutingTier = RoutingTier.DEEP) -> RoutingDecision:
    return RoutingDecision(
        decision_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        routing_tier=tier,
        composite_score=0.75,
        feature_scores={},
    )


@pytest.mark.unit
class TestGetMinhashSimilarity:
    @pytest.mark.asyncio
    async def test_returns_float_from_valkey(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(return_value=b"0.85")
        doc_id = uuid.uuid4()

        result = await _get_minhash_similarity(doc_id, valkey_client=client)

        assert result == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_returns_none_when_key_absent(self) -> None:
        client = MagicMock()
        client.get = AsyncMock(return_value=None)
        doc_id = uuid.uuid4()

        result = await _get_minhash_similarity(doc_id, valkey_client=client)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_valkey_error(self) -> None:
        """Valkey failures must not propagate — best-effort only."""
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("connection refused"))
        doc_id = uuid.uuid4()

        result = await _get_minhash_similarity(doc_id, valkey_client=client)

        assert result is None


@pytest.mark.unit
class TestAllEntitiesNearDuplicate:
    @pytest.mark.asyncio
    async def test_empty_entity_list_returns_false(self) -> None:
        """Empty entity list should never trigger near-duplicate downgrade."""
        result = await _all_entities_near_duplicate(
            [],
            entity_profile_embedding_repo=MagicMock(),
            query_embeddings={},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_all_near_duplicate_returns_true(self) -> None:
        entity_id = uuid.uuid4()
        # distance < (1 - threshold) means close enough
        close_distance = 1.0 - EMBEDDING_SIMILARITY_THRESHOLD - 0.01
        repo = MagicMock()
        repo.ann_search = AsyncMock(return_value=[(uuid.uuid4(), close_distance)])

        result = await _all_entities_near_duplicate(
            [entity_id],
            entity_profile_embedding_repo=repo,
            query_embeddings={entity_id: [0.1] * 1024},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_no_embedding_for_entity_treated_as_novel(self) -> None:
        """If an entity has no embedding, it's treated as novel (not duplicate)."""
        entity_id = uuid.uuid4()
        repo = MagicMock()
        repo.ann_search = AsyncMock(return_value=[])

        result = await _all_entities_near_duplicate(
            [entity_id],
            entity_profile_embedding_repo=repo,
            query_embeddings={},  # no embedding available
        )

        assert result is False


@pytest.mark.unit
class TestRunNoveltyGate:
    @pytest.mark.asyncio
    async def test_stage1_downgrade_deep_to_light(self) -> None:
        """Stage 1: MinHash similarity ≥ threshold on DEEP → downgrade to LIGHT."""
        decision = _make_routing_decision(RoutingTier.DEEP)
        doc_id = decision.doc_id

        valkey = MagicMock()
        # Return high similarity (above threshold)
        valkey.get = AsyncMock(return_value=str(MINHASH_SIMILARITY_THRESHOLD + 0.05).encode())
        repo = MagicMock()

        updated, novelty_score = await run_novelty_gate(
            doc_id,
            decision,
            valkey_client=valkey,
            entity_profile_embedding_repo=repo,
            resolved_entity_ids=[],
            entity_embeddings={},
        )

        assert updated.final_routing_tier == RoutingTier.LIGHT
        assert novelty_score < 1.0

    @pytest.mark.asyncio
    async def test_stage1_no_downgrade_for_medium_tier(self) -> None:
        """Stage 1 only downgrades DEEP → MinHash on MEDIUM is ignored."""
        decision = _make_routing_decision(RoutingTier.MEDIUM)
        doc_id = decision.doc_id

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=b"0.95")  # very high similarity
        repo = MagicMock()

        updated, _ = await run_novelty_gate(
            doc_id,
            decision,
            valkey_client=valkey,
            entity_profile_embedding_repo=repo,
            resolved_entity_ids=[],
            entity_embeddings={},
        )

        # MEDIUM should not be downgraded by novelty gate; final_routing_tier
        # is always set to routing_tier when no downgrade occurs.
        assert updated.final_routing_tier == RoutingTier.MEDIUM

    @pytest.mark.asyncio
    async def test_novel_document_preserves_tier(self) -> None:
        """Novel document (low similarity) preserves the original tier."""
        decision = _make_routing_decision(RoutingTier.DEEP)
        doc_id = decision.doc_id

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=b"0.30")  # below threshold
        repo = MagicMock()
        repo.ann_search = AsyncMock(return_value=[])  # no near-duplicates

        updated, novelty_score = await run_novelty_gate(
            doc_id,
            decision,
            valkey_client=valkey,
            entity_profile_embedding_repo=repo,
            resolved_entity_ids=[],
            entity_embeddings={},
        )

        # No downgrade occurred: final_routing_tier equals the initial routing_tier.
        assert updated.final_routing_tier == RoutingTier.DEEP
        assert novelty_score > 0.5

    @pytest.mark.asyncio
    async def test_valkey_unavailable_treats_as_novel(self) -> None:
        """Valkey failure must not propagate — document treated as novel."""
        decision = _make_routing_decision(RoutingTier.DEEP)
        doc_id = decision.doc_id

        valkey = MagicMock()
        valkey.get = AsyncMock(side_effect=Exception("timeout"))
        repo = MagicMock()
        repo.ann_search = AsyncMock(return_value=[])

        updated, novelty_score = await run_novelty_gate(
            doc_id,
            decision,
            valkey_client=valkey,
            entity_profile_embedding_repo=repo,
            resolved_entity_ids=[],
            entity_embeddings={},
        )

        # Should not downgrade — treated as novel; final_routing_tier mirrors
        # the initial routing_tier (DEEP unchanged).
        assert updated.final_routing_tier == RoutingTier.DEEP
        assert novelty_score == 1.0
