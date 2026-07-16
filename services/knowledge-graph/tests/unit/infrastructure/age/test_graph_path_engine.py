"""Unit tests for AgeGraphPathEngine (PLAN-0112 W2, T-2-02).

Covers the BP-689 VLE-not-explicit guard, membership pruning (FR-3), the staged
shortest-first probing (BP-687), rel_id parsing, and — critically — that the
Postgres-hygiene GUCs (statement_timeout + max_parallel_workers_per_gather) are
emitted on the SAME session/connection that runs the traversal query, using
session-scoped ``SET`` (not ``SET LOCAL``) so they actually constrain the query.
"""

from __future__ import annotations

import asyncio
import json
import re
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


# ── agtype row fixtures ────────────────────────────────────────────────────────


def _vertex(entity_id: str, name: str, etype: str = "company") -> dict:
    return {
        "id": abs(hash(entity_id)) % (10**9),
        "label": "entity",
        "properties": {"entity_id": entity_id, "canonical_name": name, "entity_type": etype},
    }


def _vertex_graphid(entity_id: str) -> int:
    """The AGE graphid ``_vertex`` assigns for a given entity_id (kept in sync)."""
    return abs(hash(entity_id)) % (10**9)


def _edge(label: str, conf: float, relation_id: str | None = None) -> dict:
    props: dict = {"confidence": conf}
    if relation_id is not None:
        props["relation_id"] = relation_id
    return {"id": 1, "label": label, "properties": props}


def _directed_edge(
    label: str,
    conf: float,
    *,
    subject_entity_id: str,
    object_entity_id: str,
    relation_id: str | None = None,
) -> dict:
    """An edge agtype carrying its true stored direction via start_id/end_id.

    ``start_id`` = subject vertex graphid, ``end_id`` = object vertex graphid —
    exactly what AGE returns from ``relationships(p)`` (see the directionality
    investigation, 2026-06-13).  The graphids are derived the same way ``_vertex``
    assigns them so the parser can match an edge endpoint to a path node.
    """
    props: dict = {"confidence": conf}
    if relation_id is not None:
        props["relation_id"] = relation_id
    return {
        "id": 1,
        "label": label,
        "start_id": _vertex_graphid(subject_entity_id),
        "end_id": _vertex_graphid(object_entity_id),
        "properties": props,
    }


def _agtype_nodes(*vertices: dict) -> str:
    """Render an agtype nodes array with ::vertex annotations (as AGE returns)."""
    return ", ".join(f"{json.dumps(v)}::vertex" for v in vertices).join(["[", "]"])


def _agtype_edges(*edges: dict) -> str:
    return ", ".join(f"{json.dumps(e)}::edge" for e in edges).join(["[", "]"])


_DEPTH_RE = re.compile(r"\*(\d+)\.\.\1")


def _make_session(*, rows_per_depth: list[list[tuple]] | None = None) -> tuple[MagicMock, MagicMock]:
    """Build a mock session that records execute() SQL and returns staged rows.

    ``rows_per_depth[i]`` is the fetchall() result for the **(i+1)-hop** query —
    keyed by the actual ``*N..N`` hop depth parsed from the SQL, NOT by call
    order.  This matters because anchor discovery skips depth 1 (min_hops=2): a
    depth-1 fixture must never be served to a depth-2 query.  The four AGE setup
    statements (LOAD/search_path/parallel/timeout) return a bare MagicMock.
    """
    rows_per_depth = rows_per_depth or [[]]
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    executed_sql: list[str] = []

    async def _execute(stmt: object, *args: object, **kwargs: object) -> MagicMock:
        sql = str(stmt)
        executed_sql.append(sql)
        result = MagicMock()
        # Traversal queries are the ones selecting nodes_col/rels_col.
        if "nodes_col" in sql and "cypher" in sql:
            match = _DEPTH_RE.search(sql)
            depth = int(match.group(1)) if match else 0
            idx = depth - 1
            rows = rows_per_depth[idx] if 0 <= idx < len(rows_per_depth) else []
            result.fetchall.return_value = rows
        else:
            result.fetchall.return_value = []
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session._executed_sql = executed_sql  # type: ignore[attr-defined]
    return session, session


