"""Unit tests for PathInsight and PathInsightJob domain entities (T-E1-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def _make_edges(n: int, confidence: float = 0.8) -> tuple:
    from knowledge_graph.domain.entities.path_insight import PathEdge

    return tuple(PathEdge(relation_type="SUPPLIES_TO", confidence=confidence) for _ in range(n))


def _make_nodes(n: int) -> tuple:
    from knowledge_graph.domain.entities.path_insight import PathNode

    return tuple(PathNode(entity_id=uuid4(), name=f"Entity{i}", entity_type="company") for i in range(n))


def _composite(harmonic: float, diversity: float, surprise: float, template: bool = False) -> float:
    return round(min(harmonic * 0.4 + diversity * 0.35 + surprise * 0.25 + (0.1 if template else 0.0), 1.0), 6)


class TestPathEdge:
    def test_path_edge_confidence_bounds_zero(self) -> None:
        """PathEdge allows confidence=0.0 (boundary)."""
        from knowledge_graph.domain.entities.path_insight import PathEdge

        e = PathEdge(relation_type="OWNS", confidence=0.0)
        assert e.confidence == 0.0

    def test_path_edge_confidence_bounds_one(self) -> None:
        """PathEdge allows confidence=1.0 (boundary)."""
        from knowledge_graph.domain.entities.path_insight import PathEdge

        e = PathEdge(relation_type="OWNS", confidence=1.0)
        assert e.confidence == 1.0

    def test_path_edge_confidence_bounds_invalid_negative(self) -> None:
        """PathEdge raises ValueError when confidence < 0.0."""
        from knowledge_graph.domain.entities.path_insight import PathEdge

        with pytest.raises(ValueError, match="confidence"):
            PathEdge(relation_type="OWNS", confidence=-0.01)

    def test_path_edge_confidence_bounds_invalid_above_one(self) -> None:
        """PathEdge raises ValueError when confidence > 1.0."""
        from knowledge_graph.domain.entities.path_insight import PathEdge

        with pytest.raises(ValueError, match="confidence"):
            PathEdge(relation_type="OWNS", confidence=1.001)

    def test_path_edge_frozen(self) -> None:
        """PathEdge is immutable (frozen dataclass)."""
        from knowledge_graph.domain.entities.path_insight import PathEdge

        e = PathEdge(relation_type="OWNS", confidence=0.5)
        with pytest.raises((AttributeError, TypeError)):
            e.confidence = 0.9  # type: ignore[misc]


class TestPathInsight:
    def _make_insight(
        self,
        hop_count: int = 2,
        harmonic: float = 0.7,
        diversity: float = 0.6,
        surprise: float = 0.5,
        template: str | None = None,
    ) -> object:
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(hop_count, confidence=0.8)
        nodes = _make_nodes(hop_count + 1)
        score = _composite(harmonic, diversity, surprise, template is not None)
        return PathInsight(
            insight_id=uuid4(),
            anchor_entity_id=uuid4(),
            hop_count=hop_count,
            path_nodes=nodes,
            path_edges=edges,
            harmonic_score=harmonic,
            diversity_score=diversity,
            surprise_score=surprise,
            composite_score=score,
            computed_at=_NOW,
            template_match=template,
        )

    def test_path_insight_invariant_hop_count_matches_edges(self) -> None:
        """PathInsight raises ValueError when hop_count != len(path_edges)."""
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(3, confidence=0.8)
        nodes = _make_nodes(4)
        score = _composite(0.7, 0.6, 0.5)
        with pytest.raises(ValueError, match="hop_count"):
            PathInsight(
                insight_id=uuid4(),
                anchor_entity_id=uuid4(),
                hop_count=2,  # mismatch: edges has 3
                path_nodes=nodes,
                path_edges=edges,
                harmonic_score=0.7,
                diversity_score=0.6,
                surprise_score=0.5,
                composite_score=score,
                computed_at=_NOW,
            )

    def test_path_insight_invariant_hop_count_too_low(self) -> None:
        """PathInsight raises ValueError when hop_count < 2."""
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(1, confidence=0.8)
        nodes = _make_nodes(2)
        score = _composite(0.7, 0.6, 0.5)
        with pytest.raises(ValueError, match="hop_count"):
            PathInsight(
                insight_id=uuid4(),
                anchor_entity_id=uuid4(),
                hop_count=1,
                path_nodes=nodes,
                path_edges=edges,
                harmonic_score=0.7,
                diversity_score=0.6,
                surprise_score=0.5,
                composite_score=score,
                computed_at=_NOW,
            )

    def test_path_insight_invariant_hop_count_too_high(self) -> None:
        """PathInsight raises ValueError when hop_count > 5."""
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(6, confidence=0.8)
        nodes = _make_nodes(7)
        score = _composite(0.7, 0.6, 0.5)
        with pytest.raises(ValueError, match="hop_count"):
            PathInsight(
                insight_id=uuid4(),
                anchor_entity_id=uuid4(),
                hop_count=6,
                path_nodes=nodes,
                path_edges=edges,
                harmonic_score=0.7,
                diversity_score=0.6,
                surprise_score=0.5,
                composite_score=score,
                computed_at=_NOW,
            )

    def test_path_insight_composite_score_formula_no_template(self) -> None:
        """PathInsight validates composite_score formula (no template match)."""
        insight = self._make_insight(hop_count=2, harmonic=0.8, diversity=0.6, surprise=0.5)
        from knowledge_graph.domain.entities.path_insight import PathInsight

        assert isinstance(insight, PathInsight)
        # composite = 0.8*0.4 + 0.6*0.35 + 0.5*0.25 = 0.32 + 0.21 + 0.125 = 0.655
        assert abs(insight.composite_score - 0.655) < 1e-5  # type: ignore[attr-defined]

    def test_path_insight_composite_score_formula_with_template(self) -> None:
        """PathInsight adds 0.1 template bonus to composite_score."""
        insight = self._make_insight(
            hop_count=2, harmonic=0.8, diversity=0.6, surprise=0.5, template="supply_chain_3hop"
        )
        from knowledge_graph.domain.entities.path_insight import PathInsight

        assert isinstance(insight, PathInsight)
        # composite = 0.655 + 0.1 = 0.755
        assert abs(insight.composite_score - 0.755) < 1e-5  # type: ignore[attr-defined]

    def test_path_insight_composite_score_clamped_to_one(self) -> None:
        """PathInsight clamps composite_score to 1.0 when formula exceeds 1.0."""
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(2, confidence=0.9)
        nodes = _make_nodes(3)
        # Scores that would exceed 1.0 before clamping
        harmonic = 1.0
        diversity = 1.0
        surprise = 1.0
        template = "supply_chain_3hop"
        score = _composite(harmonic, diversity, surprise, True)
        assert score == 1.0  # clamped
        insight = PathInsight(
            insight_id=uuid4(),
            anchor_entity_id=uuid4(),
            hop_count=2,
            path_nodes=nodes,
            path_edges=edges,
            harmonic_score=harmonic,
            diversity_score=diversity,
            surprise_score=surprise,
            composite_score=score,
            computed_at=_NOW,
            template_match=template,
        )
        assert insight.composite_score == 1.0

    def test_path_insight_composite_score_mismatch_raises(self) -> None:
        """PathInsight raises ValueError when composite_score doesn't match formula."""
        from knowledge_graph.domain.entities.path_insight import PathInsight

        edges = _make_edges(2, confidence=0.8)
        nodes = _make_nodes(3)
        with pytest.raises(ValueError, match="composite_score"):
            PathInsight(
                insight_id=uuid4(),
                anchor_entity_id=uuid4(),
                hop_count=2,
                path_nodes=nodes,
                path_edges=edges,
                harmonic_score=0.7,
                diversity_score=0.6,
                surprise_score=0.5,
                composite_score=0.999,  # wrong value
                computed_at=_NOW,
            )

    def test_path_insight_frozen(self) -> None:
        """PathInsight is immutable (frozen dataclass)."""
        insight = self._make_insight()
        with pytest.raises((AttributeError, TypeError)):
            insight.hop_count = 3  # type: ignore[misc]

    def test_path_insight_llm_explanation_none_by_default(self) -> None:
        """PathInsight.llm_explanation defaults to None (no LLM in Wave E1)."""
        insight = self._make_insight()
        assert insight.llm_explanation is None  # type: ignore[attr-defined]

    def test_path_insight_max_hop_count_5(self) -> None:
        """PathInsight accepts hop_count=5 (max boundary)."""
        insight = self._make_insight(hop_count=5, harmonic=0.5, diversity=0.5, surprise=0.5)
        from knowledge_graph.domain.entities.path_insight import PathInsight

        assert isinstance(insight, PathInsight)
        assert insight.hop_count == 5  # type: ignore[attr-defined]


