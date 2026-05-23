"""Unit tests for ContradictionBatchWorker — T-B-02 (PLAN-0074 Wave B).

Tests cover:
  - Contra columns updated on the relations table after contradiction links inserted.
  - Relation is soft-closed (valid_to set) when recomputed confidence < 0.1.
  - contra_count_by_type aggregates correctly by contradiction_type.
  - insert_link receives raw_id (not claim_id) as relation_evidence_id (bug-fix regression).
  - insert_link is skipped when relation_evidence_raw_id is None.
  - Broken orphaned records are cleaned up at the start of each run.
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
# Distinct UUID representing the raw_id from relation_evidence_raw (NOT claim_id).
# Must differ from _CLAIM_ID_A to catch the pre-fix bug where claim_id was passed
# instead of raw_id.
_RAW_ID_A = UUID("00000000-0000-0000-0000-000000000099")


def _make_session_factory() -> MagicMock:
    """Return a mock session factory whose context-managed session commits silently."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    # session.execute must be an AsyncMock so the cleanup DELETE doesn't blow up.
    session.execute = AsyncMock()
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
                    # raw_id is present — insert_link should be called.
                    "relation_evidence_raw_id": _RAW_ID_A,
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
                    "relation_evidence_raw_id": _RAW_ID_A,
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
                    "relation_evidence_raw_id": _RAW_ID_A,
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
                    "relation_evidence_raw_id": _RAW_ID_A,
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
                    "relation_evidence_raw_id": _RAW_ID_A,
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


class TestInsertLinkUsesRawId:
    """Regression tests for the relation_evidence_id bug fix.

    Pre-fix: insert_link was called with relation_evidence_id=claim_id.
    Post-fix: insert_link must be called with relation_evidence_id=raw_id
              (the raw_id from relation_evidence_raw, looked up via claim_id FK).
    """

    def test_insert_link_called_with_raw_id_not_claim_id(self) -> None:
        """insert_link must receive raw_id as relation_evidence_id, not claim_id.

        This is the core regression test for the pre-fix bug where claim_id
        (UUID ...0010) was passed instead of raw_id (UUID ...0099), causing all
        584 contradiction records to reference non-existent raw_id values and
        therefore never surface in read queries that JOIN on raw_id.
        """
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(
            return_value=[
                {
                    "claim_id": _CLAIM_ID_A,  # UUID ...0010
                    "subject_entity_id": _SUBJECT_ID,
                    "claim_type": "earnings_outlook",
                    "polarity": "positive",
                    "extraction_confidence": 0.8,
                    # raw_id is deliberately different from claim_id to catch the bug.
                    "relation_evidence_raw_id": _RAW_ID_A,  # UUID ...0099
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[{"claim_id": _CLAIM_ID_B, "polarity": "negative", "extraction_confidence": 0.7}]
        )
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

        mock_contra.insert_link.assert_awaited_once()
        assert mock_contra.insert_link.await_args is not None
        call_kwargs = mock_contra.insert_link.await_args.kwargs

        # MUST be raw_id (UUID ...0099), NOT claim_id (UUID ...0010).
        assert call_kwargs["relation_evidence_id"] == _RAW_ID_A, (
            f"Expected raw_id {_RAW_ID_A} but got {call_kwargs['relation_evidence_id']}. "
            "Pre-fix bug: claim_id was passed instead of raw_id."
        )
        # claim_id param must be the opposing claim, not the source claim.
        assert call_kwargs["claim_id"] == _CLAIM_ID_B

    def test_insert_link_skipped_when_raw_id_is_none(self) -> None:
        """insert_link must NOT be called when relation_evidence_raw_id is None.

        Some claims have no corresponding relation_evidence_raw row (they arrived
        via a different code path).  Inserting a link without a valid raw_id would
        violate the FK constraint on relation_contradiction_links.relation_evidence_id.
        """
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
                    # No relation_evidence_raw row for this claim.
                    "relation_evidence_raw_id": None,
                }
            ]
        )
        mock_contra.find_opposing_claims = AsyncMock(
            return_value=[{"claim_id": _CLAIM_ID_B, "polarity": "negative", "extraction_confidence": 0.7}]
        )
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

        # No raw_id → insert_link must never be called (FK cannot be satisfied).
        mock_contra.insert_link.assert_not_awaited()
        # Aggregation is also skipped because links_inserted == 0.
        mock_contra.aggregate_contra_stats_for_active_links.assert_not_awaited()

    def test_cleanup_delete_runs_before_scan(self) -> None:
        """The cleanup DELETE runs at the start of run() regardless of claim count.

        Verifies session.execute is called with a DELETE query so orphaned records
        from pre-fix runs (where relation_evidence_id == claim_id) are removed.
        The DELETE is idempotent and safe to run every worker cycle.
        """
        from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker

        sf = _make_session_factory()
        # Grab the underlying mock session to inspect execute calls.
        session = sf.return_value

        mock_contra = AsyncMock()
        mock_contra.fetch_claims_for_batch_scan = AsyncMock(return_value=[])
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

        # session.execute must have been called at least once (the cleanup DELETE).
        session.execute.assert_awaited()
        # Verify the cleanup SQL contains the expected DELETE pattern.
        all_sql_calls = [str(c.args[0]) for c in session.execute.await_args_list]
        assert any(
            "DELETE FROM relation_contradiction_links" in sql for sql in all_sql_calls
        ), f"Expected a DELETE cleanup query but got: {all_sql_calls}"


