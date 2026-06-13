"""Unit tests for GET /api/v1/connections/weird (PLAN-0112 W5, T-5-02).

Tests the router wiring + param validation in isolation by overriding the
``get_global_weird_connections_uc`` dependency with a mock use case:
  - happy path → 200 + response shape (connections / total / freshness_ts)
  - filters forwarded to the use case
  - 422 limit out of range (FastAPI Query le)
  - 422 unknown entity_type (router-level enum guard)
  - 422 from use-case ValueError
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)
_SRC = UUID("01900000-0000-7000-8000-0000000000b1")
_DST = UUID("01900000-0000-7000-8000-0000000000b2")


def _make_response(n: int = 1) -> object:
    from knowledge_graph.api.schemas.paths import (
        PathEdgePublic,
        PathNodePublic,
        WeirdConnectionPublic,
        WeirdConnectionsResponse,
    )

    connections = []
    for _ in range(n):
        connections.append(
            WeirdConnectionPublic(
                src_entity_id=_SRC,
                dst_entity_id=_DST,
                hop_count=2,
                reliability=0.85,
                unexpectedness=0.6,
                semantic_distance=0.7,
                novelty=0.2,
                weirdness=0.42,
                path_nodes=[
                    PathNodePublic(entity_id=_SRC, name="Apple", entity_type="company"),
                    PathNodePublic(entity_id=uuid4(), name="TSMC", entity_type="company"),
                    PathNodePublic(entity_id=_DST, name="Nvidia", entity_type="company"),
                ],
                path_edges=[
                    PathEdgePublic(relation_type="SUPPLIED_BY", confidence=0.9),
                    PathEdgePublic(relation_type="SUPPLIES", confidence=0.8),
                ],
                computed_at=_NOW,
            )
        )
    return WeirdConnectionsResponse(connections=connections, total=n, freshness_ts=_NOW if n else None)


def _override(api_app: object, mock_uc: object) -> None:
    from knowledge_graph.api.dependencies import get_global_weird_connections_uc

    api_app.dependency_overrides[get_global_weird_connections_uc] = lambda: mock_uc  # type: ignore[union-attr]


def _clear(api_app: object) -> None:
    from knowledge_graph.api.dependencies import get_global_weird_connections_uc

    api_app.dependency_overrides.pop(get_global_weird_connections_uc, None)  # type: ignore[union-attr]


class TestWeirdConnectionsRoute:
    async def test_happy_path_200(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.global_weird_connections import (
            GlobalWeirdConnectionsUseCase,
        )

        mock_uc = AsyncMock(spec=GlobalWeirdConnectionsUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_response(2))
        _override(api_app, mock_uc)
        resp = await api_client.get("/api/v1/connections/weird")  # type: ignore[union-attr]
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["connections"]) == 2
        first = body["connections"][0]
        assert first["src_entity_id"] == str(_SRC)
        assert first["dst_entity_id"] == str(_DST)
        assert first["weirdness"] == 0.42
        assert "computed_at" in first
        assert body["freshness_ts"] is not None
        _clear(api_app)

    async def test_filters_forwarded(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.global_weird_connections import (
            GlobalWeirdConnectionsUseCase,
        )

        mock_uc = AsyncMock(spec=GlobalWeirdConnectionsUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_response(0))
        _override(api_app, mock_uc)
        resp = await api_client.get(  # type: ignore[union-attr]
            "/api/v1/connections/weird" "?limit=5&offset=10&min_weirdness=0.4&since_days=7&entity_type=company"
        )
        assert resp.status_code == 200
        mock_uc.execute.assert_awaited_once_with(
            limit=5,
            offset=10,
            min_weirdness=0.4,
            since_days=7,
            entity_type="company",
        )
        _clear(api_app)

    async def test_422_limit_out_of_range(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.global_weird_connections import (
            GlobalWeirdConnectionsUseCase,
        )

        mock_uc = AsyncMock(spec=GlobalWeirdConnectionsUseCase)
        _override(api_app, mock_uc)
        resp = await api_client.get("/api/v1/connections/weird?limit=101")  # type: ignore[union-attr]
        assert resp.status_code == 422
        _clear(api_app)

    async def test_422_unknown_entity_type(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.global_weird_connections import (
            GlobalWeirdConnectionsUseCase,
        )

        mock_uc = AsyncMock(spec=GlobalWeirdConnectionsUseCase)
        _override(api_app, mock_uc)
        resp = await api_client.get("/api/v1/connections/weird?entity_type=banana")  # type: ignore[union-attr]
        assert resp.status_code == 422
        _clear(api_app)

    async def test_422_from_use_case_value_error(self, api_app: object, api_client: object) -> None:
        from knowledge_graph.application.use_cases.global_weird_connections import (
            GlobalWeirdConnectionsUseCase,
        )

        mock_uc = AsyncMock(spec=GlobalWeirdConnectionsUseCase)
        mock_uc.execute = AsyncMock(side_effect=ValueError("bad param"))
        _override(api_app, mock_uc)
        resp = await api_client.get("/api/v1/connections/weird")  # type: ignore[union-attr]
        assert resp.status_code == 422
        _clear(api_app)
