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


def _make_evidence_repo(snippets: dict | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_evidence_snippets_batch = AsyncMock(return_value=snippets or {})
    return repo


def _make_summary_repo(summaries: dict | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_current_summaries_batch = AsyncMock(return_value=summaries or {})
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
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
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
        entity_repo.get_batch = AsyncMock(return_value=[neighbor])
        relation_repo = _make_relation_repo(rows=[rel])

        entity_row, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
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
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
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
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
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
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.3,
                semantic_mode=None,
                limit=50,
            )
        )

        assert relation_rows == []
        assert entities_map == {}

    def test_evidence_snippets_merged_into_relation_rows(self) -> None:
        """evidence_snippets from the evidence repo are merged into each relation row."""

        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel_id = uuid4()
        rel = {
            "relation_id": rel_id,
            "subject_entity_id": _ENT_ID,
            "object_entity_id": _OBJ_ID,
            "canonical_type": "competes_with",
            "confidence": 0.80,
        }
        snippets = {rel_id: ["Apple Q3 revenue beat expectations.", "Cook cited iPhone sales."]}

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])
        evidence_repo = _make_evidence_repo(snippets=snippets)

        _, relation_rows, _ = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
                evidence_limit=3,
            )
        )

        assert len(relation_rows) == 1
        assert relation_rows[0]["evidence_snippets"] == [
            "Apple Q3 revenue beat expectations.",
            "Cook cited iPhone sales.",
        ]
        evidence_repo.get_evidence_snippets_batch.assert_called_once_with([rel_id], limit_per_relation=3)

    def test_relation_summary_merged_into_relation_rows(self) -> None:
        """relation_summary from the summary repo is merged into each relation row."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel_id = uuid4()
        rel = {
            "relation_id": rel_id,
            "subject_entity_id": _ENT_ID,
            "object_entity_id": _OBJ_ID,
            "canonical_type": "competes_with",
            "confidence": 0.75,
        }
        summaries = {rel_id: "Apple competes directly with Microsoft in cloud services."}

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])
        summary_repo = _make_summary_repo(summaries=summaries)

        _, relation_rows, _ = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=summary_repo,
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert len(relation_rows) == 1
        assert relation_rows[0]["relation_summary"] == "Apple competes directly with Microsoft in cloud services."

    def test_evidence_snippets_empty_when_no_evidence(self) -> None:
        """Relations without evidence get evidence_snippets=[] (never None)."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel = _relation_row()
        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])
        # evidence repo returns empty dict — no snippets for any relation
        evidence_repo = _make_evidence_repo(snippets={})

        _, relation_rows, _ = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert relation_rows[0]["evidence_snippets"] == []

    def test_no_relations_batch_repos_not_called(self) -> None:
        """When no relation rows returned, evidence and summary batch repos are not called."""
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        relation_repo = _make_relation_repo(rows=[])
        evidence_repo = _make_evidence_repo()
        summary_repo = _make_summary_repo()

        asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                summary_repo=summary_repo,
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        evidence_repo.get_evidence_snippets_batch.assert_not_called()
        summary_repo.get_current_summaries_batch.assert_not_called()

    def test_evidence_snippets_default_limit_is_3(self) -> None:
        """Calling execute() without evidence_limit uses the default of 3.

        T-72-2-01: the use case signature declares evidence_limit=3 as the default.
        This test verifies that the default is honoured so that callers who omit
        the parameter do not silently receive an empty evidence window.
        """
        from uuid import uuid4

        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel_id = uuid4()
        rel = {
            "relation_id": rel_id,
            "subject_entity_id": _ENT_ID,
            "object_entity_id": _OBJ_ID,
            "canonical_type": "competes_with",
            "confidence": 0.80,
        }

        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])
        evidence_repo = _make_evidence_repo(snippets={})

        # Deliberately omit evidence_limit so the parameter default (3) takes effect.
        asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
                # evidence_limit NOT passed — default of 3 must be used
            )
        )

        # The evidence repo must have been called with limit_per_relation=3 (the default).
        evidence_repo.get_evidence_snippets_batch.assert_called_once_with([rel_id], limit_per_relation=3)


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


class TestEvidenceBatchDegradation:
    """F-QA-206: graceful degradation when batch fetch raises."""

    def test_evidence_batch_failure_returns_empty_snippets(self) -> None:
        """If get_evidence_snippets_batch raises, response still returns relations with empty snippets.

        The use case wraps the batch call in try/except and falls back to an
        empty map — so every relation gets evidence_snippets=[] rather than a 500.
        """
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel = _relation_row()
        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])

        evidence_repo = AsyncMock()
        evidence_repo.get_evidence_snippets_batch = AsyncMock(side_effect=RuntimeError("db error"))

        _, relation_rows, _ = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=evidence_repo,
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert len(relation_rows) == 1, "Relations must still be returned despite evidence failure"
        assert (
            relation_rows[0]["evidence_snippets"] == []
        ), "evidence_snippets must be [] (empty list, not None) when batch fetch fails"

    def test_summary_batch_failure_returns_null_summaries(self) -> None:
        """If get_current_summaries_batch raises, response still returns relations with null summaries.

        The use case wraps the batch call in try/except and falls back to an
        empty map — so every relation gets relation_summary=None rather than a 500.
        """
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        rel = _relation_row()
        entity_repo = _make_entity_repo(entity=_entity_row(_ENT_ID))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo(rows=[rel])

        summary_repo = AsyncMock()
        summary_repo.get_current_summaries_batch = AsyncMock(side_effect=RuntimeError("db error"))

        _, relation_rows, _ = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=summary_repo,
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert len(relation_rows) == 1, "Relations must still be returned despite summary failure"
        assert relation_rows[0]["relation_summary"] is None, "relation_summary must be None when batch fetch fails"