def _make_factory(session: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


# ── tests ──────────────────────────────────────────────────────────────────────


class TestVleNotExplicit:
    def test_engine_emits_vle_never_explicit_edges(self) -> None:
        """BP-689 guard: traversal uses a ``*`` VLE, never the explicit per-hop form.

        AGE 1.5 cannot express a multi-label VLE (``-[:A|B*L..L]-`` is a parse
        error) nor ``ALL(r IN relationships(p) WHERE …)``; the only fast,
        AGE-compatible primitive is the UNTYPED VLE ``-[*L..L]-`` (the explicit
        ``-[r1]-(n1)-[r2]-`` form is the 18 s seq-scan we retired).
        """
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        session, _ = _make_session(rows_per_depth=[[], [], []])
        engine = AgeGraphPathEngine(_make_factory(session))
        asyncio.run(
            engine.find_paths_from_anchor(uuid4(), max_hops=3, prune_membership=True, limit=10),
        )

        traversal_sqls = [s for s in session._executed_sql if "nodes_col" in s and "cypher" in s]
        assert traversal_sqls, "expected at least one traversal query"
        for sql in traversal_sqls:
            # VLE: ``-[*L..L]-`` — must contain a ``*`` variable-length pattern.
            assert "[*" in sql, f"expected an untyped VLE pattern in: {sql}"
            # Never the explicit per-hop edge form (BP-689) …
            assert "[r1]" not in sql and "[r2]" not in sql
            # … and never the multi-label VLE syntax AGE 1.5 rejects.
            assert "|" not in sql

    def test_membership_pruned_post_hoc(self) -> None:
        """A discovered path containing a membership relation is dropped (FR-3)."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, mid, b = str(uuid4()), str(uuid4()), str(uuid4())
        # 2-hop path whose first edge is a membership relation → must be pruned.
        membership_path = (
            _agtype_nodes(_vertex(a, "A"), _vertex(mid, "Sector"), _vertex(b, "B")),
            _agtype_edges(_edge("IS_IN_SECTOR", 0.9), _edge("IS_IN_SECTOR", 0.8)),
        )
        # A clean non-membership 2-hop path → kept.
        clean = (
            _agtype_nodes(_vertex(a, "A"), _vertex(str(uuid4()), "M"), _vertex(str(uuid4()), "C")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("SUPPLIER_OF", 0.8)),
        )
        # Fixtures are keyed by hop depth: index 1 == the 2-hop query.  Anchor
        # discovery (min_hops=2) issues only the depth-2 probe, which returns both.
        session, _ = _make_session(rows_per_depth=[[], [membership_path, clean]])
        engine = AgeGraphPathEngine(_make_factory(session))
        paths = asyncio.run(
            engine.find_paths_from_anchor(__import__("uuid").UUID(a), max_hops=2, prune_membership=True, limit=10),
        )
        # Only the clean path survives.
        assert len(paths) == 1
        assert "IS_IN_SECTOR" not in paths[0].rel_types

    def test_membership_kept_when_not_pruning(self) -> None:
        """With prune_membership=False, membership paths are retained."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, mid, b = str(uuid4()), str(uuid4()), str(uuid4())
        membership_path = (
            _agtype_nodes(_vertex(a, "A"), _vertex(mid, "Sector"), _vertex(b, "B")),
            _agtype_edges(_edge("IS_IN_SECTOR", 0.9), _edge("IS_IN_SECTOR", 0.8)),
        )
        # Index 1 == the depth-2 query (anchor discovery starts at depth 2).
        session, _ = _make_session(rows_per_depth=[[], [membership_path]])
        engine = AgeGraphPathEngine(_make_factory(session))
        paths = asyncio.run(
            engine.find_paths_from_anchor(__import__("uuid").UUID(a), max_hops=2, prune_membership=False, limit=10),
        )
        assert len(paths) == 1
        assert "IS_IN_SECTOR" in paths[0].rel_types


class TestStagedProbe:
    def test_pairwise_accumulates_across_depths(self) -> None:
        """Pairwise (W4 refinement): accumulate distinct paths ACROSS depths.

        "How are A and B connected?" should surface the VARIETY of routes — not
        just the single shortest one.  With fewer paths at the shortest depth
        than ``limit``, the engine continues to deeper depths (within max_hops)
        for alternative routes, preserving shortest-first ordering.
        """
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        src, tgt = str(uuid4()), str(uuid4())
        # One direct (1-hop) route, two distinct 2-hop routes, one 3-hop route.
        one_hop = (_agtype_nodes(_vertex(src, "A"), _vertex(tgt, "B")), _agtype_edges(_edge("PARTNER_OF", 0.9)))
        two_hop_a = (
            _agtype_nodes(_vertex(src, "A"), _vertex(str(uuid4()), "M1"), _vertex(tgt, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("SUPPLIER_OF", 0.8)),
        )
        two_hop_b = (
            _agtype_nodes(_vertex(src, "A"), _vertex(str(uuid4()), "M2"), _vertex(tgt, "B")),
            _agtype_edges(_edge("COMPETITOR_OF", 0.7), _edge("PARTNER_OF", 0.6)),
        )
        three_hop = (
            _agtype_nodes(_vertex(src, "A"), _vertex(str(uuid4()), "X"), _vertex(str(uuid4()), "Y"), _vertex(tgt, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("PARTNER_OF", 0.8), _edge("PARTNER_OF", 0.7)),
        )
        session, _ = _make_session(rows_per_depth=[[one_hop], [two_hop_a, two_hop_b], [three_hop]])
        engine = AgeGraphPathEngine(_make_factory(session))

        paths = asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(src),
                __import__("uuid").UUID(tgt),
                max_hops=3,
                prune_membership=False,
                limit=5,
            ),
        )
        # All four distinct routes are returned (limit not reached).
        assert len(paths) == 4
        # Shortest-first ordering preserved (1, 2, 2, 3).
        assert [p.hop_count for p in paths] == [1, 2, 2, 3]
        # All three depths were probed (no early-stop).
        traversal_sqls = [s for s in session._executed_sql if "nodes_col" in s and "cypher" in s]
        assert len(traversal_sqls) == 3
        assert any("*1..1" in s for s in traversal_sqls)
        assert any("*2..2" in s for s in traversal_sqls)
        assert any("*3..3" in s for s in traversal_sqls)
        # No ORDER BY length(p) (the BP-687 anti-pattern) on any probe.
        for sql in traversal_sqls:
            assert "order by length" not in sql.lower()

    def test_pairwise_respects_limit_across_depths(self) -> None:
        """Accumulation stops once ``limit`` distinct paths are collected."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        src, tgt = str(uuid4()), str(uuid4())
        # Three 1-hop+2-hop candidates but limit=2 → only the first two (shortest).
        one_hop = (_agtype_nodes(_vertex(src, "A"), _vertex(tgt, "B")), _agtype_edges(_edge("PARTNER_OF", 0.9)))
        two_hop_a = (
            _agtype_nodes(_vertex(src, "A"), _vertex(str(uuid4()), "M1"), _vertex(tgt, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("SUPPLIER_OF", 0.8)),
        )
        two_hop_b = (
            _agtype_nodes(_vertex(src, "A"), _vertex(str(uuid4()), "M2"), _vertex(tgt, "B")),
            _agtype_edges(_edge("COMPETITOR_OF", 0.7), _edge("PARTNER_OF", 0.6)),
        )
        session, _ = _make_session(rows_per_depth=[[one_hop], [two_hop_a, two_hop_b], []])
        engine = AgeGraphPathEngine(_make_factory(session))

        paths = asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(src),
                __import__("uuid").UUID(tgt),
                max_hops=3,
                prune_membership=False,
                limit=2,
            ),
        )
        assert len(paths) == 2
        assert [p.hop_count for p in paths] == [1, 2]
        # Once limit was reached after depth 2, depth 3 is never probed.
        traversal_sqls = [s for s in session._executed_sql if "nodes_col" in s and "cypher" in s]
        assert all("*3..3" not in s for s in traversal_sqls)

    def test_pairwise_dedups_identical_routes_across_depths(self) -> None:
        """Distinct-by-node-id-sequence: a duplicate route is collected once."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        src, tgt, mid = str(uuid4()), str(uuid4()), str(uuid4())
        two_hop = (
            _agtype_nodes(_vertex(src, "A"), _vertex(mid, "M"), _vertex(tgt, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("SUPPLIER_OF", 0.8)),
        )
        # Same node-id sequence appears twice at depth 2 → deduped to one.
        session, _ = _make_session(rows_per_depth=[[], [two_hop, two_hop], []])
        engine = AgeGraphPathEngine(_make_factory(session))

        paths = asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(src),
                __import__("uuid").UUID(tgt),
                max_hops=3,
                prune_membership=False,
                limit=5,
            ),
        )
        assert len(paths) == 1
        assert paths[0].hop_count == 2

    def test_anchor_discovery_never_returns_one_hop_path(self) -> None:
        """Regression: anchor discovery starts probing at depth 2, never returns a 1-hop path.

        PathInsight enforces ``hop_count >= 2`` (a 1-hop "path" is just a known
        direct edge, not a multi-hop insight).  A mock that WOULD return a 1-hop
        path at depth 1 must yield 0 anchor results, while the SAME 1-hop fixture
        is returned by find_paths_between (pairwise, where 1-hop is valid).
        """
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, b = str(uuid4()), str(uuid4())
        one_hop = (
            _agtype_nodes(_vertex(a, "A"), _vertex(b, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9)),
        )

        # Anchor: a depth-1 row exists in the fixture, but anchor mode never probes
        # depth 1 (range starts at 2), so the depth-1 row is never consumed → 0 paths.
        anchor_session, _ = _make_session(rows_per_depth=[[one_hop], [], []])
        anchor_engine = AgeGraphPathEngine(_make_factory(anchor_session))
        anchor_paths = asyncio.run(
            anchor_engine.find_paths_from_anchor(
                __import__("uuid").UUID(a), max_hops=3, prune_membership=False, limit=5
            ),
        )
        assert anchor_paths == []
        # No ``*1..1`` probe was ever issued by anchor discovery.
        anchor_traversals = [s for s in anchor_session._executed_sql if "nodes_col" in s and "cypher" in s]
        assert all("*1..1" not in s for s in anchor_traversals)
        assert any("*2..2" in s for s in anchor_traversals)

        # Pairwise: the SAME 1-hop fixture is a valid direct connection → returned.
        pairwise_session, _ = _make_session(rows_per_depth=[[one_hop], [], []])
        pairwise_engine = AgeGraphPathEngine(_make_factory(pairwise_session))
        pairwise_paths = asyncio.run(
            pairwise_engine.find_paths_between(
                __import__("uuid").UUID(a),
                __import__("uuid").UUID(b),
                max_hops=3,
                prune_membership=False,
                limit=5,
            ),
        )
        assert len(pairwise_paths) == 1
        assert pairwise_paths[0].hop_count == 1

    def test_anchor_min_hops_clamped_to_two(self) -> None:
        """Data-coverage fix 2026-07-16: ``min_hops`` is now a parameter, but a
        value below 2 must be clamped to 2 so anchor discovery never issues a
        ``*1..1`` probe (PathInsight enforces hop_count >= 2)."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a = str(uuid4())
        session, _ = _make_session(rows_per_depth=[[], [], []])
        engine = AgeGraphPathEngine(_make_factory(session))
        asyncio.run(
            engine.find_paths_from_anchor(
                __import__("uuid").UUID(a), max_hops=3, prune_membership=False, limit=5, min_hops=1
            ),
        )
        traversals = [s for s in session._executed_sql if "nodes_col" in s and "cypher" in s]
        assert all("*1..1" not in s for s in traversals)
        assert any("*2..2" in s for s in traversals)

    def test_path_exists_returns_first_hop(self) -> None:
        """path_exists returns the shortest hop count where a row appears."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, b = str(uuid4()), str(uuid4())
        row = (_agtype_nodes(_vertex(a, "A"), _vertex(b, "B")), _agtype_edges(_edge("PARTNER_OF", 0.9)))
        # Empty at depth 1, hit at depth 2.
        session, _ = _make_session(rows_per_depth=[[], [row]])
        engine = AgeGraphPathEngine(_make_factory(session))

        hops = asyncio.run(
            engine.path_exists(__import__("uuid").UUID(a), __import__("uuid").UUID(b), max_hops=3),
        )
        assert hops == 2

    def test_path_exists_none_when_disconnected(self) -> None:
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        session, _ = _make_session(rows_per_depth=[[], [], []])
        engine = AgeGraphPathEngine(_make_factory(session))
        hops = asyncio.run(engine.path_exists(uuid4(), uuid4(), max_hops=3))
        assert hops is None


