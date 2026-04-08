"""Unit tests for RelationSummarySearchUseCase (Wave C-3)."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
_EMBEDDING = [0.1] * 1024


def _make_repo(results: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.search_by_embedding = AsyncMock(return_value=results or [])
    return repo


def _make_result(
    confidence: float = 0.80,
    evidence_count: int = 5,
    entity_id: object = None,
) -> object:
    from knowledge_graph.application.ports.relation_summary_repository import (
        RelationSummarySearchResult,
    )

    eid = entity_id or uuid4()
    return RelationSummarySearchResult(
        relation_id=uuid4(),
        subject_entity_id=eid,
        object_entity_id=uuid4(),
        subject_canonical_name="Apple Inc",
        object_canonical_name="Tim Cook",
        canonical_type="EMPLOYS",
        summary="Apple employs Tim Cook as CEO.",
        confidence=confidence,
        evidence_count=evidence_count,
        latest_evidence_at=_NOW,
        semantic_mode="RELATION_STATE",
        summary_authority=confidence * math.log1p(evidence_count),
    )


class TestRelationSummarySearchUseCase:
    def test_relation_search_returns_summary_authority(self) -> None:
        """summary_authority is computed correctly: confidence * log1p(evidence_count)."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        confidence = 0.80
        evidence_count = 5
        expected_authority = confidence * math.log1p(evidence_count)
        item = _make_result(confidence=confidence, evidence_count=evidence_count)
        repo = _make_repo(results=[item])

        result = asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
            )
        )

        assert len(result) == 1
        assert abs(result[0].summary_authority - expected_authority) < 1e-9

    def test_relation_search_entity_filter(self) -> None:
        """entity_ids filter forwarded to repository."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        entity_id = uuid4()
        repo = _make_repo()

        asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
                entity_ids=[entity_id],
            )
        )

        call_kwargs = repo.search_by_embedding.call_args.kwargs
        assert call_kwargs["entity_ids"] == [entity_id]

    def test_relation_search_min_confidence(self) -> None:
        """min_confidence forwarded to repository."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        repo = _make_repo()

        asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
                min_confidence=0.70,
            )
        )

        call_kwargs = repo.search_by_embedding.call_args.kwargs
        assert call_kwargs["min_confidence"] == 0.70

    def test_relation_search_relation_types_filter(self) -> None:
        """relation_types filter forwarded to repository."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        repo = _make_repo()

        asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
                relation_types=["EMPLOYS"],
            )
        )

        call_kwargs = repo.search_by_embedding.call_args.kwargs
        assert call_kwargs["relation_types"] == ["EMPLOYS"]

    def test_relation_search_semantic_mode_filter(self) -> None:
        """semantic_mode filter forwarded to repository."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        repo = _make_repo()

        asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
                semantic_mode="RELATION_STATE",
            )
        )

        call_kwargs = repo.search_by_embedding.call_args.kwargs
        assert call_kwargs["semantic_mode"] == "RELATION_STATE"

    def test_relation_search_top_k_forwarded(self) -> None:
        """top_k forwarded to repository."""
        from knowledge_graph.application.use_cases.relation_summary_search import (
            RelationSummarySearchUseCase,
        )

        repo = _make_repo()

        asyncio.run(
            RelationSummarySearchUseCase().execute(
                repo=repo,
                query_embedding=_EMBEDDING,
                top_k=5,
            )
        )

        call_kwargs = repo.search_by_embedding.call_args.kwargs
        assert call_kwargs["top_k"] == 5
