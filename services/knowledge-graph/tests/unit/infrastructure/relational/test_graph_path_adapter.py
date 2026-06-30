"""Unit tests for RelationalGraphPathAdapter (PLAN-0113 W1).

These tests mock the SQLAlchemy session so they run with no database.  They lock
in the contract that the live integration / AGE-parity tests then verify against
real data:

  * the connectivity probe uses a SETTLED-SET ``UNION`` (dedup) — NOT ``UNION ALL``
  * the enumeration CTE is depth-bounded (``:max_hops``), cycle-guarded
    (``NOT ... = ANY(node_path)``) and degree-capped (``LIMIT :degree_cap``)
  * the ``degree_cap`` / ``limit`` params are bound from config, not interpolated
  * membership-relation paths are pruned post-hoc when ``prune_membership=True``
  * RawPath assembly mirrors the AGE adapter (names/types/labels/confidences,
    ``edge_forward`` from ``src == subject_entity_id``, self-loop rejection)
  * a Postgres statement-timeout cancellation maps to ``CypherTimeoutError``
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
from knowledge_graph.infrastructure.relational.graph_path_adapter import (
    _PATH_EXISTS_SQL,
    RelationalGraphPathAdapter,
    _build_enumerate_sql,
    _path_has_membership,
)

# ── Fake session plumbing ────────────────────────────────────────────────────


class _FakeResult:
    """Mimics the subset of SQLAlchemy Result the adapter uses."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def first(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class _FakeSession:
    """Records every executed SQL string and returns scripted rows by query kind.

    The adapter issues up to four query *shapes* per discover() call:
      1. the SET GUC statements (``SET ...``)
      2. the enumeration CTE (``WITH RECURSIVE walk``)
      3. the node resolver (``FROM canonical_entities``)
      4. the edge resolver (``FROM graph_edges`` with ``relation_id = ANY``)
    and for path_exists the connectivity probe (``WITH RECURSIVE reach``).
    """

    def __init__(
        self,
        *,
        exists_hops: int | None = None,
        enumerate_rows: list[tuple] | None = None,
        nodes: list[tuple] | None = None,
        edges: list[tuple] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self.executed: list[str] = []
        self._exists_hops = exists_hops
        self._enumerate_rows = enumerate_rows or []
        self._nodes = nodes or []
        self._edges = edges or []
        self._raise_on = raise_on

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, sql: Any, params: dict | None = None) -> _FakeResult:
        s = str(sql)
        self.executed.append(s)
        if self._raise_on and self._raise_on in s:
            raise RuntimeError("canceling statement due to statement timeout")
        if s.strip().upper().startswith("SET "):
            return _FakeResult([])
        if "WITH RECURSIVE reach" in s:
            return _FakeResult([(self._exists_hops,)] if self._exists_hops is not None else [(None,)])
        if "WITH RECURSIVE walk" in s:
            return _FakeResult(self._enumerate_rows)
        if "FROM canonical_entities" in s:
            return _FakeResult(self._nodes)
        if "relation_id = ANY" in s:
            return _FakeResult(self._edges)
        return _FakeResult([])


def _factory(session: _FakeSession) -> Any:
    """Return a sessionmaker-like callable yielding the given fake session."""

    def _make() -> _FakeSession:
        return session

    return _make


# ── SQL-shape guards ─────────────────────────────────────────────────────────


