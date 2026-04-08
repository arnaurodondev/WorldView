"""Unit tests for Worker 13A — ConfidenceWorker (T-D-3-01)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


def _make_session_factory(
    *,
    unprocessed_rows: list | None = None,
    all_raw: list | None = None,
    relation_row: dict | None = None,
    contra_rows: list | None = None,
) -> MagicMock:
    """Build a mock session factory for ConfidenceWorker tests."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()

    sf = MagicMock()
    sf.return_value = session

    return sf


class TestConfidenceWorkerRun:
    def test_no_unprocessed_rows_no_update(self) -> None:
        """If no unprocessed evidence, confidence update is skipped."""
        from knowledge_graph.config import Settings
        from knowledge_graph.infrastructure.workers.confidence import ConfidenceWorker

        settings = Settings()
        sf = _make_session_factory()

        with (
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository"
            ) as MockRelRepo,
            patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence.RelationEvidenceRepository"
            ) as MockEvRepo,
            patch("knowledge_graph.infrastructure.intelligence_db.repositories.contradiction.ContradictionRepository"),
        ):
            mock_ev = AsyncMock()
            mock_ev.fetch_unprocessed_by_partition = AsyncMock(return_value=[])
            MockEvRepo.return_value = mock_ev

            worker = ConfidenceWorker(sf, settings)
            asyncio.run(worker.run())

            # mark_confidence_updated should never be called
            for _call in MockRelRepo.return_value.mock_calls:
                assert "mark_confidence_updated" not in str(_call)

    def test_confidence_bounded_at_one(self) -> None:
        """Computed confidence must always be clamped to [0, 1]."""
        from knowledge_graph.config import Settings
        from knowledge_graph.domain.confidence import EvidenceInput, compute_confidence
        from knowledge_graph.domain.enums import SemanticMode

        s = Settings()
        # Very high source weights — result must still be <= 1.0
        evidence = [
            EvidenceInput(source_weight=1.0, source_type="sec_10k", source_name="X", evidence_date=_NOW),
            EvidenceInput(source_weight=1.0, source_type="reuters", source_name="Y", evidence_date=_NOW),
            EvidenceInput(source_weight=1.0, source_type="ft", source_name="Z", evidence_date=_NOW),
        ]
        components = compute_confidence(
            evidence,
            [],
            0.01,
            SemanticMode.RELATION_STATE,
            corroboration_cap=s.confidence_corroboration_cap,
            contradiction_cap=s.confidence_contradiction_cap,
            temporal_claim_alpha=s.confidence_temporal_claim_alpha,
            corroboration_gain_per_source=s.confidence_corroboration_gain_per_source,
            corroboration_min_temporal_weight=s.confidence_corroboration_min_temporal_weight,
            contradiction_top_k=s.confidence_contradiction_top_k,
        )
        assert 0.0 <= components.final <= 1.0

    def test_confidence_never_negative(self) -> None:
        """Confidence must never go below 0.0 even with heavy contradictions."""
        from knowledge_graph.config import Settings
        from knowledge_graph.domain.confidence import (
            ContradictionInput,
            EvidenceInput,
            compute_confidence,
        )
        from knowledge_graph.domain.enums import SemanticMode

        s = Settings()
        evidence = [EvidenceInput(source_weight=0.01, source_type="x", source_name="a", evidence_date=_NOW)]
        contradictions = [
            ContradictionInput(strength=0.9, detected_at=_NOW),
            ContradictionInput(strength=0.9, detected_at=_NOW),
            ContradictionInput(strength=0.9, detected_at=_NOW),
        ]
        components = compute_confidence(
            evidence,
            contradictions,
            0.01,
            SemanticMode.RELATION_STATE,
            corroboration_cap=s.confidence_corroboration_cap,
            contradiction_cap=s.confidence_contradiction_cap,
            temporal_claim_alpha=s.confidence_temporal_claim_alpha,
            corroboration_gain_per_source=s.confidence_corroboration_gain_per_source,
            corroboration_min_temporal_weight=s.confidence_corroboration_min_temporal_weight,
            contradiction_top_k=s.confidence_contradiction_top_k,
        )
        assert components.final >= 0.0