class TestPathInsightJob:
    def _make_job(
        self,
        status: str = "pending",
        claimed_by: object = None,
        retry_count: int = 0,
    ) -> object:
        from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

        return PathInsightJob(
            job_id=uuid4(),
            entity_id=uuid4(),
            status=PathJobStatus(status),
            created_at=_NOW,
            claimed_by=claimed_by,  # type: ignore[arg-type]
            retry_count=retry_count,
        )

    def test_path_job_status_pending_no_claimed_by(self) -> None:
        """PENDING job with claimed_by=None is valid."""
        job = self._make_job(status="pending", claimed_by=None)
        from knowledge_graph.domain.entities.path_insight import PathInsightJob

        assert isinstance(job, PathInsightJob)

    def test_path_job_status_running_requires_claimed_by(self) -> None:
        """RUNNING job without claimed_by raises ValueError."""
        from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

        with pytest.raises(ValueError, match="claimed_by"):
            PathInsightJob(
                job_id=uuid4(),
                entity_id=uuid4(),
                status=PathJobStatus.RUNNING,
                created_at=_NOW,
                claimed_by=None,  # missing — should raise
            )

    def test_path_job_status_pending_with_claimed_by_raises(self) -> None:
        """PENDING job with claimed_by set raises ValueError."""
        from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

        with pytest.raises(ValueError, match="claimed_by"):
            PathInsightJob(
                job_id=uuid4(),
                entity_id=uuid4(),
                status=PathJobStatus.PENDING,
                created_at=_NOW,
                claimed_by=uuid4(),  # should only be set for RUNNING
            )

    def test_path_job_status_running_valid_with_claimed_by(self) -> None:
        """RUNNING job with claimed_by set is valid."""
        from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

        job = PathInsightJob(
            job_id=uuid4(),
            entity_id=uuid4(),
            status=PathJobStatus.RUNNING,
            created_at=_NOW,
            claimed_by=uuid4(),
        )
        assert job.status == PathJobStatus.RUNNING
        assert job.claimed_by is not None

    def test_path_job_retry_cap_at_3(self) -> None:
        """PathInsightJob raises ValueError when retry_count > 3."""
        from knowledge_graph.domain.entities.path_insight import PathInsightJob, PathJobStatus

        with pytest.raises(ValueError, match="retry_count"):
            PathInsightJob(
                job_id=uuid4(),
                entity_id=uuid4(),
                status=PathJobStatus.PENDING,
                created_at=_NOW,
                retry_count=4,  # exceeds max
            )

    def test_path_job_retry_count_3_allowed(self) -> None:
        """retry_count=3 is the boundary maximum and must be accepted."""
        job = self._make_job(status="pending", retry_count=3)
        from knowledge_graph.domain.entities.path_insight import PathInsightJob

        assert isinstance(job, PathInsightJob)
        assert job.retry_count == 3  # type: ignore[attr-defined]

    def test_path_job_done_status_no_claimed_by_allowed(self) -> None:
        """DONE status with no claimed_by is valid (claimed_by cleared after completion)."""
        job = self._make_job(status="done", claimed_by=None)
        from knowledge_graph.domain.entities.path_insight import PathInsightJob

        assert isinstance(job, PathInsightJob)

    def test_path_job_failed_status_no_claimed_by_allowed(self) -> None:
        """FAILED status with no claimed_by is valid."""
        job = self._make_job(status="failed", claimed_by=None)
        from knowledge_graph.domain.entities.path_insight import PathInsightJob

        assert isinstance(job, PathInsightJob)
