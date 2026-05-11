"""Unit tests for GET /api/v1/entities/{entity_id}/paths (PLAN-0074 Wave E2).

Tests:
- test_happy_path_returns_200             — valid entity with paths returns 200
- test_404_entity_not_found               — unknown entity_id returns 404
- test_422_invalid_params_min_hops_gt_max_hops — constraint violation returns 422
- test_422_invalid_limit_over_50          — limit > 50 returns 422
- test_empty_response_entity_with_no_paths — entity exists but no paths → 200 + empty list
- test_explanation_pending_field_present  — response includes explanation_pending
- test_default_query_params               — defaults work without explicit params
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000030")
_INSIGHT_ID = UUID("01900000-0000-7000-8000-000000000031")


def _composite_score(h: float = 0.7, d: float = 0.6, s: float = 0.5, match: bool = False) -> float:
    return round(min(h * 0.4 + d * 0.35 + s * 0.25, 1.0), 6)


def _make_paths_response(with_paths: bool = True) -> object:
    """Build an EntityPathsResponse (from Pydantic model) for use-case mock."""
    from knowledge_graph.api.schemas.paths import (
        EntityPathsResponse,
        PathEdgePublic,
        PathInsightPublic,
        PathNodePublic,
    )

    if not with_paths:
        return EntityPathsResponse(entity_id=_ENTITY_ID, paths=[], total=0, freshness_ts=None)

    node_a = PathNodePublic(entity_id=uuid4(), name="Apple Inc.", entity_type="financial_instrument")
    node_b = PathNodePublic(entity_id=uuid4(), name="Google LLC", entity_type="financial_instrument")
    edge = PathEdgePublic(relation_type="COMPETES_WITH", confidence=0.85)
    path = PathInsightPublic(
        insight_id=_INSIGHT_ID,
        hop_count=2,
        harmonic_score=0.7,
        diversity_score=0.6,
        surprise_score=0.5,
        template_match=None,
        composite_score=_composite_score(),
        path_nodes=[node_a, node_b],
        path_edges=[edge],
        llm_explanation=None,
        explanation_pending=True,
        computed_at=_NOW,
    )
    return EntityPathsResponse(
        entity_id=_ENTITY_ID,
        paths=[path],
        total=1,
        freshness_ts=_NOW,
    )


class TestGetEntityPathsRoute:
    async def test_happy_path_returns_200(self, api_app: object, api_client: object) -> None:
        """Valid entity with paths returns 200 with full response."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_paths_response(with_paths=True))
        # Simulate entity exists — router calls uc.entity_exists(entity_id).
        mock_uc.entity_exists = AsyncMock(return_value=True)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}/paths")  # type: ignore[union-attr]

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(_ENTITY_ID)
        assert body["total"] == 1
        assert len(body["paths"]) == 1
        assert body["paths"][0]["hop_count"] == 2
        assert body["paths"][0]["explanation_pending"] is True

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_404_entity_not_found(self, api_app: object, api_client: object) -> None:
        """Unknown entity_id returns 404."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)
        # Simulate entity does NOT exist — router calls uc.entity_exists(entity_id).
        mock_uc.entity_exists = AsyncMock(return_value=False)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(f"/api/v1/entities/{uuid4()}/paths")  # type: ignore[union-attr]

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Entity not found"

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_422_invalid_params_min_hops_gt_max_hops(self, api_app: object, api_client: object) -> None:
        """min_hops > max_hops must return 422 before calling the use case."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(  # type: ignore[union-attr]
            f"/api/v1/entities/{_ENTITY_ID}/paths?min_hops=4&max_hops=3"
        )

        assert resp.status_code == 422

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_422_invalid_limit_over_50(self, api_app: object, api_client: object) -> None:
        """limit > 50 must be rejected by FastAPI Query(le=50) → 422."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(  # type: ignore[union-attr]
            f"/api/v1/entities/{_ENTITY_ID}/paths?limit=51"
        )

        assert resp.status_code == 422

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_empty_response_entity_with_no_paths(self, api_app: object, api_client: object) -> None:
        """Entity exists but has no paths → 200 with empty paths list, NOT 404."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_paths_response(with_paths=False))
        # Entity exists — router calls uc.entity_exists(entity_id).
        mock_uc.entity_exists = AsyncMock(return_value=True)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}/paths")  # type: ignore[union-attr]

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["paths"] == []
        assert body["freshness_ts"] is None

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_explanation_pending_field_present_in_response(self, api_app: object, api_client: object) -> None:
        """explanation_pending must be a boolean field in the response body."""
        from knowledge_graph.api.dependencies import get_entity_paths_uc
        from knowledge_graph.application.use_cases.get_entity_paths import GetEntityPathsUseCase

        mock_uc = AsyncMock(spec=GetEntityPathsUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_paths_response(with_paths=True))
        # Entity exists — router calls uc.entity_exists(entity_id).
        mock_uc.entity_exists = AsyncMock(return_value=True)

        api_app.dependency_overrides[get_entity_paths_uc] = lambda: mock_uc  # type: ignore[union-attr]

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}/paths")  # type: ignore[union-attr]

        assert resp.status_code == 200
        path_item = resp.json()["paths"][0]
        assert "explanation_pending" in path_item
        assert isinstance(path_item["explanation_pending"], bool)

        api_app.dependency_overrides.pop(get_entity_paths_uc, None)

    async def test_invalid_uuid_returns_422(self, api_client: object) -> None:
        """Non-UUID entity_id path param returns 422 Unprocessable Entity."""
        resp = await api_client.get("/api/v1/entities/not-a-uuid/paths")  # type: ignore[union-attr]
        assert resp.status_code == 422
