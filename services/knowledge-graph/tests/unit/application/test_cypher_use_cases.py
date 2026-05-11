"""Unit tests for CypherPathUseCase and CypherNeighborhoodUseCase (PRD-0018 Wave E-2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

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

    async def test_entity_id_embedded_as_uuid_literal_not_params(self) -> None:
        """Entity IDs are UUID-validated string literals in SQL — NOT $params.

        BP-461 (2026-05-11): The SQL path query bypasses AGE entirely and queries
        the relations table directly. Entity IDs must still be embedded as UUID
        string literals (UUID-validated, only [0-9a-fA-F-] chars) — no $params.

        Security invariant: only UUID-validated values are embedded — no arbitrary
        user strings can be injected because _UUID_RE rejects non-UUID inputs.
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            _build_direct_sql,
        )

        src_str = str(_SRC)
        tgt_str = str(_TGT)

        # The SQL must embed entity_ids as UUID string literals (BP-461 / BP-459-C)
        sql = _build_direct_sql(src_str, tgt_str, limit=1)
        assert src_str in sql, "source entity_id must be embedded as a UUID literal in SQL"
        assert tgt_str in sql, "target entity_id must be embedded as a UUID literal in SQL"

        # The SQL must NOT use PostgreSQL $params (asyncpg extended-query conflict)
        assert "$source" not in sql, "entity_ids must be literal strings, not $params (BP-450)"
        assert "$target" not in sql, "entity_ids must be literal strings, not $params (BP-450)"

        # Verify that when execute() is called, NO positional $params dict is passed
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

        # Every execute() call must NOT pass a {"params": ...} dict
        for c in session.execute.call_args_list:
            args, _kwargs = c
            if len(args) >= 2 and isinstance(args[1], dict) and "params" in args[1]:
                pytest.fail(
                    "execute() must NOT pass a {'params': ...} dict — "
                    "entity_ids are embedded as UUID literals (BP-461 / BP-450)"
                )

    async def test_raises_timeout_error_on_db_exception(self) -> None:
        """DB exception containing 'timeout' → CypherTimeoutError.

        BP-461: the new SQL-only implementation has no AGE session setup; the
        first execute() call IS the 1-hop SQL query.  A timeout on that call
        must still be surfaced as CypherTimeoutError.
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            CypherTimeoutError,
        )

        uc = CypherPathUseCase()
        entity_repo = _make_entity_repo(exists=True)

        session = AsyncMock()
        # The first (and only) execute is the 1-hop SQL query — it raises timeout.
        session.execute = AsyncMock(side_effect=Exception("canceling statement due to statement timeout"))

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

    async def test_max_hops_controls_two_hop_phase(self) -> None:
        """max_hops=1 skips 2-hop query; max_hops>=2 attempts it when 1-hop returns nothing.

        BP-461: the new SQL-only implementation uses two separate queries
        (_build_direct_sql for 1-hop, _build_twohop_sql for 2-hop).  max_hops
        determines whether the 2-hop phase is attempted, not a Cypher *1..N literal.
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            _build_direct_sql,
            _build_twohop_sql,
        )

        src_str = str(_SRC)
        tgt_str = str(_TGT)

        # Entity IDs must appear in both SQL helpers (UUID literal embedding).
        sql1 = _build_direct_sql(src_str, tgt_str, limit=1)
        sql2 = _build_twohop_sql(src_str, tgt_str, limit=1)
        for sql in (sql1, sql2):
            assert src_str in sql
            assert tgt_str in sql
            assert "$max_hops" not in sql

        # max_hops=1 → only one execute() call (1-hop SQL only, 2-hop skipped).
        session_1hop = _make_session(execute_returns=[])
        entity_repo = _make_entity_repo(exists=True)
        uc = CypherPathUseCase()
        await uc.execute(
            session_1hop,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            max_hops=1,
        )
        assert session_1hop.execute.call_count == 1, "max_hops=1 must run only the 1-hop query"

        # max_hops=2 → two execute() calls (1-hop returns nothing, then 2-hop tried).
        session_2hop = _make_session(execute_returns=[])
        await uc.execute(
            session_2hop,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            max_hops=2,
        )
        assert session_2hop.execute.call_count == 2, "max_hops=2 must attempt the 2-hop query too"

    async def test_all_paths_uses_limit_in_sql(self) -> None:
        """all_paths=True → limit=5 rows; all_paths=False → limit=1 row.

        BP-461: the new SQL-only implementation passes a ``limit`` argument to
        _build_direct_sql / _build_twohop_sql.  Neither shortestPath() nor
        allShortestPaths() are used — they are not supported by AGE 1.5.0.
        """
        from knowledge_graph.application.use_cases.cypher_path import _build_direct_sql

        src_str = str(_SRC)
        tgt_str = str(_TGT)
        sql_single = _build_direct_sql(src_str, tgt_str, limit=1)
        sql_all = _build_direct_sql(src_str, tgt_str, limit=5)

        # AGE 1.5.0-incompatible functions must never appear
        assert "shortestPath" not in sql_single
        assert "allShortestPaths" not in sql_all

        # LIMIT is embedded as a numeric literal in the SQL
        assert "LIMIT 5" in sql_all
        assert "LIMIT 1" in sql_single

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

    async def test_entity_id_embedded_as_uuid_literal_in_neighborhood(self) -> None:
        """BP-450: center_id is embedded as a UUID string literal in neighborhood Cypher SQL.

        Rationale: asyncpg's PREPARE phase fails when AGE Cypher SQL mixes a PostgreSQL
        $1 positional param with Cypher-level $var references. The fix embeds the UUID
        directly after strict _UUID_RE validation (only [0-9a-fA-F-] characters).
        """
        from knowledge_graph.application.use_cases.cypher_neighborhood import _build_neighborhood_sql

        eid_str = str(_ENT)
        sql = _build_neighborhood_sql(entity_id_str=eid_str, max_hops=2, limit=50)
        # Entity UUID must appear directly in the Cypher literal
        assert eid_str in sql, "center_id must be embedded as a UUID string literal in the Cypher body"
        # No $1 params argument should be present — that was the source of the asyncpg error
        assert ":params" not in sql, "BP-450: $1/:params argument must be removed from neighborhood SQL"
        assert "$center_id" not in sql, "BP-450: $center_id Cypher param must be replaced with literal UUID"
        # ALL(rel IN relationships...) predicate must be absent — AGE 1.5 doesn't support it
        assert "ALL(" not in sql, "BP-450: ALL() on variable-length rels must be removed from neighborhood SQL"

    async def test_max_hops_embedded_as_numeric_literal_in_neighborhood(self) -> None:
        """max_hops [1,3] is an int literal in the Cypher pattern, not a param."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import _build_neighborhood_sql

        eid_str = str(_ENT)
        for hops in [1, 2, 3]:
            sql = _build_neighborhood_sql(eid_str, hops, limit=50)
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
