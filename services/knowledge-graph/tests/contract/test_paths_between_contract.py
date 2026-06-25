"""Contract tests for the pairwise PathsBetweenResponse schema (PLAN-0112 W4, T-4-05).

The S9 gateway proxies S6's ``GET /api/v1/paths/between`` verbatim and mirrors
the response schema (``api_gateway.schemas.paths.PathsBetweenResponse``). This
test pins the S6 wire format so the S9 mirror — and the rag-chat
``PathBetweenResult`` parser — can rely on these fields/types always being
present. No DB or HTTP calls are made (pure schema contract).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_SRC = UUID("01900000-0000-7000-8000-000000000050")
_TGT = UUID("01900000-0000-7000-8000-000000000051")
_NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def _connected_dict() -> dict:
    """A minimal valid connected PathsBetweenResponse wire dict."""
    return {
        "source_entity_id": str(_SRC),
        "target_entity_id": str(_TGT),
        "connected": True,
        "shortest_hops": 2,
        "paths": [
            {
                "path_nodes": [
                    {"entity_id": str(_SRC), "name": "Apple Inc.", "entity_type": "company"},
                    {"entity_id": str(uuid4()), "name": "TSMC", "entity_type": "company"},
                    {"entity_id": str(_TGT), "name": "Nvidia", "entity_type": "company"},
                ],
                "path_edges": [
                    {"relation_type": "SUPPLIED_BY", "confidence": 0.9},
                    {"relation_type": "SUPPLIES", "confidence": 0.8},
                ],
                "hop_count": 2,
                "reliability": 0.85,
                "unexpectedness": 0.5,
                "semantic_distance": 0.6,
                "novelty": 0.1,
                "weirdness": 0.42,
            }
        ],
        "computed_at": _NOW.isoformat(),
    }


class TestPathsBetweenResponseContractShape:
    def test_top_level_fields_present(self) -> None:
        from knowledge_graph.api.schemas.paths import PathsBetweenResponse

        resp = PathsBetweenResponse.model_validate(_connected_dict())
        assert isinstance(resp.source_entity_id, UUID)
        assert isinstance(resp.target_entity_id, UUID)
        assert resp.connected is True
        assert resp.shortest_hops == 2
        assert isinstance(resp.paths, list)
        assert isinstance(resp.computed_at, datetime)

    def test_path_between_subscore_fields_present(self) -> None:
        from knowledge_graph.api.schemas.paths import PathsBetweenResponse

        resp = PathsBetweenResponse.model_validate(_connected_dict())
        p = resp.paths[0]
        for field in ("reliability", "unexpectedness", "semantic_distance", "novelty", "weirdness"):
            assert isinstance(getattr(p, field), float)
        assert p.hop_count == len(p.path_edges)
        assert len(p.path_nodes) == len(p.path_edges) + 1

    def test_disconnected_shape(self) -> None:
        from knowledge_graph.api.schemas.paths import PathsBetweenResponse

        resp = PathsBetweenResponse(
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            connected=False,
            shortest_hops=None,
            paths=[],
            computed_at=_NOW,
        )
        assert resp.connected is False
        assert resp.shortest_hops is None
        assert resp.paths == []

    def test_rag_chat_result_parses_s6_shape(self) -> None:
        """The rag-chat S7IntelligenceClient parses ``connected``/``shortest_hops``/``paths``.

        Mirrors the field access in ``S7IntelligenceClient.get_path_between`` so a
        rename on the S6 side would fail here before it reaches production.
        """
        raw = _connected_dict()
        assert "connected" in raw
        assert "shortest_hops" in raw
        assert "paths" in raw
        assert raw["paths"][0]["weirdness"] == 0.42
