"""Unit tests for ContradictionBatchWorker — T-B-02 (PLAN-0074 Wave B).

Tests cover:
  - Contra columns updated on the relations table after contradiction links inserted.
  - Relation is soft-closed (valid_to set) when recomputed confidence < 0.1.
  - contra_count_by_type aggregates correctly by contradiction_type.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)

_RELATION_ID = UUID("00000000-0000-0000-0000-000000000001")
_CLAIM_ID_A = UUID("00000000-0000-0000-0000-000000000010")
_CLAIM_ID_B = UUID("00000000-0000-0000-0000-000000000011")
_SUBJECT_ID = UUID("00000000-0000-0000-0000-000000000020")


def _make_session_factory() -> MagicMock:
    """Return a mock session factory whose context-managed session commits silently."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session
    return sf


class TestContraColumnsUpdated:
    def test_contra_columns_updated_by_contradiction_worker(self) -> None:
        """When links are inserted, update_contra_columns is called with aggregated stats."""
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "earnings_outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.8,
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_B,
                    "polarity": "negative",
                    "extraction_confidence": 0.7,
                }
            ]
        )
        mock_contra.insert_link = AsyncMock()
        mock_contra.aggregate_contra_stats_for_active_links = AsyncMock(
            return_value=[
                {
                    "relation_id": _RELATION_ID,
                    "strongest_contra_score": 0.7,
                    "contra_count_by_type": {"polarity_conflict": 1},
                    "latest_contra_at": _NOW,
                    "current_confidence": 0.5,
                }
            ]
        )

        mock_rel = AsyncMock()
        mock_rel.update_contra_columns = AsyncMock()
        mock_rel.invalidate_relation = AsyncMock()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository",
                return_value=mock_contra,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=mock_rel,
            ),
        ):
            worker = ContradictionBatchWorker(sf)
            asyncio.run(worker.run())

        # update_contra_columns should have been called once with the aggregated stats.
        mock_rel.update_contra_columns.assert_awaited_once()
        assert mock_rel.update_contra_columns.await_args is not None
        call_kwargs = mock_rel.update_contra_columns.await_args.kwargs
        assert call_kwargs["relation_id"] == _RELATION_ID
        assert call_kwargs["strongest_contra_score"] == 0.7
        assert call_kwargs["contra_count_by_type"] == {"polarity_conflict": 1}
        assert call_kwargs["latest_contra_at"] == _NOW

    def test_relation_invalidated_when_confidence_below_threshold(self) -> None:
        """When current_confidence < 0.1, invalidate_relation is called with valid_to = NOW()."""
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.9,
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[{"claim_id": _CLAIM_ID_B, "polarity": "negative", "extraction_confidence": 0.9}]
        )
        mock_contra.insert_link = AsyncMock()
        # Simulate a relation with very low confidence (below 0.1 threshold).
        mock_contra.aggregate_contra_stats_for_active_links = AsyncMock(
            return_value=[
                {
                    "relation_id": _RELATION_ID,
                    "strongest_contra_score": 0.9,
                    "contra_count_by_type": {"polarity_conflict": 2},
                    "latest_contra_at": _NOW,
                    "current_confidence": 0.05,  # below 0.1 threshold
                }
            ]
        )

        mock_rel = AsyncMock()
        mock_rel.update_contra_columns = AsyncMock()
        mock_rel.invalidate_relation = AsyncMock()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository",
                return_value=mock_contra,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=mock_rel,
            ),
        ):
            worker = ContradictionBatchWorker(sf)
            asyncio.run(worker.run())

        # Both update_contra_columns AND invalidate_relation must be called.
        mock_rel.update_contra_columns.assert_awaited_once()
        mock_rel.invalidate_relation.assert_awaited_once()
        assert mock_rel.invalidate_relation.await_args is not None
        inv_kwargs = mock_rel.invalidate_relation.await_args.kwargs
        assert inv_kwargs["relation_id"] == _RELATION_ID
        assert inv_kwargs["valid_to_confidence"] == pytest.approx(0.05)
        assert inv_kwargs["valid_to_source"] == "contradiction_batch_worker"

    def test_relation_not_invalidated_when_confidence_at_threshold(self) -> None:
        """When confidence == 0.1 (not strictly less), invalidate_relation must NOT be called."""
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.5,
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[{"claim_id": _CLAIM_ID_B, "polarity": "negative", "extraction_confidence": 0.5}]
        )
        mock_contra.insert_link = AsyncMock()
        mock_contra.aggregate_contra_stats_for_active_links = AsyncMock(
            return_value=[
                {
                    "relation_id": _RELATION_ID,
                    "strongest_contra_score": 0.5,
                    "contra_count_by_type": {"polarity_conflict": 1},
                    "latest_contra_at": _NOW,
                    "current_confidence": 0.1,  # exactly at threshold, not below
                }
            ]
        )

        mock_rel = AsyncMock()
        mock_rel.update_contra_columns = AsyncMock()
        mock_rel.invalidate_relation = AsyncMock()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository",
                return_value=mock_contra,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=mock_rel,
            ),
        ):
            worker = ContradictionBatchWorker(sf)
            asyncio.run(worker.run())

        mock_rel.update_contra_columns.assert_awaited_once()
        # Exactly 0.1 is NOT strictly less than 0.1 → no invalidation.
        mock_rel.invalidate_relation.assert_not_awaited()