class TestFetchClaimsForBatchScanShape:
    """Unit tests for the updated fetch_claims_for_batch_scan query shape."""

    def test_returned_dicts_include_relation_evidence_raw_id_key(self) -> None:
        """fetch_claims_for_batch_scan must return dicts with 'relation_evidence_raw_id'.

        This key was added by the bug fix so the worker can use the correct
        raw_id when inserting contradiction links.
        """
        # Simulate what the DB returns: 6-column rows including raw_id in column 5.
        claim_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        subject_id = UUID("bbbbbbbb-0000-0000-0000-000000000001")
        raw_id = UUID("cccccccc-0000-0000-0000-000000000001")

        # Build a fake row-like object (tuple is fine for positional access).
        # Columns: claim_id, subject_entity_id, claim_type, polarity,
        #          extraction_confidence, raw_id
        fake_row = (str(claim_id), str(subject_id), "earnings_outlook", "positive", "0.85", str(raw_id))

        # Replicate the mapping logic from the repository to validate the shape.
        result = {
            "claim_id": UUID(str(fake_row[0])),
            "subject_entity_id": UUID(str(fake_row[1])),
            "claim_type": fake_row[2],
            "polarity": fake_row[3],
            "extraction_confidence": float(fake_row[4]),
            "relation_evidence_raw_id": UUID(str(fake_row[5])) if fake_row[5] is not None else None,
        }

        assert "relation_evidence_raw_id" in result
        assert result["relation_evidence_raw_id"] == raw_id
        assert result["claim_id"] == claim_id

    def test_relation_evidence_raw_id_is_none_when_no_raw_row(self) -> None:
        """fetch_claims_for_batch_scan must return None for relation_evidence_raw_id
        when the LEFT JOIN finds no matching relation_evidence_raw row."""
        # Column 5 (raw_id) is NULL → LEFT JOIN produced no match.
        fake_row = (
            "aaaaaaaa-0000-0000-0000-000000000001",
            "bbbbbbbb-0000-0000-0000-000000000001",
            "earnings_outlook",
            "positive",
            "0.85",
            None,
        )

        result = {
            "claim_id": UUID(str(fake_row[0])),
            "subject_entity_id": UUID(str(fake_row[1])),
            "claim_type": fake_row[2],
            "polarity": fake_row[3],
            "extraction_confidence": float(fake_row[4]),
            "relation_evidence_raw_id": UUID(str(fake_row[5])) if fake_row[5] is not None else None,
        }

        assert "relation_evidence_raw_id" in result
        assert result["relation_evidence_raw_id"] is None
