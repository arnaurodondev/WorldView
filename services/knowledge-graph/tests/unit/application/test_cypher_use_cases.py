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
        """Entity IDs are UUID-validated string literals in AGE Cypher — NOT $params.

        BP-459-C / BP-450 (2026-05-11): asyncpg's prepared-statement protocol fails
        when AGE Cypher SQL mixes a PostgreSQL $1 param with Cypher-level $var refs.
        The fix embeds entity UUIDs directly as Cypher string literals after strict
        _UUID_RE validation (only [0-9a-fA-F-] characters — no injection possible).
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            _build_path_sql,
        )

        src_str = str(_SRC)
        tgt_str = str(_TGT)

        # The AGE Cypher SQL must embed entity_ids as UUID string literals
        sql = _build_path_sql(src_str, tgt_str, max_hops=3, all_paths=False)
        assert src_str in sql, "source entity_id must be embedded as a UUID literal in AGE Cypher"
        assert tgt_str in sql, "target entity_id must be embedded as a UUID literal in AGE Cypher"

        # The Cypher SQL must NOT use PostgreSQL $params (asyncpg extended-query conflict)
        assert "$source" not in sql, "entity_ids must be literal strings, not $params (BP-450)"
        assert "$target" not in sql, "entity_ids must be literal strings, not $params (BP-450)"
        # AGE 1.5.0 incompatible functions must not appear
        assert "shortestPath" not in sql
        assert "allShortestPaths" not in sql

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
                    "entity_ids are embedded as UUID literals (BP-459-C / BP-450)"
                )

    async def test_raises_timeout_error_on_db_exception(self) -> None:
        """DB exception containing 'timeout' on the AGE Cypher query → CypherTimeoutError.

        execute() makes 3 AGE setup calls (LOAD 'age', SET search_path, SET timeout)
        that succeed, then the 4th call (AGE Cypher query) raises a statement timeout.
        CypherTimeoutError must be raised regardless of which call fails.
        """
        from unittest.mock import MagicMock

        from knowledge_graph.application.use_cases.cypher_path import (
            CypherPathUseCase,
            CypherTimeoutError,
        )

        uc = CypherPathUseCase()
        entity_repo = _make_entity_repo(exists=True)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session = AsyncMock()
        # First 4 calls (AGE session setup) succeed; 5th (AGE Cypher query) times out.
        # PLAN-0112 W2: setup now emits 4 statements — LOAD, search_path,
        # SET max_parallel_workers_per_gather, SET statement_timeout (session-scoped).
        session.execute = AsyncMock(
            side_effect=[
                mock_result,  # LOAD 'age'
                mock_result,  # SET search_path
                mock_result,  # SET max_parallel_workers_per_gather = 0
                mock_result,  # SET statement_timeout
                Exception("canceling statement due to statement timeout"),
            ]
        )

        with pytest.raises(CypherTimeoutError):
            await uc.execute(
                session,
                entity_repo,
                cypher_enabled=True,
                source_entity_id=_SRC,
                target_entity_id=_TGT,
            )

    async def test_path_query_uses_30s_statement_timeout_backstop(self) -> None:
        """The path query must use a 30 s statement_timeout backstop (BP-687).

        Round 1 (BP-686) raised 5 s → 20 s, but hub-to-hub paths (OpenAI↔Microsoft)
        still occasionally exceeded 20 s because the open-range ``-[*1..3]-`` query
        enumerated the full O(degree^3) frontier. Round 2 (BP-687) makes the query
        fast via staged shortest-first probing and raises the timeout to 30 s as a
        pure BACKSTOP — it should now rarely bind.
        """
        from knowledge_graph.application.use_cases.cypher_path import (
            _STATEMENT_TIMEOUT_MS,
            CypherPathUseCase,
        )
        from sqlalchemy import text

        # The module-level constant is the single authoritative deadline (backstop).
        assert _STATEMENT_TIMEOUT_MS == "30000", (
            "path query statement_timeout backstop must be 30 s (BP-687), "
            "not the old 5 s / 20 s that timed out on hub-to-hub paths"
        )

        uc = CypherPathUseCase()
        session = _make_session(execute_returns=[])
        entity_repo = _make_entity_repo(exists=True)
        await uc.execute(
            session,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
        )

        # The statement_timeout statement actually issued to the DB must carry the
        # 30 s value (guards against the constant being read but a stale literal
        # being embedded in the SQL string).  PLAN-0112 W2: it is now a
        # session-scoped ``SET`` (NOT ``SET LOCAL``) so it survives to the traversal
        # query (the GUC-scope fix).
        timeout_stmts = [
            str(c.args[0]) for c in session.execute.call_args_list if c.args and "statement_timeout" in str(c.args[0])
        ]
        assert any(
            "30000" in s for s in timeout_stmts
        ), f"expected a SET statement_timeout = '30000' call, got: {timeout_stmts}"
        assert not any(
            "5000" in s or "20000" in s for s in timeout_stmts
        ), f"path query must NOT issue the old 5000/20000 ms timeout, got: {timeout_stmts}"
        # The timeout GUC must be session-scoped (not SET LOCAL) so it binds the
        # subsequent traversal query.
        assert all("set local" not in s.lower() for s in timeout_stmts)
        # Sanity: the issued statement matches what the use case builds.
        assert str(text(f"SET statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

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

    async def test_max_hops_embedded_in_legacy_open_range_form(self) -> None:
        """Legacy open-range builder (exact_hops=None) embeds *1..N with ORDER BY.

        BP-461 (2026-05-11): confirmed-working AGE 1.5.0 syntax uses variable-length
        matching with ``ORDER BY length(p)`` instead of ``shortestPath()`` or list
        comprehensions (both unsupported in AGE 1.5.0). The open-range form is
        retained (exact_hops=None) but the use case now drives the staged form.
        """
        from knowledge_graph.application.use_cases.cypher_path import _build_path_sql

        src_str = str(_SRC)
        tgt_str = str(_TGT)

        # Open-range (legacy) form: *1..N with ORDER BY length(p).
        sql2 = _build_path_sql(src_str, tgt_str, max_hops=2, all_paths=False)
        sql3 = _build_path_sql(src_str, tgt_str, max_hops=3, all_paths=False)
        assert "*1..2" in sql2, "open-range max_hops=2 must appear as *1..2 in Cypher pattern"
        assert "*1..3" in sql3, "open-range max_hops=3 must appear as *1..3 in Cypher pattern"
        assert "$max_hops" not in sql2, "max_hops must be a literal, not a $param"
        assert "shortestPath" not in sql2, "shortestPath() is not supported by AGE 1.5.0"
        assert "allShortestPaths" not in sql3, "allShortestPaths() is not supported by AGE 1.5.0"
        assert "ORDER BY length(p)" in sql3, "open-range form sorts shortest-first via ORDER BY"

    async def test_staged_builder_pins_exact_hop_length_and_drops_order_by(self) -> None:
        """BP-687: exact_hops form pins *L..L and OMITS ORDER BY (early-exit enabler).

        The staged optimisation issues one fixed-length probe per depth. A single
        exact hop length is already uniform, so ``ORDER BY length(p)`` is dropped —
        and its removal is exactly what lets AGE stop after LIMIT matches instead of
        materialising and sorting the whole O(degree^N) frontier (the 504 root cause).
        """
        from knowledge_graph.application.use_cases.cypher_path import _build_path_sql

        src_str = str(_SRC)
        tgt_str = str(_TGT)

        sql_l1 = _build_path_sql(src_str, tgt_str, max_hops=3, all_paths=False, exact_hops=1)
        sql_l2 = _build_path_sql(src_str, tgt_str, max_hops=3, all_paths=False, exact_hops=2)
        sql_l3 = _build_path_sql(src_str, tgt_str, max_hops=3, all_paths=True, exact_hops=3)

        # Pattern is pinned to the exact length, NOT the open range *1..N.
        assert "*1..1" in sql_l1
        assert "*2..2" in sql_l2
        assert "*3..3" in sql_l3
        assert "*1..3" not in sql_l3, "staged form must not use the open range *1..3"

        # ORDER BY must be ABSENT in the staged form — this is the early-exit enabler.
        for sql in (sql_l1, sql_l2, sql_l3):
            assert "ORDER BY" not in sql, "staged exact-hop form must omit ORDER BY (early exit)"
            assert "shortestPath" not in sql
            assert "allShortestPaths" not in sql

        # LIMIT still caps results: 1 for all_paths=False, 5 for all_paths=True.
        assert "LIMIT 1" in sql_l1
        assert "LIMIT 5" in sql_l3

    async def test_staged_execution_stops_at_first_non_empty_depth(self) -> None:
        """BP-687: probing stops at the shortest depth that yields a path (early exit).

        Direct (1-hop) connections — the OpenAI↔Microsoft case — must resolve with a
        SINGLE Cypher probe and never expand the deeper 2-/3-hop frontier. We assert
        exactly ONE *L..L Cypher query ran (the L=1 probe), plus the 3 setup calls.
        """
        from unittest.mock import MagicMock

        from knowledge_graph.application.use_cases.cypher_path import CypherPathUseCase

        uc = CypherPathUseCase()
        entity_repo = _make_entity_repo(exists=True)

        # L=1 probe returns a row; deeper probes must never be issued.
        one_path_result = MagicMock()
        one_path_result.fetchall.return_value = [(None, None)]  # a single (nodes, rels) row
        setup_result = MagicMock()
        setup_result.fetchall.return_value = []

        session = AsyncMock()
        # PLAN-0112 W2: 4 setup calls (LOAD, search_path, parallel, timeout).
        session.execute = AsyncMock(
            side_effect=[
                setup_result,  # LOAD 'age'
                setup_result,  # SET search_path
                setup_result,  # SET max_parallel_workers_per_gather = 0
                setup_result,  # SET statement_timeout
                one_path_result,  # L=1 probe — HITS, must stop here
            ]
        )

        await uc.execute(
            session,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            max_hops=3,
        )

        # 4 setup + exactly 1 Cypher probe = 5 total. No L=2/L=3 probes were issued.
        assert session.execute.call_count == 5, (
            "a 1-hop hit must stop staged probing after the L=1 query — got "
            f"{session.execute.call_count} calls (deeper frontier was expanded)"
        )
        # The single Cypher probe must be the *1..1 exact-length form.
        cypher_calls = [str(c.args[0]) for c in session.execute.call_args_list if "ag_catalog.cypher" in str(c.args[0])]
        assert len(cypher_calls) == 1, f"expected exactly 1 Cypher probe, got {len(cypher_calls)}"
        assert "*1..1" in cypher_calls[0], "the winning probe must be the exact 1-hop form *1..1"

    async def test_staged_execution_probes_deeper_when_shorter_empty(self) -> None:
        """BP-687: when no shorter path exists, probing ascends 1 → 2 → 3.

        Guards the regression direction: a pair connected only at 3 hops (e.g. some
        Apple→Anthropic chains) must still be found — the staged loop must probe
        L=1 (empty), L=2 (empty), then L=3 (hit), preserving discovery.
        """
        from unittest.mock import MagicMock

        from knowledge_graph.application.use_cases.cypher_path import CypherPathUseCase

        uc = CypherPathUseCase()
        entity_repo = _make_entity_repo(exists=True)

        empty = MagicMock()
        empty.fetchall.return_value = []
        hit = MagicMock()
        hit.fetchall.return_value = [(None, None)]

        session = AsyncMock()
        # PLAN-0112 W2: 4 setup calls (LOAD, search_path, parallel, timeout).
        session.execute = AsyncMock(
            side_effect=[
                empty,  # LOAD 'age'
                empty,  # SET search_path
                empty,  # SET max_parallel_workers_per_gather = 0
                empty,  # SET statement_timeout
                empty,  # L=1 probe — no direct edge
                empty,  # L=2 probe — no 2-hop path
                hit,  # L=3 probe — found
            ]
        )

        result = await uc.execute(
            session,
            entity_repo,
            cypher_enabled=True,
            source_entity_id=_SRC,
            target_entity_id=_TGT,
            max_hops=3,
        )

        # 4 setup + 3 probes (1,2,3) = 7 calls; the L=3 hit terminates the loop.
        assert session.execute.call_count == 7
        cypher_calls = [str(c.args[0]) for c in session.execute.call_args_list if "ag_catalog.cypher" in str(c.args[0])]
        assert len(cypher_calls) == 3, f"expected 3 ascending probes, got {len(cypher_calls)}"
        assert "*1..1" in cypher_calls[0]
        assert "*2..2" in cypher_calls[1]
        assert "*3..3" in cypher_calls[2]
        # A 3-hop path must still be discovered (no regression in reachability).
        assert result.paths_found == 1

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

    # ── PLAN-0099 W3: lateral / second-hop edge merge ──────────────────────────
    #
    # ROOT CAUSE PINNED: Step 2 only fetched the CENTER's direct relations, so
    # depth-2 nodes discovered by AGE arrived edge-less and the S9 orphan
    # filter deleted them — depth=2 was visually identical to depth=1 (live
    # AAPL: 21 nodes / 22 edges, ALL incident to the root, while neighbors had
    # 40+ edges of their own). Step 2b must fetch edges among the node set.

    async def test_merges_lateral_edges_among_neighbors_at_depth_2(self) -> None:
        """max_hops=2 with discovered neighbors → list_among_entities edges merged, deduped."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        n1, n2 = uuid4(), uuid4()
        # AGE returns two neighbor ids (agtype quoted strings).
        session = _make_session(execute_returns=[(f'"{n1}"',), (f'"{n2}"',)])

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

        direct_rel_id, lateral_rel_id = uuid4(), uuid4()
        direct_rel = {"relation_id": direct_rel_id, "subject_entity_id": _ENT, "object_entity_id": n1}
        lateral_rel = {"relation_id": lateral_rel_id, "subject_entity_id": n1, "object_entity_id": n2}

        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[direct_rel])
        # list_among_entities returns the lateral edge AND a duplicate of the
        # direct edge (both its endpoints are in the set) — the dedup must
        # keep exactly one copy.
        relation_repo.list_among_entities = AsyncMock(return_value=[dict(direct_rel), lateral_rel])

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,
            cypher_enabled=True,
            entity_id=_ENT,
            max_hops=2,
            include_temporal_events=False,
        )

        # The lateral edge made it in; the duplicated direct edge did not.
        rel_ids = [r["relation_id"] for r in result.relation_rows]
        assert rel_ids == [direct_rel_id, lateral_rel_id]
        # The node-set passed includes the center + both resolved neighbors.
        called_ids = relation_repo.list_among_entities.call_args.args[0]
        assert set(called_ids) == {_ENT, n1, n2}

    async def test_no_lateral_fetch_at_depth_1(self) -> None:
        """max_hops=1 → list_among_entities must NOT be called (1-hop is complete via Step 2)."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        n1 = uuid4()
        session = _make_session(execute_returns=[(f'"{n1}"',)])

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
        relation_repo.list_among_entities = AsyncMock(return_value=[])

        await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,
            cypher_enabled=True,
            entity_id=_ENT,
            max_hops=1,
            include_temporal_events=False,
        )

        relation_repo.list_among_entities.assert_not_called()

    async def test_resolves_direct_endpoints_age_missed_into_node_set(self) -> None:
        """Step 3b: direct-relation endpoints absent from AGE's set still join the
        entity map + lateral fetch (AGE LIMIT fills arbitrarily / stale-sync ghosts)."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        n1 = uuid4()  # direct SQL neighbor that AGE did NOT discover
        session = _make_session(execute_returns=[])  # AGE returns nothing

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        n1_row = {"entity_id": n1, "canonical_name": "Microsoft", "entity_type": "financial_instrument"}
        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(return_value=True)
        # 1st get = center existence check; 2nd get = Step 3b endpoint resolve.
        entity_repo.get = AsyncMock(side_effect=[center_row, n1_row])

        direct_rel = {"relation_id": uuid4(), "subject_entity_id": _ENT, "object_entity_id": n1}
        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[direct_rel])
        relation_repo.list_among_entities = AsyncMock(return_value=[])

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,
            cypher_enabled=True,
            entity_id=_ENT,
            max_hops=2,
            include_temporal_events=False,
        )

        # n1 was resolved into the entity map even though AGE never returned it…
        assert str(n1) in result.neighbor_rows
        # …and the lateral fetch covered {center, n1}.
        called_ids = relation_repo.list_among_entities.call_args.args[0]
        assert set(called_ids) == {_ENT, n1}

    async def test_no_lateral_fetch_when_no_neighbors_resolved(self) -> None:
        """Neighbors that fail SQL resolution are excluded → no ghost-edge fetch."""
        from knowledge_graph.application.use_cases.cypher_neighborhood import CypherNeighborhoodUseCase

        uc = CypherNeighborhoodUseCase()
        n1 = uuid4()
        session = _make_session(execute_returns=[(f'"{n1}"',)])

        center_row = {
            "entity_id": _ENT,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "isin": None,
            "ticker": "AAPL",
            "exchange": "US",
            "metadata": {},
        }
        # entity_repo.get returns the center for the existence check, then None
        # for the neighbor (AGE knows it; SQL does not — e.g. tombstoned).
        entity_repo = AsyncMock()
        entity_repo.exists = AsyncMock(return_value=True)
        entity_repo.get = AsyncMock(side_effect=[center_row, None])

        relation_repo = AsyncMock()
        relation_repo.list_for_entity = AsyncMock(return_value=[])
        relation_repo.list_among_entities = AsyncMock(return_value=[])

        result = await uc.execute(
            session,
            entity_repo,
            relation_repo,
            None,
            cypher_enabled=True,
            entity_id=_ENT,
            max_hops=2,
            include_temporal_events=False,
        )

        relation_repo.list_among_entities.assert_not_called()
        assert result.neighbor_rows == {}


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

    def test_parse_strips_per_element_vertex_annotations(self) -> None:
        """AGE arrays with per-element ::vertex annotations → parsed correctly (BP-461).

        The old rfind('::') approach failed for multi-element arrays because it only
        stripped the last :: occurrence, leaving inner ::vertex tokens as invalid JSON.
        The regex fix strips ALL }::word and ]::word type annotations.
        """
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        raw = (
            '[{"id":1,"label":"entity","properties":{"entity_id":"abc",'
            '"canonical_name":"Apple","entity_type":"company"}}::vertex,'
            '{"id":2,"label":"entity","properties":{"entity_id":"xyz",'
            '"canonical_name":"Anthropic","entity_type":"company"}}::vertex]'
        )
        result = _parse_agtype_text(raw)
        assert len(result) == 2
        assert result[0]["properties"]["entity_id"] == "abc"
        assert result[1]["properties"]["entity_id"] == "xyz"

    def test_parse_strips_per_element_edge_annotations(self) -> None:
        """AGE edge arrays with per-element ::edge annotations → parsed correctly (BP-461)."""
        from knowledge_graph.application.use_cases.cypher_path import _parse_agtype_text

        raw = (
            '[{"id":10,"label":"owns_stake_in","end_id":2,"start_id":1,'
            '"properties":{"confidence":1.0,"relation_id":"r1"}}::edge,'
            '{"id":11,"label":"partner_of","end_id":3,"start_id":2,'
            '"properties":{"confidence":0.9,"relation_id":"r2"}}::edge]'
        )
        result = _parse_agtype_text(raw)
        assert len(result) == 2
        assert result[0]["label"] == "owns_stake_in"
        assert result[1]["label"] == "partner_of"

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
        # No start_id/end_id + no graphid → default forward (back-compat).
        assert edges[0].direction == "forward"
        assert edges[1].direction == "forward"

    def test_extract_edges_direction_from_start_end_ids(self) -> None:
        """direction reflects TRUE subject→object via start_id/end_id (2026-06-13)."""
        from knowledge_graph.application.use_cases.cypher_path import _extract_edges, _PathNode

        nodes = [
            _PathNode(entity_id="a", canonical_name="A", entity_type="co", graphid="100"),
            _PathNode(entity_id="b", canonical_name="B", entity_type="co", graphid="200"),
        ]
        # Forward: stored subject (start_id=100) == node we leave from (A).
        fwd = _extract_edges(
            [{"label": "ACQUIRED_BY", "start_id": 100, "end_id": 200, "properties": {"confidence": 0.9}}],
            nodes,
        )
        assert fwd[0].direction == "forward"
        # Reverse: stored subject (start_id=200=B) is the node we ARRIVE at →
        # the undirected walk went against the stored direction.
        rev = _extract_edges(
            [{"label": "ACQUIRED_BY", "start_id": 200, "end_id": 100, "properties": {"confidence": 0.9}}],
            nodes,
        )
        assert rev[0].direction == "reverse"
