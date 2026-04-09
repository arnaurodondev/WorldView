"""Unit tests for GetEntityGraphUseCase, ListRelationsUseCase, GetGraphStatsUseCase."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_ENT_ID = uuid4()
_OBJ_ID = uuid4()


def _entity_row(entity_id: object = None) -> dict:
    return {
        "entity_id": entity_id or uuid4(),
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "ticker": "AAPL",
    }


def _relation_row(subject_id: object = None, object_id: object = None) -> dict:
    return {
        "relation_id": uuid4(),
        "subject_entity_id": subject_id or _ENT_ID,
        "object_entity_id": object_id or _OBJ_ID,
        "canonical_type": "COMPETES_WITH",
        "confidence": 0.80,
    }


def _make_entity_repo(entity: dict | None = None, batch: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=entity)
    repo.get_batch = AsyncMock(return_value=batch or [])
    return repo


def _make_relation_repo(rows: list | None = None, stats: dict | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.list_for_entity = AsyncMock(return_value=rows or [])
    repo.list_filtered = AsyncMock(return_value=(rows or [], len(rows or [])))
    repo.get_stats = AsyncMock(return_value=stats or {"relation_count": 0})
    return repo


class TestGetEntityGraphUseCase:
    def test_entity_not_found_returns_empty(self) -> None:
        """Returns (None, [], {}) when entity does not exist."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        entity_repo = _make_entity_repo(entity=None)
        relation_repo = _make_relation_repo()

        result = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                entity_id=_ENT_ID,
                min_confidence=0.3,
                semantic_mode=None,
                limit=50,
            )
        )

        entity_row, relation_rows, entities_map = result
        assert entity_row is None
        assert relation_rows == []
        assert entities_map == {}
        relation_repo.list_for_entity.assert_not_called()

    def test_entity_found_returns_row_and_relations(self) -> None:
        """Returns entity row and relation rows when entity exists."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        center = _entity_row(_ENT_ID)
        neighbor = _entity_row(_OBJ_ID)
        rel = _relation_row(subject_id=_ENT_ID, object_id=_OBJ_ID)

        entity_repo = _make_entity_repo(entity=center)
        entity_repo.get = AsyncMock(side_effect=lambda eid: center if eid == _ENT_ID else neighbor)
        relation_repo = _make_relation_repo(rows=[rel])

        entity_row, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                entity_id=_ENT_ID,
                min_confidence=0.5,
                semantic_mode="RELATION_STATE",
                limit=100,
            )
        )

        assert entity_row == center
        assert relation_rows == [rel]
        # Neighbor entity should appear in the map
        assert str(_OBJ_ID) in entities_map

    def test_referenced_entities_map_excludes_center(self) -> None:
        """The center entity is not included in the referenced entities map."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        center = _entity_row(_ENT_ID)
        # Relation both endpoints are the center (self-loop)
        self_loop = _relation_row(subject_id=_ENT_ID, object_id=_ENT_ID)

        entity_repo = _make_entity_repo(entity=center)
        relation_repo = _make_relation_repo(rows=[self_loop])

        _entity_row_out, _relations, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        # Self-loop: both endpoints are _ENT_ID which is excluded as center
        assert str(_ENT_ID) not in entities_map

    def test_relation_repo_called_with_correct_params(self) -> None:
        """list_for_entity is called with the correct filters."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        relation_repo = _make_relation_repo()

        asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                entity_id=_ENT_ID,
                min_confidence=0.45,
                semantic_mode="TEMPORAL_CLAIM",
                limit=75,
            )
        )

        relation_repo.list_for_entity.assert_called_once_with(
            entity_id=_ENT_ID,
            min_confidence=0.45,
            semantic_mode="TEMPORAL_CLAIM",
            limit=75,
        )

    def test_no_relations_returns_empty_map(self) -> None:
        """When no relations, referenced entities map is empty."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        relation_repo = _make_relation_repo(rows=[])

        _, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                entity_id=_ENT_ID,
                min_confidence=0.3,
                semantic_mode=None,
                limit=50,
            )
        )

        assert relation_rows == []
        assert entities_map == {}


class TestListRelationsUseCase:
    def test_returns_paginated_results(self) -> None:
        """Delegates filtering and pagination to the repository."""
        from knowledge_graph.application.use_cases.graph_query import ListRelationsUseCase

        rows = [_relation_row(), _relation_row()]
        relation_repo = _make_relation_repo(rows=rows)

        result, total = asyncio.run(
            ListRelationsUseCase().execute(
                relation_repo=relation_repo,
                subject_entity_id=None,
                object_entity_id=None,
                canonical_type="COMPETES_WITH",
                semantic_mode=None,
                min_confidence=0.5,
                limit=20,
                offset=0,
            )
        )

        assert len(result) == 2
        assert total == 2

    def test_filters_forwarded(self) -> None:
        """Subject, object, type, and confidence filters are forwarded."""
        from knowledge_graph.application.use_cases.graph_query import ListRelationsUseCase

        relation_repo = _make_relation_repo()
        subj = uuid4()
        obj = uuid4()

        asyncio.run(
            ListRelationsUseCase().execute(
                relation_repo=relation_repo,
                subject_entity_id=subj,
                object_entity_id=obj,
                canonical_type="HAS_EXECUTIVE",
                semantic_mode="RELATION_STATE",
                min_confidence=0.70,
                limit=10,
                offset=5,
            )
        )

        relation_repo.list_filtered.assert_called_once_with(
            subject_entity_id=subj,
            object_entity_id=obj,
            canonical_type="HAS_EXECUTIVE",
            semantic_mode="RELATION_STATE",
            min_confidence=0.70,
            limit=10,
            offset=5,
        )


class TestGetGraphStatsUseCase:
    def test_returns_stats_from_repo(self) -> None:
        """Passes stats dict from repository through unchanged."""
        from knowledge_graph.application.use_cases.graph_query import GetGraphStatsUseCase

        stats = {"relation_count": 150, "entity_count": 42}
        relation_repo = _make_relation_repo(stats=stats)

        result = asyncio.run(GetGraphStatsUseCase().execute(relation_repo=relation_repo))

        assert result == stats
        relation_repo.get_stats.assert_called_once()