class TestRelIdParsing:
    def test_rel_ids_parsed(self) -> None:
        """rel_ids are populated from relationships(p) edge properties."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, b = str(uuid4()), str(uuid4())
        rid = str(uuid4())
        row = (
            _agtype_nodes(_vertex(a, "A"), _vertex(b, "B")),
            _agtype_edges(_edge("PARTNER_OF", 0.9, relation_id=rid)),
        )
        session, _ = _make_session(rows_per_depth=[[row]])
        engine = AgeGraphPathEngine(_make_factory(session))

        # rel_id parsing is independent of mode; use find_paths_between because a
        # 1-hop direct edge is only valid in pairwise mode (anchor starts at 2 hops).
        paths = asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(a),
                __import__("uuid").UUID(b),
                max_hops=1,
                prune_membership=False,
                limit=5,
            ),
        )
        assert len(paths) == 1
        assert paths[0].rel_ids == (__import__("uuid").UUID(rid),)
        assert paths[0].edge_confs == (0.9,)
        assert paths[0].rel_types == ("PARTNER_OF",)

    def test_missing_rel_id_yields_empty_tuple(self) -> None:
        """EVENT_EXPOSES-style edges with no relation_id → rel_ids omits them."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a, b = str(uuid4()), str(uuid4())
        row = (
            _agtype_nodes(_vertex(a, "A"), _vertex(b, "B")),
            _agtype_edges(_edge("EVENT_EXPOSES", 0.7)),  # no relation_id
        )
        session, _ = _make_session(rows_per_depth=[[row]])
        engine = AgeGraphPathEngine(_make_factory(session))
        # 1-hop direct edge → pairwise mode (anchor discovery starts at 2 hops).
        paths = asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(a),
                __import__("uuid").UUID(b),
                max_hops=1,
                prune_membership=False,
                limit=5,
            ),
        )
        assert len(paths) == 1
        assert paths[0].rel_ids == ()