class TestGetGraphStatsUseCase:
    def test_returns_stats_from_repo(self) -> None:
        """Passes stats dict from repository through unchanged."""
        from knowledge_graph.application.use_cases.graph_query import GetGraphStatsUseCase

        stats = {"relation_count": 150, "entity_count": 42}
        relation_repo = _make_relation_repo(stats=stats)

        result = asyncio.run(GetGraphStatsUseCase().execute(relation_repo=relation_repo))

        assert result == stats
        relation_repo.get_stats.assert_called_once()


class TestGraphQueryGracefulDegradationGaps:
    """F-QA-206 (Wave C-1): graceful-degradation gaps for the entity + relations
    fetch paths.

    Existing tests in `TestEvidenceBatchDegradation` already cover graceful
    degradation for evidence- and summary-batch failures.  These tests document
    the remaining gaps:

      • F-QA-206a: ``entity_repo.get(entity_id)`` failure currently propagates
        (no try/except in GetEntityGraphUseCase line 48).
      • F-QA-206b: ``relation_repo.list_for_entity`` failure currently
        propagates (no try/except in GetEntityGraphUseCase line 52).

    Production code is unchanged in Wave C-1 (test-only wave), so these two
    tests use ``@pytest.mark.xfail`` to document the desired behaviour without
    breaking the suite.  When PLAN-0076 graduates these gaps to a code-fix
    wave, the xfail markers should be removed.

      • F-QA-206c: when the centre entity has zero referenced neighbours
        (i.e. no relations or no edges to other entities), ``get_batch`` is
        not called.  This guards the existing short-circuit at
        graph_query.py:71-77.
    """

    @pytest.mark.xfail(
        reason="F-QA-206a: GetEntityGraphUseCase does not graceful-degrade on "
        "entity_repo.get() failure — desired behaviour, not yet implemented "
        "(test-only wave C-1; code fix tracked separately).",
        strict=True,
    )
    def test_graph_query_entity_fetch_fails_gracefully(self) -> None:
        """``entity_repo.get`` raises → use case should return (None, [], {})
        rather than propagate a 500.

        Until the production code wraps the get() call in try/except, this
        test xfails: the RuntimeError currently propagates out of execute().
        """
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        entity_repo = AsyncMock()
        entity_repo.get = AsyncMock(side_effect=RuntimeError("transient db error"))
        entity_repo.get_batch = AsyncMock(return_value=[])
        relation_repo = _make_relation_repo()

        # Desired behaviour: the use case catches the exception and returns
        # an empty graph response.  Currently this raises.
        entity_row, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert entity_row is None
        assert relation_rows == []
        assert entities_map == {}

    @pytest.mark.xfail(
        reason="F-QA-206b: GetEntityGraphUseCase does not graceful-degrade on "
        "relation_repo.list_for_entity() failure — desired behaviour, not yet "
        "implemented (test-only wave C-1; code fix tracked separately).",
        strict=True,
    )
    def test_graph_query_relations_fetch_fails_gracefully(self) -> None:
        """``relation_repo.list_for_entity`` raises → use case should return
        the entity row with an empty relations list rather than propagate a 500.

        Until the production code wraps list_for_entity in try/except, this
        test xfails: the RuntimeError currently propagates out of execute().
        """
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        center = _entity_row(_ENT_ID)
        entity_repo = _make_entity_repo(entity=center)
        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(side_effect=RuntimeError("transient db error"))

        entity_row, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        # Desired behaviour: entity row preserved, relations empty.
        assert entity_row == center
        assert relation_rows == []
        assert entities_map == {}

    def test_graph_query_no_referenced_entities_skips_get_batch(self) -> None:
        """F-QA-206c: when the centre entity has zero referenced neighbours,
        ``entity_repo.get_batch`` is NOT called.

        This is the existing short-circuit at graph_query.py:72 (``if
        referenced_ids:``).  We exercise it by returning relations whose
        subject and object both equal the centre entity_id, so the
        ``referenced_ids`` set stays empty.
        """
        from knowledge_graph.application.use_cases.graph_query import GetEntityGraphUseCase

        center = _entity_row(_ENT_ID)
        # Self-loop relation: subject==object==centre → referenced_ids = ∅.
        self_loop = _relation_row(subject_id=_ENT_ID, object_id=_ENT_ID)

        entity_repo = _make_entity_repo(entity=center)
        relation_repo = _make_relation_repo(rows=[self_loop])

        entity_row, relation_rows, entities_map = asyncio.run(
            GetEntityGraphUseCase().execute(
                entity_repo=entity_repo,
                relation_repo=relation_repo,
                evidence_repo=_make_evidence_repo(),
                summary_repo=_make_summary_repo(),
                entity_id=_ENT_ID,
                min_confidence=0.0,
                semantic_mode=None,
                limit=50,
            )
        )

        assert entity_row == center
        assert len(relation_rows) == 1
        assert entities_map == {}, "No referenced neighbours → entities_map must be empty"
        # Critical assertion: the short-circuit must skip the batch fetch.
        entity_repo.get_batch.assert_not_called()
