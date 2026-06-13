"""Unit tests for GET /api/v1/paths/between (PLAN-0112 W4, T-4-02).

Tests the router wiring + error mapping in isolation by overriding the
``get_find_paths_between_uc`` dependency with a mock use case:
  - happy path (connected) → 200 + response shape
  - disconnected → 200 connected=false / shortest_hops=null
  - 400 source == target (domain error)
  - 404 entity not found (domain error)
  - 422 max_hops out of range (FastAPI Query le)
  - 503 AGE timeout (CypherTimeoutError)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)
_SRC = UUID("01900000-0000-7000-8000-0000000000a1")
_TGT = UUID("01900000-0000-7000-8000-0000000000a2")


def _make_response(*, connected: bool) -> object:
    from knowledge_graph.api.schemas.paths import (
        PathBetweenPublic,
        PathEdgePublic,
        PathNodePublic,
        PathsBetweenResponse,
    )

    if not connected:
        return PathsBetweenResponse(
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            connected=False,
            shortest_hops=None,
            paths=[],
            computed_at=_NOW,
        )
    path = PathBetweenPublic(
        path_nodes=[
            PathNodePublic(entity_id=_SRC, name="Apple", entity_type="company"),
            PathNodePublic(entity_id=_TGT, name="OpenAI", entity_type="company"),
        ],
        path_edges=[PathEdgePublic(relation_type="PARTNERS_WITH", confidence=0.9)],
        hop_count=1,
        reliability=0.9,
        unexpectedness=0.5,
        semantic_distance=0.6,
        novelty=0.1,
        weirdness=0.42,
    )
    return PathsBetweenResponse(
        source_entity_id=_SRC,
        target_entity_id=_TGT,
        connected=True,
        shortest_hops=1,
        paths=[path],
        computed_at=_NOW,
    )


def _override(api_app: object, mock_uc: object) -> None:
    from knowledge_graph.api.dependencies import get_find_paths_between_uc

    api_app.dependency_overrides[get_find_paths_between_uc] = lambda: mock_uc  # type: ignore[union-attr]


def _clear(api_app: object) -> None:
    from knowledge_graph.api.dependencies import get_find_paths_between_uc

    api_app.dependency_overrides.pop(get_find_paths_between_uc, None)  # type: ignore[union-attr]


class TestPathsBetweenRoute:
    async def test_connected_200(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.find_paths_between import FindPathsBetweenUseCase

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_response(connected=True))
        _override(api_app, mock_uc)
        resp = await api_client.get(f"/api/v1/paths/between?source={_SRC}&target={_TGT}")  # type: ignore[union-attr]
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["shortest_hops"] == 1
        assert len(body["paths"]) == 1
        assert body["paths"][0]["weirdness"] == 0.42
        assert body["paths"][0]["hop_count"] == 1
        _clear(api_app)

    async def test_disconnected_200(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.find_paths_between import FindPathsBetweenUseCase

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_response(connected=False))
        _override(api_app, mock_uc)
        resp = await api_client.get(f"/api/v1/paths/between?source={_SRC}&target={_TGT}")  # type: ignore[union-attr]
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["shortest_hops"] is None
        assert body["paths"] == []
        _clear(api_app)

    async def test_400_same_entity(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.find_paths_between import (
            FindPathsBetweenUseCase,
            PathsBetweenSameEntityError,
        )

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        mock_uc.execute = AsyncMock(side_effect=PathsBetweenSameEntityError("same"))
        _override(api_app, mock_uc)
        resp = await api_client.get(f"/api/v1/paths/between?source={_SRC}&target={_SRC}")  # type: ignore[union-attr]
        assert resp.status_code == 400
        _clear(api_app)

    async def test_404_entity_not_found(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.find_paths_between import (
            FindPathsBetweenUseCase,
            PathsBetweenEntityNotFoundError,
        )

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        mock_uc.execute = AsyncMock(side_effect=PathsBetweenEntityNotFoundError(uuid4()))
        _override(api_app, mock_uc)
        resp = await api_client.get(f"/api/v1/paths/between?source={_SRC}&target={_TGT}")  # type: ignore[union-attr]
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Entity not found"
        _clear(api_app)

    async def test_422_max_hops_out_of_range(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.find_paths_between import FindPathsBetweenUseCase

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        _override(api_app, mock_uc)
        resp = await api_client.get(  # type: ignore[union-attr]
            f"/api/v1/paths/between?source={_SRC}&target={_TGT}&max_hops=4"
        )
        assert resp.status_code == 422
        _clear(api_app)

    async def test_503_timeout(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
        from knowledge_graph.application.use_cases.find_paths_between import FindPathsBetweenUseCase

        mock_uc = AsyncMock(spec=FindPathsBetweenUseCase)
        mock_uc.execute = AsyncMock(side_effect=CypherTimeoutError("timeout"))
        _override(api_app, mock_uc)
        resp = await api_client.get(f"/api/v1/paths/between?source={_SRC}&target={_TGT}")  # type: ignore[union-attr]
        assert resp.status_code == 503
        _clear(api_app)