class TestEdgeDirectionCapture:
    """edge_forward captures TRUE subject→object orientation per hop (2026-06-13).

    The undirected VLE can walk an edge backward; ``relationships(p)`` still
    carries each edge's real ``start_id``(subject)/``end_id``(object).  The parser
    compares them to the path-node graphids to record whether each hop was walked
    forward (subject→object) or reverse.
    """

    def _run_pairwise(self, a: str, b: str, edge: dict):  # type: ignore[no-untyped-def]
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        row = (_agtype_nodes(_vertex(a, "A"), _vertex(b, "B")), _agtype_edges(edge))
        session, _ = _make_session(rows_per_depth=[[row]])
        engine = AgeGraphPathEngine(_make_factory(session))
        return asyncio.run(
            engine.find_paths_between(
                __import__("uuid").UUID(a),
                __import__("uuid").UUID(b),
                max_hops=1,
                prune_membership=False,
                limit=5,
            ),
        )

    def test_forward_walked_edge_is_forward(self) -> None:
        """Path order A→B and edge start_id=A → edge_forward[0] is True."""
        a, b = str(uuid4()), str(uuid4())
        edge = _directed_edge("ACQUIRED_BY", 0.9, subject_entity_id=a, object_entity_id=b)
        paths = self._run_pairwise(a, b, edge)
        assert len(paths) == 1
        assert paths[0].edge_forward == (True,)

    def test_reverse_walked_edge_is_reverse(self) -> None:
        """Path order A→B but edge start_id=B (subject) → edge_forward[0] is False.

        The classic inverted ACQUIRED_BY: traversal walked Informatica→Salesforce
        while the stored edge is Salesforce(subject)→Informatica(object).
        """
        a, b = str(uuid4()), str(uuid4())
        # Subject is B (the node we ARRIVE at), object is A (the node we leave).
        edge = _directed_edge("ACQUIRED_BY", 0.9, subject_entity_id=b, object_entity_id=a)
        paths = self._run_pairwise(a, b, edge)
        assert len(paths) == 1
        assert paths[0].edge_forward == (False,)

    def test_missing_start_end_defaults_forward(self) -> None:
        """Legacy agtype without start_id/end_id → forward default (back-compat)."""
        a, b = str(uuid4()), str(uuid4())
        paths = self._run_pairwise(a, b, _edge("ACQUIRED_BY", 0.9))
        assert len(paths) == 1
        assert paths[0].edge_forward == (True,)