class TestContraCountByType:
    def test_contra_count_by_type_aggregates_correctly(self) -> None:
        """contra_count_by_type dict is passed verbatim from the repo aggregation result."""
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        expected_count_by_type = {"polarity_conflict": 3, "temporal_conflict": 1}

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.6,
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[{"claim_id": _CLAIM_ID_B, "polarity": "negative", "extraction_confidence": 0.6}]
        )
        mock_contra.insert_link = AsyncMock()
        mock_contra.aggregate_contra_stats_for_active_links = AsyncMock(
            return_value=[
                {
                    "relation_id": _RELATION_ID,
                    "strongest_contra_score": 0.6,
                    "contra_count_by_type": expected_count_by_type,
                    "latest_contra_at": _NOW,
                    "current_confidence": 0.4,
                }
            ]
        )

        mock_rel = AsyncMock()
        mock_rel.update_contra_columns = AsyncMock()
        mock_rel.invalidate_relation = AsyncMock()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository",
                return_value=mock_contra,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=mock_rel,
            ),
        ):
            worker = ContradictionBatchWorker(sf)
            asyncio.run(worker.run())

        assert mock_rel.update_contra_columns.await_args is not None
        call_kwargs = mock_rel.update_contra_columns.await_args.kwargs
        # Verify the dict with multiple types is passed through unchanged.
        assert call_kwargs["contra_count_by_type"] == expected_count_by_type

    def test_no_links_inserted_skips_aggregation(self) -> None:
        """When no opposing claims exist (links_inserted=0), aggregation is skipped."""
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.6,
                }
            ]
        )
        # No opposing claims → no links inserted.
        mock_contra.find_opposing_claims = AsyncMock(return_value=[])
        mock_contra.insert_link = AsyncMock()
        mock_contra.aggregate_contra_stats_for_active_links = AsyncMock(return_value=[])

        mock_rel = AsyncMock()
        mock_rel.update_contra_columns = AsyncMock()
        mock_rel.invalidate_relation = AsyncMock()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository",
                return_value=mock_contra,
            ),
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository",
                return_value=mock_rel,
            ),
        ):
            worker = ContradictionBatchWorker(sf)
            asyncio.run(worker.run())

        # links_inserted == 0 → aggregation query never fired.
        mock_contra.aggregate_contra_stats_for_active_links.assert_not_awaited()
        mock_rel.update_contra_columns.assert_not_awaited()
        mock_rel.invalidate_relation.assert_not_awaited()
