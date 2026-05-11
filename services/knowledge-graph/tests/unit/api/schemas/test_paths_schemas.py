"""Unit tests for PathInsightPublic / EntityPathsResponse Pydantic schemas.

Validates that:
- All required fields are present and correctly typed.
- Nullable fields default to None (BP-126 / BP-148 guard).
- ``explanation_pending`` correctly reflects whether an explanation task was fired.
- ``EntityPathsResponse.freshness_ts`` is None when the paths list is empty.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000010")
_INSIGHT_ID = UUID("01900000-0000-7000-8000-000000000011")


def _make_node(name: str = "Apple Inc.") -> dict:
    return {
        "entity_id": str(uuid4()),
        "name": name,
        "entity_type": "financial_instrument",
    }


def _make_edge() -> dict:
    return {
        "relation_type": "COMPETES_WITH",
        "confidence": 0.85,
    }


def _make_insight(
    llm_explanation: str | None = None,
    template_match: str | None = None,
    explanation_pending: bool = False,
) -> dict:
    return {
        "insight_id": str(_INSIGHT_ID),
        "hop_count": 2,
        "harmonic_score": 0.75,
        "diversity_score": 0.60,
        "surprise_score": 0.50,
        "template_match": template_match,
        "composite_score": 0.65,
        "path_nodes": [_make_node("Apple Inc."), _make_node("Google LLC")],
        "path_edges": [_make_edge()],
        "llm_explanation": llm_explanation,
        "explanation_pending": explanation_pending,
        "computed_at": _NOW.isoformat(),
    }


class TestPathNodePublic:
    def test_all_fields_parsed(self) -> None:
        from knowledge_graph.api.schemas.paths import PathNodePublic

        node = PathNodePublic(**_make_node())
        assert isinstance(node.entity_id, UUID)
        assert node.name == "Apple Inc."
        assert node.entity_type == "financial_instrument"


class TestPathEdgePublic:
    def test_all_fields_parsed(self) -> None:
        from knowledge_graph.api.schemas.paths import PathEdgePublic

        edge = PathEdgePublic(**_make_edge())
        assert edge.relation_type == "COMPETES_WITH"
        assert edge.confidence == 0.85


class TestPathInsightPublic:
    def test_schema_all_required_fields_present(self) -> None:
        """All non-optional fields must be present and correctly typed."""
        from knowledge_graph.api.schemas.paths import PathInsightPublic

        data = _make_insight(llm_explanation="Apple competes with Google.", explanation_pending=False)
        insight = PathInsightPublic(**data)

        assert insight.insight_id == _INSIGHT_ID
        assert insight.hop_count == 2
        assert insight.harmonic_score == 0.75
        assert insight.diversity_score == 0.60
        assert insight.surprise_score == 0.50
        assert insight.composite_score == 0.65
        assert len(insight.path_nodes) == 2
        assert len(insight.path_edges) == 1
        assert insight.llm_explanation == "Apple competes with Google."
        assert insight.explanation_pending is False
        assert isinstance(insight.computed_at, datetime)

    def test_nullable_fields_default_to_none(self) -> None:
        """BP-126: nullable fields must have default=None — not missing/required."""
        from knowledge_graph.api.schemas.paths import PathInsightPublic

        # Omit template_match and llm_explanation — must NOT raise ValidationError.
        data = _make_insight()
        # Remove optional fields to test defaults.
        data.pop("template_match", None)
        data.pop("llm_explanation", None)

        insight = PathInsightPublic(**data)
        assert insight.template_match is None
        assert insight.llm_explanation is None

    def test_explanation_pending_true_when_explanation_missing(self) -> None:
        """explanation_pending=True indicates that a background task was fired."""
        from knowledge_graph.api.schemas.paths import PathInsightPublic

        insight = PathInsightPublic(**_make_insight(llm_explanation=None, explanation_pending=True))
        assert insight.llm_explanation is None
        assert insight.explanation_pending is True

    def test_explanation_pending_false_when_explanation_populated(self) -> None:
        """explanation_pending=False when the explanation is already present."""
        from knowledge_graph.api.schemas.paths import PathInsightPublic

        insight = PathInsightPublic(**_make_insight(llm_explanation="Some explanation.", explanation_pending=False))
        assert insight.llm_explanation == "Some explanation."
        assert insight.explanation_pending is False


class TestEntityPathsResponse:
    def test_schema_all_fields_present(self) -> None:
        """EntityPathsResponse must carry entity_id, paths, total, freshness_ts."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse, PathInsightPublic

        path = PathInsightPublic(**_make_insight(explanation_pending=False))
        resp = EntityPathsResponse(
            entity_id=_ENTITY_ID,
            paths=[path],
            total=1,
            freshness_ts=_NOW,
        )
        assert resp.entity_id == _ENTITY_ID
        assert len(resp.paths) == 1
        assert resp.total == 1
        assert resp.freshness_ts == _NOW

    def test_freshness_ts_none_when_no_paths(self) -> None:
        """BP-126: freshness_ts defaults to None — not a required field."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        # Omit freshness_ts entirely — must NOT raise ValidationError.
        resp = EntityPathsResponse(entity_id=_ENTITY_ID, paths=[], total=0)
        assert resp.freshness_ts is None

    def test_total_reflects_paths_length(self) -> None:
        """total must equal len(paths) — caller responsibility, validated here."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse, PathInsightPublic

        path = PathInsightPublic(**_make_insight(explanation_pending=False))
        resp = EntityPathsResponse(entity_id=_ENTITY_ID, paths=[path], total=1, freshness_ts=_NOW)
        assert resp.total == len(resp.paths)

    def test_json_round_trip(self) -> None:
        """model_dump / model_validate round-trip must not lose data."""
        from knowledge_graph.api.schemas.paths import EntityPathsResponse

        resp = EntityPathsResponse(
            entity_id=_ENTITY_ID,
            paths=[],
            total=0,
            freshness_ts=None,
        )
        data = resp.model_dump()
        restored = EntityPathsResponse.model_validate(data)
        assert restored.entity_id == _ENTITY_ID
        assert restored.total == 0
        assert restored.freshness_ts is None