class TestGucAppliedToQuery:
    def test_guc_applied_to_query_session_scoped(self) -> None:
        """The hygiene GUCs are emitted as session-scoped SET on the SAME session.

        This is the GUC-scope fix: ``SET LOCAL`` would evaporate before the
        traversal query ran in a different implicit transaction, so the timeout /
        parallel cap never bound the query (the flood). Session-scoped ``SET``
        on the same connection persists to the traversal query.
        """
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        session, _ = _make_session(rows_per_depth=[[]])
        engine = AgeGraphPathEngine(_make_factory(session))
        # max_hops=2 so anchor discovery (min_hops=2) actually issues a traversal
        # query — with max_hops=1 the loop range(2, 2) is empty and nothing runs.
        asyncio.run(
            engine.find_paths_from_anchor(uuid4(), max_hops=2, prune_membership=True, limit=5),
        )

        emitted = [s.lower() for s in session._executed_sql]
        # The GUCs must be plain session-scoped SET (NOT SET LOCAL).
        parallel = [s for s in emitted if "max_parallel_workers_per_gather" in s]
        timeout = [s for s in emitted if "statement_timeout" in s]
        assert parallel and "set local" not in parallel[0]
        assert "0" in parallel[0]
        assert timeout and "set local" not in timeout[0]

        # The GUCs are emitted BEFORE the traversal query on the SAME session
        # (same mock => same connection), so they actually constrain it.
        idx_parallel = next(i for i, s in enumerate(emitted) if "max_parallel_workers_per_gather" in s)
        idx_traversal = next(i for i, s in enumerate(emitted) if "nodes_col" in s and "cypher" in s)
        assert idx_parallel < idx_traversal

    def test_timeout_mapped_to_cypher_timeout_error(self) -> None:
        """A statement_timeout cancellation surfaces as CypherTimeoutError."""
        from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        ok = MagicMock()

        async def _execute(stmt: object, *a: object, **k: object) -> MagicMock:
            sql = str(stmt)
            if "nodes_col" in sql and "cypher" in sql:
                raise RuntimeError("canceling statement due to statement timeout")
            return ok

        session.execute = AsyncMock(side_effect=_execute)
        engine = AgeGraphPathEngine(_make_factory(session))
        # max_hops=2 so a traversal query actually executes (anchor min_hops=2).
        with pytest.raises(CypherTimeoutError):
            asyncio.run(
                engine.find_paths_from_anchor(uuid4(), max_hops=2, prune_membership=True, limit=5),
            )


