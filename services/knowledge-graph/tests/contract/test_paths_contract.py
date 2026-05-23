"""Contract tests for EntityPathsResponse schema shape (PLAN-0074 Wave E2).

These tests assert that the wire-format schema used by the API is stable and
contains the expected fields with the correct types.  They are NOT end-to-end
tests — no DB or HTTP calls are made.

A "contract" test here means: the external consumer (e.g. the frontend / S9 gateway)
can rely on these fields always being present at the documented types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit  # fast, no infrastructure required

_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000040")
_INSIGHT_ID = UUID("01900000-0000-7000-8000-000000000041")
_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def _full_response_dict() -> dict:
    """Build a minimal valid wire-format dict for EntityPathsResponse."""
    return {
        "entity_id": str(_ENTITY_ID),
        "paths": [
            {
                "insight_id": str(_INSIGHT_ID),
                "hop_count": 2,
                "harmonic_score": 0.75,
                "diversity_score": 0.60,
                "surprise_score": 0.50,
                "template_match": None,
                "composite_score": 0.648,
                "path_nodes": [
                    {"entity_id": str(uuid4()), "name": "Apple Inc.", "entity_type": "financial_instrument"},
                    {"entity_id": str(uuid4()), "name": "Google LLC", "entity_type": "financial_instrument"},
                ],
                "path_edges": [
                    {"relation_type": "COMPETES_WITH", "confidence": 0.85},
                ],
                "llm_explanation": None,
                "explanation_pending": True,
                "computed_at": _NOW.isoformat(),
            },
        ],
        "total": 1,
        "freshness_ts": _NOW.isoformat(),
    }


class TestEntityPathsResponseContractShape:
    def test_top_level_fields_are_present(self) -> None:
        """entity_id, paths, total, freshness_ts must all be present."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())

        assert hasattr(resp, "entity_id")
        assert hasattr(resp, "paths")
        assert hasattr(resp, "total")
        assert hasattr(resp, "freshness_ts")

    def test_entity_id_is_uuid(self) -> None:
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        assert isinstance(resp.entity_id, UUID)

    def test_paths_is_list(self) -> None:
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        assert isinstance(resp.paths, list)

    def test_total_equals_paths_length(self) -> None:
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        assert resp.total == len(resp.paths)

    def test_path_insight_fields_are_present(self) -> None:
        """Each PathInsightPublic must have the required fields."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        path = resp.paths[0]

        assert hasattr(path, "insight_id")
        assert hasattr(path, "hop_count")
        assert hasattr(path, "harmonic_score")
        assert hasattr(path, "diversity_score")
        assert hasattr(path, "surprise_score")
        assert hasattr(path, "template_match")
        assert hasattr(path, "composite_score")
        assert hasattr(path, "path_nodes")
        assert hasattr(path, "path_edges")
        assert hasattr(path, "llm_explanation")
        assert hasattr(path, "explanation_pending")
        assert hasattr(path, "computed_at")

    def test_path_node_fields_are_present(self) -> None:
        """PathNodePublic must have entity_id, name, entity_type."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        node = resp.paths[0].path_nodes[0]

        assert isinstance(node.entity_id, UUID)
        assert isinstance(node.name, str)
        assert isinstance(node.entity_type, str)

    def test_path_edge_fields_are_present(self) -> None:
        """PathEdgePublic must have relation_type and confidence."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse.model_validate(_full_response_dict())
        edge = resp.paths[0].path_edges[0]

        assert isinstance(edge.relation_type, str)
        assert isinstance(edge.confidence, float)

    def test_nullable_fields_accept_none(self) -> None:
        """template_match, llm_explanation, freshness_ts must accept None (BP-126)."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        data = _full_response_dict()
        data["freshness_ts"] = None
        # Paths already have template_match=None and llm_explanation=None.

        # Must not raise ValidationError.
        resp = EntityPathsResponse.model_validate(data)
        assert resp.freshness_ts is None
        assert resp.paths[0].template_match is None
        assert resp.paths[0].llm_explanation is None

    def test_empty_paths_list_is_valid(self) -> None:
        """total=0, paths=[], freshness_ts=None is a valid empty response."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse(entity_id=_ENTITY_ID, paths=[], total=0)
        assert resp.total == 0
        assert resp.paths == []
        assert resp.freshness_ts is None
