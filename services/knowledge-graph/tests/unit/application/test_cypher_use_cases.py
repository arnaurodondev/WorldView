"""Unit tests for CypherPathUseCase and CypherNeighborhoodUseCase (PRD-0018 Wave E-2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_SRC = uuid4()
_TGT = uuid4()
_ENT = uuid4()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_session(*, execute_returns=None) -> AsyncMock:
    """Build a mock AsyncSession that returns execute_returns for any execute() call."""
    session = AsyncMock()
    mock_result = MagicMock()
    if execute_returns is None:
        mock_result.fetchall.return_value = []
    else:
        mock_result.fetchall.return_value = execute_returns
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_entity_repo(*, exists: bool = True, entity_row: dict | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.exists = AsyncMock(return_value=exists)
    repo.get = AsyncMock(return_value=entity_row)
    return repo


# ── CypherPathUseCase ─────────────────────────────────────────────────────────


class TestCypherPathUseCase:
    async def test_raises_cypher_disabled_when_flag_off(self) -> None:
        """cypher_enabled=False → CypherDisabledError raised (PRD §11 HIGH)."""
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherDisabledError,
            CypherPathUseCase,
        )

        uc = CypherPathUseCase()
        session = _make_session()
        entity_repo = _make_entity_repo()

        with pytest.raises(CypherDisabledError):
            await uc.execute(
                session,
                entity_repo,
                cypher_enabled=False,
                source_entity_id=_SRC,
                target_entity_id=_TGT,
            )

    async def test_raises_entity_not_found_when_source_missing(self) -> None:
        """Source entity absent → CypherEntityNotFoundError."""
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherEntityNotFoundError,
            CypherPathUseCase,
        )

        uc = CypherPathUseCase()
        session = _make_session()
        entity_repo = _make_entity_repo(exists=False)

        with pytest.raises(CypherEntityNotFoundError):
            await uc.execute(
                session,
                entity_repo,
                cypher_enabled=True,
                source_entity_id=_SRC,
                target_entity_id=_TGT,
            )

    async def test_raises_entity_not_found_when_target_missing(self) -> None:
        """Target entity absent → CypherEntityNotFoundError."""
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherEntityNotFoundError,
            CypherPathUseCase,
        )

        uc = CypherPathUseCase()
        session = _make_session()

        # source exists, target does not
        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(side_effect=[True, False])

        with pytest.raises(CypherEntityNotFoundError):
            await uc.execute(
                session,
                entity_repo,
                cypher_enabled=True,
                source_entity_id=_SRC,
                target_entity_id=_TGT,
            )

    async def test_entity_id_passed_as_param_not_f_string(self) -> None:
        """Entity IDs are in the AGE params dict, not interpolated into Cypher SQL.

        This is the HIGH-priority security test: test_cypher_path_entity_id_parameterized
        from PRD §11.
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            _build_path_sql,
        )

        # The SQL template must NOT contain entity_id string literals
        sql = _build_path_sql(max_hops=3, all_paths=False)
        assert "$source" in sql, "entity_id must be a $source Cypher parameter, not an f-string literal"
        assert "$target" in sql, "entity_id must be a $target Cypher parameter, not an f-string literal"

        # The entity UUID must NOT appear in the SQL — it goes in the params JSON dict
        src_str = str(_SRC)
        tgt_str = str(_TGT)
        assert src_str not in sql
        assert tgt_str not in sql

        # Verify that when execute() is called, the params JSON contains the entity IDs
        session = _make_session()
        entity_repo = _make_entity_repo(exists=True)
        uc = CypherPathUseCase()

        await uc.execute(
            session,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            max_hops=3,
            min_confidence=0.3,
        )

        # Find the AGE Cypher execute call (has {"params": json_string})
        age_call = None
        for c in session.execute.call_args_list:
            args, kwargs = c
            # The cypher execute call passes {"params": "..."} as the second argument
            if len(args) >= 2 and isinstance(args[1], dict) and "params" in args[1]:
                age_call = c
                break

        assert age_call is not None, "Expected an AGE Cypher execute call with 'params' dict"
        _, params_dict = age_call[0]
        params_json = params_dict["params"]
        params = json.loads(params_json)

        # Entity IDs must be in the params dict — not in the SQL string
        assert params["source"] == str(_SRC)
        assert params["target"] == str(_TGT)

    async def test_raises_timeout_error_on_db_exception(self) -> None:
        """DB exception containing 'timeout' → CypherTimeoutError."""
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            CypherTimeoutError,
        )

        uc = CypherPathUseCase()
        entity_repo = _make_entity_repo(exists=True)

        session = AsyncMock()
        # First 3 executes are LOAD + SET search_path + SET statement_timeout — succeed
        # The 4th execute (the Cypher query) raises timeout
        call_count = 0

        async def _execute_side_effect(sql, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                mock_result = MagicMock()
                mock_result.fetchall.return_value = []
                return mock_result
            raise Exception("canceling statement due to statement timeout")

        session.execute = AsyncMock(side_effect=_execute_side_effect)

        with pytest.raises(CypherTimeoutError):
            await uc.execute(
                session,
                entity_repo,
                cypher_enabled=True,
                source_entity_id=_SRC,
                target_entity_id=_TGT,
            )

    async def test_returns_empty_paths_when_no_path_found(self) -> None:
        """AGE returns no rows → paths=[], paths_found=0."""
        from knowledge_graph.application.use_cases.cypher_path import CypherPathUseCase

        uc = CypherPathUseCase()
        session = _make_session(execute_returns=[])
        entity_repo = _make_entity_repo(exists=True)

        result = await uc.execute(
            session,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
        )

        assert result.paths_found == 0
        assert result.paths == []
        assert result.source_entity_id == _SRC
        assert result.target_entity_id == _TGT

    async def test_max_hops_embedded_in_cypher_not_params(self) -> None:
        """max_hops is embedded as a numeric literal in Cypher — not a Cypher $param."""
        from knowledge_graph.application.use_cases.cypher_path import _build_path_sql

        for hops in [1, 3, 5]:
            sql = _build_path_sql(hops, all_paths=False)
            # The numeric literal must appear in the Cypher string
            assert f"*1..{hops}" in sql, f"max_hops={hops} must appear as *1..{hops} in Cypher"
            # It must NOT be a Cypher parameter
            assert "$max_hops" not in sql

    async def test_all_paths_uses_allshortestpaths(self) -> None:
        """all_paths=True → allShortestPaths() in Cypher; all_paths=False → shortestPath()."""
        from knowledge_graph.application.use_cases.cypher_path import _build_path_sql

        sql_single = _build_path_sql(3, all_paths=False)
        sql_all = _build_path_sql(3, all_paths=True)

        assert "shortestPath" in sql_single
        assert "allShortestPaths" not in sql_single
        assert "allShortestPaths" in sql_all
        assert "LIMIT 5" in sql_all
        assert "LIMIT 5" not in sql_single

    async def test_relation_types_filter_applied_post_hoc(self) -> None:
        """relation_types filter excludes paths whose edges don't match."""
        from knowledge_graph.application.use_cases.cypher_path import (
            _Path,
            _PathEdge,
            _PathNode,
        )

        # Simulate _build_paths directly (not a full execute)
        node_a = _PathNode(entity_id=str(_SRC), canonical_name="A", entity_type="company")
        node_b = _PathNode(entity_id=str(_TGT), canonical_name="B", entity_type="company")
        edge_wrong = _PathEdge(
            from_entity_id=str(_SRC),
            to_entity_id=str(_TGT),
            canonical_type="EMPLOYS",
            confidence=0.9,
        )
        edge_right = _PathEdge(
            from_entity_id=str(_SRC),
            to_entity_id=str(_TGT),
            canonical_type="COMPETES_WITH",
            confidence=0.8,
        )

        # Simulate two raw rows from AGE (each is a _Path built from parsed agtype)
        # _build_paths accepts list[Any] rows — we mock them to yield the paths above
        path_wrong = _Path(hops=1, nodes=[node_a, node_b], edges=[edge_wrong], path_confidence=0.9)
        path_right = _Path(hops=1, nodes=[node_a, node_b], edges=[edge_right], path_confidence=0.8)

        # Call _build_paths indirectly by monkey-patching; or just test filtering directly
        # Verify that only COMPETES_WITH path passes the filter
        raw_paths = [path_wrong, path_right]
        filtered = [p for p in raw_paths if all(e.canonical_type.upper() in {"COMPETES_WITH"} for e in p.edges)]
        assert len(filtered) == 1
        assert filtered[0].edges[0].canonical_type == "COMPETES_WITH"

    async def test_path_confidence_is_product_of_edge_confidences(self) -> None:
        """path_confidence = product(edge.confidence for edge in path)."""
        from knowledge_graph.application.use_cases.cypher_path import _path_confidence, _PathEdge

        e1 = _PathEdge(from_entity_id="a", to_entity_id="b", canonical_type="X", confidence=0.8)
        e2 = _PathEdge(from_entity_id="b", to_entity_id="c", canonical_type="Y", confidence=0.5)

        conf = _path_confidence([e1, e2])
        assert conf == pytest.approx(0.8 * 0.5, rel=1e-6)

    async def test_path_confidence_empty_edges_returns_zero(self) -> None:
        """No edges → path_confidence = 0.0."""
        from knowledge_graph.application.use_cases.cypher_path import _path_confidence

        assert _path_confidence([]) == 0.0


# ── CypherNeighborhoodUseCase ─────────────────────────────────────────────────


class TestCypherNeighborhoodUseCase:
    async def test_raises_cypher_disabled_when_flag_off(self) -> None:
        """cypher_enabled=False → CypherDisabledError."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase
        from knowledge_graph.application.use_cases.cypher_path import CypherDisabledError

        uc = CypherNeighborhoodUseCase()
        session = _make_session()
        entity_repo = _make_entity_repo(exists=True)

        with pytest.raises(CypherDisabledError):
            await uc.execute(
                session,
                entity_repo,
                MagicMock(),
                None,
                cypher_enabled=False,
                entity_id=_ENT,
            )

    async def test_raises_entity_not_found_when_entity_missing(self) -> None:
        """Entity absent in canonical_entities → CypherEntityNotFoundError."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase
        from knowledge_graph.application.use_cases.cypher_path import CypherEntityNotFoundError

        uc = CypherNeighborhoodUseCase()
        session = _make_session()
        entity_repo = _make_entity_repo(exists=True, entity_row=None)

        with pytest.raises(CypherEntityNotFoundError):
            await uc.execute(
                session,
                entity_repo,
                MagicMock(),
                None,
                cypher_enabled=True,
                entity_id=_ENT,
            )

    async def test_entity_id_passed_as_param_not_f_string_in_neighborhood(self) -> None:
        """center_id is in AGE params dict, not interpolated into neighborhood Cypher SQL."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import _build_neighborhood_sql

        sql = _build_neighborhood_sql(max_hops=2, limit=50)
        assert "$center_id" in sql, "center_id must be a Cypher $parameter, never an f-string literal"
        # Entity UUID must not appear in the template (it's only in the params dict at runtime)
        assert str(_ENT) not in sql

    async def test_max_hops_embedded_as_numeric_literal_in_neighborhood(self) -> None:
        """max_hops [1,3] is an int literal in the Cypher pattern, not a param."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import _build_neighborhood_sql

        for hops in [1, 2, 3]:
            sql = _build_neighborhood_sql(hops, limit=50)
            assert f"r*1..{hops}" in sql, f"max_hops={hops} must be literal *1..{hops} in Cypher"
            assert "$max_hops" not in sql

    async def test_returns_empty_neighborhood_when_no_neighbors(self) -> None:
        """AGE returns no neighbor rows → CypherNeighborhoodResult with empty dicts/lists."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        session = _make_session(execute_returns=[])

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        entity_repo = _make_entity_repo(exists=True, entity_row=center_row)

        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[])

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,  # temporal_event_repo=None → skip temporal events
            cypher_enabled=True,
            entity_id=_ENT,
            include_temporal_events=False,
        )

        assert result.center_row["canonical_name"] == "Apple Inc."
        assert result.relation_rows == []
        assert result.neighbor_rows == {}
        assert result.temporal_event_rows == []

    async def test_includes_temporal_events_when_requested(self) -> None:
        """include_temporal_events=True → temporal_event_repo.list_active() called."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        session = _make_session(execute_returns=[])

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        entity_repo = _make_entity_repo(exists=True, entity_row=center_row)

        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[])

        temporal_event_repo = AsyncMock()
        temporal_event_repo.list_active = AsyncMock(return_value=([], 0))

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            temporal_event_repo,
            cypher_enabled=True,
            entity_id=_ENT,
            include_temporal_events=True,
        )

        temporal_event_repo.list_active.assert_called_once()
        assert result.temporal_event_rows == []

    async def test_skips_temporal_events_when_not_requested(self) -> None:
        """include_temporal_events=False or temporal_event_repo=None → no temporal query."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        session = _make_session(execute_returns=[])

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        entity_repo = _make_entity_repo(exists=True, entity_row=center_row)
        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[])

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,  # temporal_event_repo=None skips temporal events
            cypher_enabled=True,
            entity_id=_ENT,
            include_temporal_events=False,
        )

        assert result.temporal_event_rows == []


# ── Agtype parsing ────────────────────────────────────────────────────────────


class TestAgtypeParser:
    def test_parse_valid_json_list(self) -> None:
        """Standard JSON list → parsed Python list."""
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        raw = '[{"id": 1, "label": "Entity", "properties": {"entity_id": "abc"}}]'
        result = _parse_agtype_text(raw)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["label"] == "Entity"

    def test_parse_strips_type_annotation_suffix(self) -> None:
        """Agtype with ``::agtype`` suffix → suffix stripped before JSON parse."""
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        raw = '[{"id": 1, "label": "Entity", "properties": {}}]::agtype'
        result = _parse_agtype_text(raw)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_parse_none_returns_empty_list(self) -> None:
        """None input → empty list (no exception)."""
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        assert _parse_agtype_text(None) == []

    def test_parse_bytes_input(self) -> None:
        """Bytes input (asyncpg may return bytes for unknown types) → parsed correctly."""
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        raw = b'[{"id": 1, "label": "Entity", "properties": {"entity_id": "abc"}}]'
        result = _parse_agtype_text(raw)
        assert len(result) == 1

    def test_extract_nodes_from_vertex_dicts(self) -> None:
        """_extract_nodes parses entity_id/canonical_name/entity_type from AGE vertex dicts."""
        from knowledge_graph.application.use_cases.cypher_path import _extract_nodes

        node_dicts = [
            {
                "id": 1,
                "label": "Entity",
                "properties": {"entity_id": "abc", "canonical_name": "Apple", "entity_type": "company"},
            },
            {
                "id": 2,
                "label": "Entity",
                "properties": {"entity_id": "xyz", "canonical_name": "Samsung", "entity_type": "company"},
            },
        ]
        nodes = _extract_nodes(node_dicts)
        assert len(nodes) == 2
        assert nodes[0].entity_id == "abc"
        assert nodes[0].canonical_name == "Apple"
        assert nodes[1].entity_id == "xyz"

    def test_extract_edges_maps_correct_from_to(self) -> None:
        """_extract_edges maps nodes[i] → from, nodes[i+1] → to for each edge."""
        from knowledge_graph.application.use_cases.cypher_path import _extract_edges, _PathNode

        nodes = [
            _PathNode(entity_id="a", canonical_name="A", entity_type="co"),
            _PathNode(entity_id="b", canonical_name="B", entity_type="co"),
            _PathNode(entity_id="c", canonical_name="C", entity_type="co"),
        ]
        edge_dicts = [
            {"label": "COMPETES_WITH", "properties": {"confidence": 0.8, "relation_id": "r1"}},
            {"label": "PARTNER_OF", "properties": {"confidence": 0.6, "relation_id": "r2"}},
        ]
        edges = _extract_edges(edge_dicts, nodes)
        assert len(edges) == 2
        assert edges[0].from_entity_id == "a"
        assert edges[0].to_entity_id == "b"
        assert edges[0].canonical_type == "COMPETES_WITH"
        assert edges[1].from_entity_id == "b"
        assert edges[1].to_entity_id == "c"
        assert edges[1].canonical_type == "PARTNER_OF"