class TestPortContract:
    def test_graph_path_engine_port_is_abc(self) -> None:
        """The port is an ABC with the 3 abstract methods and cannot be instantiated."""
        import inspect

        from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine

        assert inspect.isabstract(GraphPathEngine)
        with pytest.raises(TypeError):
            GraphPathEngine()  # type: ignore[abstract]
        for method in ("path_exists", "find_paths_between", "find_paths_from_anchor"):
            assert getattr(GraphPathEngine, method).__isabstractmethod__

    def test_raw_path_has_rel_ids(self) -> None:
        """RawPath carries the new rel_ids field (default empty for legacy callers)."""
        from knowledge_graph.application.ports.graph_path_engine import RawPath

        rid = uuid4()
        p = RawPath(
            node_ids=("a", "b"),
            node_names=("A", "B"),
            node_types=("company", "company"),
            rel_types=("PARTNER_OF",),
            edge_confs=(0.9,),
            rel_ids=(rid,),
        )
        assert p.rel_ids == (rid,)
        assert p.hop_count == 1
        # Default empty when omitted (back-compat).
        legacy = RawPath(
            node_ids=("a", "b"),
            node_names=("A", "B"),
            node_types=("company", "company"),
            rel_types=("PARTNER_OF",),
            edge_confs=(0.9,),
        )
        assert legacy.rel_ids == ()

    def test_raw_path_edge_forward_defaults_empty(self) -> None:
        """RawPath.edge_forward defaults empty; edge_forward_at defaults forward."""
        from knowledge_graph.application.ports.graph_path_engine import RawPath, edge_forward_at

        legacy = RawPath(
            node_ids=("a", "b", "c"),
            node_names=("A", "B", "C"),
            node_types=("company", "company", "company"),
            rel_types=("ACQUIRED_BY", "SUPPLIER_OF"),
            edge_confs=(0.9, 0.8),
        )
        assert legacy.edge_forward == ()
        # Out-of-range / empty → forward (the pre-fix node[i]→node[i+1] default).
        assert edge_forward_at(legacy.edge_forward, 0) is True
        assert edge_forward_at(legacy.edge_forward, 1) is True

        explicit = RawPath(
            node_ids=("a", "b"),
            node_names=("A", "B"),
            node_types=("company", "company"),
            rel_types=("ACQUIRED_BY",),
            edge_confs=(0.9,),
            edge_forward=(False,),
        )
        assert explicit.edge_forward == (False,)
        assert edge_forward_at(explicit.edge_forward, 0) is False

    def test_age_engine_implements_port(self) -> None:
        from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        assert issubclass(AgeGraphPathEngine, GraphPathEngine)


class TestSelfLoopGuard:
    def test_self_loop_rejected(self) -> None:
        """A path whose endpoints are the same entity is dropped."""
        from knowledge_graph.infrastructure.age.graph_path_engine import AgeGraphPathEngine

        a = str(uuid4())
        mid = str(uuid4())
        # src == dst (same_id) at both ends → self-loop.
        row = (
            _agtype_nodes(_vertex(a, "A"), _vertex(mid, "M"), _vertex(a, "A")),
            _agtype_edges(_edge("PARTNER_OF", 0.9), _edge("PARTNER_OF", 0.8)),
        )
        session, _ = _make_session(rows_per_depth=[[row], [], []])
        engine = AgeGraphPathEngine(_make_factory(session))
        paths = asyncio.run(
            engine.find_paths_from_anchor(__import__("uuid").UUID(a), max_hops=3, prune_membership=False, limit=5),
        )
        assert paths == []