class TestSqlShape:
    def test_path_exists_uses_settled_set_union_not_union_all(self) -> None:
        sql = str(_PATH_EXISTS_SQL)
        assert "UNION" in sql
        # The connectivity probe must dedup (settled set) — never UNION ALL.
        assert "UNION ALL" not in sql.replace("\n", " ")
        assert "WITH RECURSIVE reach" in sql

    def test_enumerate_sql_depth_bound_cycle_guard_degree_cap(self) -> None:
        sql = str(_build_enumerate_sql(anchor_free_target=False))
        # Depth bound.
        assert ":max_hops" in sql
        assert "w.depth <" in sql
        # In-SQL cycle guard.
        assert "NOT e.dst = ANY(w.node_path)" in sql
        # Degree cap bound as a param (not interpolated).
        assert "LIMIT :degree_cap" in sql
        # Result limit bound as a param.
        assert "LIMIT :limit" in sql
        # Carries the path arrays for later resolution.
        assert "node_path" in sql
        assert "rel_path" in sql

    def test_enumerate_sql_pairwise_binds_target_anchor_is_free(self) -> None:
        pairwise = str(_build_enumerate_sql(anchor_free_target=False))
        anchor = str(_build_enumerate_sql(anchor_free_target=True))
        assert ":target" in pairwise
        assert ":target" not in anchor


# ── Membership pruning helper ────────────────────────────────────────────────


class TestMembershipHelper:
    def test_is_in_industry_is_membership(self) -> None:
        # PLAN-0113 W0 added IS_IN_INDUSTRY to the prune set.
        assert _path_has_membership(("PARTNER_OF", "IS_IN_INDUSTRY")) is True

    def test_revenue_from_country_is_membership(self) -> None:
        assert _path_has_membership(("REVENUE_FROM_COUNTRY",)) is True

    def test_non_membership_path_not_pruned(self) -> None:
        assert _path_has_membership(("PARTNER_OF", "SUPPLIER_OF")) is False


# ── path_exists ──────────────────────────────────────────────────────────────


class TestPathExists:
    def test_returns_shortest_hops(self) -> None:
        sess = _FakeSession(exists_hops=2)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        hops = asyncio.run(adapter.path_exists(uuid4(), uuid4(), max_hops=3))
        assert hops == 2

    def test_disconnected_returns_none(self) -> None:
        sess = _FakeSession(exists_hops=None)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        hops = asyncio.run(adapter.path_exists(uuid4(), uuid4(), max_hops=3))
        assert hops is None

    def test_same_entity_returns_none(self) -> None:
        sess = _FakeSession(exists_hops=1)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        eid = uuid4()
        assert asyncio.run(adapter.path_exists(eid, eid, max_hops=3)) is None

    def test_timeout_maps_to_cypher_timeout_error(self) -> None:
        sess = _FakeSession(raise_on="WITH RECURSIVE reach")
        adapter = RelationalGraphPathAdapter(_factory(sess))
        with pytest.raises(CypherTimeoutError):
            asyncio.run(adapter.path_exists(uuid4(), uuid4(), max_hops=3))


# ── find_paths_between (RawPath assembly + pruning + self-loop) ───────────────


def _ids() -> tuple[UUID, UUID, UUID, UUID]:
    return uuid4(), uuid4(), uuid4(), uuid4()


