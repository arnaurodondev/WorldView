"""Unit tests for GetEntityPathsUseCase (PLAN-0074 Wave E2).

Tests:
- test_filter_validation_min_hops_gt_max_hops     — raises ValueError
- test_filter_validation_invalid_limit            — raises ValueError
- test_schema_all_fields_present                  — use case returns complete response
- test_empty_response_when_no_paths               — empty list without 404
- test_response_sorted_by_composite_score_desc    — ordering from repo preserved
- test_freshness_ts_is_max_computed_at            — MAX(computed_at) computed correctly
- test_explanation_pending_when_no_llm_explanation — pending=True for null explanations
- test_no_background_task_when_no_explanation_service — pending=False when service=None
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW_1 = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)
_NOW_2 = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)  # later → MAX
_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000020")


def _composite_score(h: float, d: float, s: float, match: bool = False) -> float:
    """Replicate the PathInsight composite_score formula."""
    return round(
        min(h * 0.4 + d * 0.35 + s * 0.25 + (0.1 if match else 0.0), 1.0),
        6,
    )


def _make_path_insight(
    h: float = 0.75,
    d: float = 0.60,
    s: float = 0.50,
    computed_at: datetime = _NOW_1,
    llm_explanation: str | None = None,
) -> object:
    """Build a real PathInsight domain entity.

    hop_count=2 requires exactly 2 edges (invariant: hop_count == len(path_edges)).
    Nodes: 3 (one per hop boundary).

    composite_score is always derived from h/d/s via the formula so the domain
    invariant is never violated.
    """
    from knowledge_graph.domain.entities.path_insight import PathEdge, PathInsight, PathNode

    cs = _composite_score(h, d, s)
    node_a = PathNode(entity_id=uuid4(), name="Apple Inc.", entity_type="financial_instrument")
    node_b = PathNode(entity_id=uuid4(), name="Google LLC", entity_type="financial_instrument")
    node_c = PathNode(entity_id=uuid4(), name="NVIDIA Corp.", entity_type="financial_instrument")
    edge_1 = PathEdge(relation_type="COMPETES_WITH", confidence=0.85)
    edge_2 = PathEdge(relation_type="SUPPLIES_TO", confidence=0.75)

    return PathInsight(
        insight_id=uuid4(),
        anchor_entity_id=_ENTITY_ID,
        hop_count=2,
        path_nodes=(node_a, node_b, node_c),
        path_edges=(edge_1, edge_2),
        harmonic_score=h,
        diversity_score=d,
        surprise_score=s,
        template_match=None,
        composite_score=cs,
        computed_at=computed_at,
        llm_explanation=llm_explanation,
    )


class TestGetEntityPathsUseCaseValidation:
    async def test_filter_validation_min_hops_gt_max_hops(self) -> None:
        """min_hops > max_hops must raise ValueError."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)

        with pytest.raises(ValueError, match="min_hops"):
            await uc.execute(_ENTITY_ID, min_hops=4, max_hops=3)

    async def test_filter_validation_invalid_limit_too_high(self) -> None:
        """limit > 50 must raise ValueError."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)

        with pytest.raises(ValueError, match="limit"):
            await uc.execute(_ENTITY_ID, limit=51)

    async def test_filter_validation_invalid_limit_too_low(self) -> None:
        """limit < 1 must raise ValueError."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)

        with pytest.raises(ValueError, match="limit"):
            await uc.execute(_ENTITY_ID, limit=0)

    async def test_filter_validation_invalid_min_score(self) -> None:
        """min_score outside [0.0, 1.0] must raise ValueError."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)

        with pytest.raises(ValueError, match="min_score"):
            await uc.execute(_ENTITY_ID, min_score=1.5)


class TestGetEntityPathsUseCaseExecution:
    async def test_schema_all_fields_present(self) -> None:
        """Response includes entity_id, paths, total, freshness_ts."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        path = _make_path_insight(computed_at=_NOW_1)
        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[path])

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)
        resp = await uc.execute(_ENTITY_ID)

        assert resp.entity_id == _ENTITY_ID
        assert len(resp.paths) == 1
        assert resp.total == 1
        assert resp.freshness_ts == _NOW_1
        # Verify sub-fields are populated.
        p = resp.paths[0]
        assert p.hop_count == 2
        assert len(p.path_nodes) == 3  # 2 hops → 3 nodes
        assert len(p.path_edges) == 2  # hop_count == len(path_edges)

    async def test_empty_response_when_no_paths(self) -> None:
        """Empty path list returns total=0 and freshness_ts=None."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[])

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)
        resp = await uc.execute(_ENTITY_ID)

        assert resp.entity_id == _ENTITY_ID
        assert resp.paths == []
        assert resp.total == 0
        assert resp.freshness_ts is None

    async def test_response_sorted_by_composite_score_desc(self) -> None:
        """Use case preserves the ordering returned by the repo (DESC by score).

        The repo contract specifies ORDER BY composite_score DESC.  The use case
        must NOT reorder the results.
        """
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        high = _make_path_insight(h=0.9, d=0.9, s=0.9, computed_at=_NOW_1)
        low = _make_path_insight(h=0.4, d=0.4, s=0.4, computed_at=_NOW_2)

        # Repo returns in DESC order.
        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[high, low])

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)
        resp = await uc.execute(_ENTITY_ID)

        assert resp.paths[0].composite_score > resp.paths[1].composite_score

    async def test_freshness_ts_is_max_computed_at(self) -> None:
        """freshness_ts must be MAX(computed_at) across all returned paths."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        older = _make_path_insight(computed_at=_NOW_1)
        newer = _make_path_insight(computed_at=_NOW_2)

        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[older, newer])

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)
        resp = await uc.execute(_ENTITY_ID)

        assert resp.freshness_ts == _NOW_2  # MAX

    async def test_explanation_pending_set_when_llm_explanation_null(self) -> None:
        """explanation_pending=True for paths with no llm_explanation AND service wired."""
        from knowledge_graph.application.services.path_explanation_service import PathExplanationService
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        path_no_exp = _make_path_insight(computed_at=_NOW_1, llm_explanation=None)
        path_has_exp = _make_path_insight(computed_at=_NOW_2, llm_explanation="Existing.")

        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[path_no_exp, path_has_exp])

        # Stub explanation service — generate_explanation must be async callable.
        mock_exp_service = AsyncMock(spec=PathExplanationService)
        mock_exp_service.generate_explanation = AsyncMock()

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo, explanation_service=mock_exp_service)

        import asyncio

        async def _run() -> object:
            resp = await uc.execute(_ENTITY_ID)
            # Drain any pending tasks so generate_explanation is called.
            await asyncio.sleep(0)
            return resp

        resp = await _run()

        pending_paths = [p for p in resp.paths if p.explanation_pending]
        ready_paths = [p for p in resp.paths if not p.explanation_pending]

        assert len(pending_paths) == 1
        assert len(ready_paths) == 1
        assert ready_paths[0].llm_explanation == "Existing."

    async def test_no_background_task_when_no_explanation_service(self) -> None:
        """explanation_pending=False for all paths when explanation_service=None."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        path = _make_path_insight(computed_at=_NOW_1, llm_explanation=None)

        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[path])

        # No explanation service wired.
        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo, explanation_service=None)
        resp = await uc.execute(_ENTITY_ID)

        assert resp.paths[0].explanation_pending is False

    async def test_repo_called_with_correct_params(self) -> None:
        """Use case must forward limit / min_score / min_hops / max_hops to repo."""
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_repo = AsyncMock()
        mock_repo.list_by_anchor = AsyncMock(return_value=[])

        uc = GetEntityPathsUseCase(path_insight_repo=mock_repo)
        await uc.execute(_ENTITY_ID, limit=5, min_score=0.5, min_hops=2, max_hops=4)

        mock_repo.list_by_anchor.assert_awaited_once_with(
            _ENTITY_ID,
            limit=5,
            min_score=0.5,
            min_hops=2,
            max_hops=4,
        )
