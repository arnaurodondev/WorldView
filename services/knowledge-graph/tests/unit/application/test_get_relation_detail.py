"""Unit tests for GetRelationDetailUseCase (PLAN-0099 edge detail).

Verifies:
- None when the relation does not exist (no further repo calls)
- summary_authority computed at query time (confidence * log1p(evidence_count))
- subject/object resolved via one get_batch call (no N+1)
- evidence fetched with the requested limit
- missing entity rows degrade to None (never raises)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from knowledge_graph.application.use_cases.get_relation_detail import GetRelationDetailUseCase

pytestmark = pytest.mark.unit

_REL_ID = UUID("01900000-0000-7000-8000-00000000aaaa")
_SUBJ_ID = uuid4()
_OBJ_ID = uuid4()
_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _relation_row(confidence: float | None = 0.8, evidence_count: int = 10) -> dict[str, Any]:
    return {
        "relation_id": _REL_ID,
        "subject_entity_id": _SUBJ_ID,
        "object_entity_id": _OBJ_ID,
        "canonical_type": "competes_with",
        "semantic_mode": "RELATION_STATE",
        "decay_class": "DURABLE",
        "confidence": confidence,
        "confidence_stale": False,
        "evidence_count": evidence_count,
        "first_evidence_at": _NOW,
        "latest_evidence_at": _NOW,
    }


def _repos(relation_row: dict[str, Any] | None) -> tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    relation_repo = AsyncMock()
    relation_repo.get_by_id = AsyncMock(return_value=relation_row)
    evidence_repo = AsyncMock()
    evidence_repo.get_detail_for_relation = AsyncMock(return_value=[])
    summary_repo = AsyncMock()
    summary_repo.get_current = AsyncMock(return_value=None)
    entity_repo = AsyncMock()
    entity_repo.get_batch = AsyncMock(return_value=[])
    return relation_repo, evidence_repo, summary_repo, entity_repo


class TestGetRelationDetailUseCase:
    async def test_returns_none_when_relation_missing(self) -> None:
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(None)

        result = await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
        )

        assert result is None
        # Short-circuit: no further queries when the relation is missing.
        evidence_repo.get_detail_for_relation.assert_not_awaited()
        summary_repo.get_current.assert_not_awaited()
        entity_repo.get_batch.assert_not_awaited()

    async def test_summary_authority_computed(self) -> None:
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(
            _relation_row(confidence=0.8, evidence_count=10)
        )

        result = await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
        )

        assert result is not None
        assert result.relation["summary_authority"] == pytest.approx(round(0.8 * math.log1p(10), 6))

    async def test_summary_authority_zero_when_confidence_null(self) -> None:
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(
            _relation_row(confidence=None, evidence_count=10)
        )

        result = await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
        )

        assert result is not None
        assert result.relation["summary_authority"] == 0.0

    async def test_entities_resolved_via_single_batch(self) -> None:
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(_relation_row())
        entity_repo.get_batch = AsyncMock(
            return_value=[
                {"entity_id": _SUBJ_ID, "canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
                {"entity_id": _OBJ_ID, "canonical_name": "Microsoft", "entity_type": "financial_instrument"},
            ]
        )

        result = await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
        )

        assert result is not None
        entity_repo.get_batch.assert_awaited_once_with([_SUBJ_ID, _OBJ_ID])
        assert result.subject_row is not None
        assert result.subject_row["canonical_name"] == "Apple Inc."
        assert result.object_row is not None
        assert result.object_row["canonical_name"] == "Microsoft"

    async def test_missing_entity_rows_degrade_to_none(self) -> None:
        """get_batch silently omits missing IDs — the use case must not raise."""
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(_relation_row())
        entity_repo.get_batch = AsyncMock(return_value=[])  # both entities missing

        result = await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
        )

        assert result is not None
        assert result.subject_row is None
        assert result.object_row is None

    async def test_evidence_limit_forwarded(self) -> None:
        relation_repo, evidence_repo, summary_repo, entity_repo = _repos(_relation_row())

        await GetRelationDetailUseCase().execute(
            relation_repo=relation_repo,
            evidence_repo=evidence_repo,
            summary_repo=summary_repo,
            entity_repo=entity_repo,
            relation_id=_REL_ID,
            evidence_limit=7,
        )

        evidence_repo.get_detail_for_relation.assert_awaited_once_with(_REL_ID, limit=7)