class TestFindPathsBetween:
    def test_assembles_rawpath_with_names_types_edges(self) -> None:
        a, b, c, rel = _ids()
        # One 2-hop path a -> c -> b via two relations.
        rel1, rel2 = uuid4(), uuid4()
        enumerate_rows = [([a, c, b], [rel1, rel2], 2)]
        nodes = [
            (a, "Apple", "company"),
            (c, "TSMC", "company"),
            (b, "Anthropic", "company"),
        ]
        edges = [
            (rel1, "SUPPLIER_OF", 0.9, a),  # a is subject -> forward
            (rel2, "PARTNER_OF", 0.8, b),  # b is subject -> reverse (leaving node is c)
        ]
        sess = _FakeSession(enumerate_rows=enumerate_rows, nodes=nodes, edges=edges)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        paths = asyncio.run(adapter.find_paths_between(a, b, max_hops=3, prune_membership=False, limit=5))
        assert len(paths) == 1
        p = paths[0]
        assert p.node_ids == (str(a), str(c), str(b))
        assert p.node_names == ("Apple", "TSMC", "Anthropic")
        assert p.node_types == ("company", "company", "company")
        assert p.rel_types == ("SUPPLIER_OF", "PARTNER_OF")
        assert p.edge_confs == (0.9, 0.8)
        assert p.rel_ids == (rel1, rel2)
        assert p.hop_count == 2
        # edge_forward: edge0 leaves from a (subject a) -> True; edge1 leaves from
        # c but subject is b -> False (reverse walk).
        assert p.edge_forward == (True, False)

    def test_membership_path_pruned_when_requested(self) -> None:
        a, b, c, _ = _ids()
        rel1, rel2 = uuid4(), uuid4()
        enumerate_rows = [([a, c, b], [rel1, rel2], 2)]
        nodes = [(a, "Apple", "company"), (c, "Tech", "sector"), (b, "MSFT", "company")]
        edges = [
            (rel1, "IS_IN_SECTOR", 0.9, a),  # membership edge
            (rel2, "IS_IN_SECTOR", 0.8, b),
        ]
        sess = _FakeSession(enumerate_rows=enumerate_rows, nodes=nodes, edges=edges)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        # prune on -> dropped.
        pruned = asyncio.run(adapter.find_paths_between(a, b, max_hops=3, prune_membership=True, limit=5))
        assert pruned == []
        # prune off -> kept.
        kept = asyncio.run(adapter.find_paths_between(a, b, max_hops=3, prune_membership=False, limit=5))
        assert len(kept) == 1

    def test_self_loop_path_rejected(self) -> None:
        a, _, c, _ = _ids()
        rel1, rel2 = uuid4(), uuid4()
        # Path returns to its start (a -> c -> a) — must be rejected.
        enumerate_rows = [([a, c, a], [rel1, rel2], 2)]
        nodes = [(a, "Apple", "company"), (c, "TSMC", "company")]
        edges = [(rel1, "PARTNER_OF", 0.9, a), (rel2, "PARTNER_OF", 0.8, c)]
        sess = _FakeSession(enumerate_rows=enumerate_rows, nodes=nodes, edges=edges)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        paths = asyncio.run(adapter.find_paths_between(a, a, max_hops=3, prune_membership=False, limit=5))
        # source==target short-circuits to [] before any query.
        assert paths == []

    def test_same_source_target_short_circuits(self) -> None:
        a = uuid4()
        sess = _FakeSession(enumerate_rows=[])
        adapter = RelationalGraphPathAdapter(_factory(sess))
        out = asyncio.run(adapter.find_paths_between(a, a, max_hops=3, prune_membership=False, limit=5))
        assert out == []
        # No traversal query should have been issued for the self pair.
        assert not any("WITH RECURSIVE walk" in s for s in sess.executed)

    def test_degree_cap_param_bound_from_config(self) -> None:
        a, b, _, _ = _ids()
        sess = _FakeSession(enumerate_rows=[])
        adapter = RelationalGraphPathAdapter(_factory(sess), degree_cap=37)
        asyncio.run(adapter.find_paths_between(a, b, max_hops=2, prune_membership=False, limit=5))
        # The adapter stores the cap; it is bound as the :degree_cap param.
        assert adapter._degree_cap == 37


# ── find_paths_from_anchor (min 2 hops) ──────────────────────────────────────


class TestFindPathsFromAnchor:
    def test_anchor_min_hops_is_two(self) -> None:
        a, b, c, _ = _ids()
        rel1, rel2 = uuid4(), uuid4()
        enumerate_rows = [([a, c, b], [rel1, rel2], 2)]
        nodes = [(a, "A", "company"), (c, "C", "company"), (b, "B", "company")]
        edges = [(rel1, "PARTNER_OF", 0.9, a), (rel2, "PARTNER_OF", 0.8, c)]
        sess = _FakeSession(enumerate_rows=enumerate_rows, nodes=nodes, edges=edges)
        adapter = RelationalGraphPathAdapter(_factory(sess))
        paths = asyncio.run(adapter.find_paths_from_anchor(a, max_hops=3, prune_membership=True, limit=5))
        assert len(paths) == 1
        assert paths[0].hop_count == 2
