"""Unit tests for FindPathsBetweenUseCase (PLAN-0112 W4, T-4-01).

Covers the use-case logic in isolation with a fake GraphPathEngine + a fake
build_scorer factory:
  - connected: existence + ranked scored paths
  - disconnected: connected=False, shortest_hops=None, empty paths
  - self-loop (source == target) rejected (→ 400)
  - max_hops out of range (→ 422 via ValueError)
  - limit out of range (→ 422 via ValueError)
  - entity-not-found (→ 404 via domain error)
  - ranking order: weirdness desc, then hop_count asc
  - meaningful_only forwards prune_membership=True to the engine
  - timeout propagates (CypherTimeoutError → router maps 503)
"""

from __future__ import annotations

from uuid import UUID

import pytest
from knowledge_graph.application.ports.graph_path_engine import RawPath
from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
from knowledge_graph.application.use_cases.find_paths_between import (
    FindPathsBetweenUseCase,
    PathsBetweenEntityNotFoundError,
    PathsBetweenSameEntityError,
)

pytestmark = [pytest.mark.unit]

_SRC = UUID("01900000-0000-7000-8000-0000000000a1")
_TGT = UUID("01900000-0000-7000-8000-0000000000a2")
_MID = UUID("01900000-0000-7000-8000-0000000000a3")


def _raw(hops: int, *, has_membership: bool = False) -> RawPath:
    """Build a RawPath with ``hops`` edges (hops+1 nodes)."""
    node_ids = [str(_SRC)]
    node_names = ["Source"]
    node_types = ["company"]
    for i in range(hops - 1):
        node_ids.append(str(UUID(int=0x1900_0000_0000_7000_8000_0000_0000_0B00 + i)))
        node_names.append(f"Mid{i}")
        node_types.append("company")
    node_ids.append(str(_TGT))
    node_names.append("Target")
    node_types.append("company")
    rel = "MEMBER_OF" if has_membership else "PARTNERS_WITH"
    return RawPath(
        node_ids=tuple(node_ids),
        node_names=tuple(node_names),
        node_types=tuple(node_types),
        rel_types=tuple(rel for _ in range(hops)),
        edge_confs=tuple(0.9 for _ in range(hops)),
        rel_ids=(),
    )


class _FakeEngine:
    """Configurable fake GraphPathEngine."""

    def __init__(
        self,
        *,
        shortest: int | None,
        paths: list[RawPath] | None = None,
        raise_on_exists: Exception | None = None,
    ) -> None:
        self._shortest = shortest
        self._paths = paths or []
        self._raise = raise_on_exists
        self.last_prune_membership: bool | None = None

    async def path_exists(self, source: UUID, target: UUID, *, max_hops: int) -> int | None:
        if self._raise is not None:
            raise self._raise
        return self._shortest

    async def find_paths_between(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        self.last_prune_membership = prune_membership
        return self._paths[:limit]

    async def find_paths_from_anchor(self, *a: object, **k: object) -> list[RawPath]:  # pragma: no cover
        return []


class _FakeScorer:
    """Scorer stub returning a PathInsight-like object with a fixed weirdness map.

    Maps hop_count → weirdness so ranking can be asserted deterministically.
    """

    def __init__(self, weirdness_by_hops: dict[int, float]) -> None:
        self._map = weirdness_by_hops

    def score(self, raw: RawPath) -> object:
        from types import SimpleNamespace

        w = self._map.get(raw.hop_count, 0.0)
        return SimpleNamespace(
            reliability=0.8,
            unexpectedness=0.5,
            semantic_distance=0.6,
            novelty=0.1,
            weirdness=w,
        )


async def _always_exists(_: UUID) -> bool:
    return True


def _uc(engine: _FakeEngine, scorer: _FakeScorer | None = None, *, exists=_always_exists) -> FindPathsBetweenUseCase:
    async def _build(_paths: list[RawPath]) -> object:
        return scorer

    return FindPathsBetweenUseCase(
        path_engine=engine,  # type: ignore[arg-type]
        entity_exists=exists,
        build_scorer=_build if scorer is not None else None,  # type: ignore[arg-type]
        max_hops_cap=3,
    )


class TestFindPathsBetween:
    async def test_connected_returns_ranked_paths(self) -> None:
        engine = _FakeEngine(shortest=1, paths=[_raw(1), _raw(2)])
        uc = _uc(engine, _FakeScorer({1: 0.4, 2: 0.9}))
        res = await uc.execute(_SRC, _TGT, max_hops=3, limit=5)
        assert res.connected is True
        assert res.shortest_hops == 1
        assert len(res.paths) == 2
        # weirdness desc → the 2-hop path (0.9) ranks above the 1-hop (0.4).
        assert res.paths[0].weirdness == 0.9
        assert res.paths[0].hop_count == 2

    async def test_shortest_hops_derived_from_returned_paths_not_probe(self) -> None:
        """shortest_hops is min(hop_count) of REPORTABLE paths, not the path_exists probe.

        Live-QA fix: ``path_exists`` may report a (degenerate) shorter hop than any
        path actually returned. The response must reflect the real reportable set.
        """
        # Probe claims a 1-hop connection, but the only enumerated paths are 2- and
        # 3-hop (the 1-hop was a degenerate duplicate-vertex path the engine dropped).
        engine = _FakeEngine(shortest=1, paths=[_raw(3), _raw(2)])
        uc = _uc(engine, _FakeScorer({2: 0.5, 3: 0.6}))
        res = await uc.execute(_SRC, _TGT, max_hops=3)
        assert res.connected is True
        assert res.shortest_hops == 2  # min hop_count of the RETURNED paths, not 1

    async def test_probe_connected_but_no_reportable_paths(self) -> None:
        """path_exists says connected, find_paths_between returns [] → connected=False.

        This is the SpaceX duplicate-vertex bug (FR-11 deferred dedup): the only
        path goes through a duplicate canonical vertex, so the engine's distinct-
        node guard drops it. The contract must be self-consistent — never
        ``connected:true, paths:[]``.
        """
        engine = _FakeEngine(shortest=2, paths=[])
        uc = _uc(engine, _FakeScorer({}))
        res = await uc.execute(_SRC, _TGT, max_hops=3)
        assert res.connected is False
        assert res.shortest_hops is None
        assert res.paths == []

    async def test_disconnected(self) -> None:
        engine = _FakeEngine(shortest=None)
        uc = _uc(engine, _FakeScorer({}))
        res = await uc.execute(_SRC, _TGT)
        assert res.connected is False
        assert res.shortest_hops is None
        assert res.paths == []

    async def test_self_loop_rejected(self) -> None:
        uc = _uc(_FakeEngine(shortest=None))
        with pytest.raises(PathsBetweenSameEntityError):
            await uc.execute(_SRC, _SRC)

    async def test_max_hops_out_of_range(self) -> None:
        uc = _uc(_FakeEngine(shortest=1))
        with pytest.raises(ValueError, match="max_hops"):
            await uc.execute(_SRC, _TGT, max_hops=4)
        with pytest.raises(ValueError, match="max_hops"):
            await uc.execute(_SRC, _TGT, max_hops=0)

    async def test_limit_out_of_range(self) -> None:
        uc = _uc(_FakeEngine(shortest=1))
        with pytest.raises(ValueError, match="limit"):
            await uc.execute(_SRC, _TGT, limit=21)

    async def test_entity_not_found(self) -> None:
        async def _missing(_: UUID) -> bool:
            return False

        uc = _uc(_FakeEngine(shortest=1), exists=_missing)
        with pytest.raises(PathsBetweenEntityNotFoundError):
            await uc.execute(_SRC, _TGT)

    async def test_ranking_tiebreak_by_hop_count_asc(self) -> None:
        # Two paths with EQUAL weirdness → shorter hop_count wins the tiebreak.
        engine = _FakeEngine(shortest=1, paths=[_raw(3), _raw(1)])
        uc = _uc(engine, _FakeScorer({1: 0.5, 3: 0.5}))
        res = await uc.execute(_SRC, _TGT, max_hops=3)
        assert [p.hop_count for p in res.paths] == [1, 3]

    async def test_meaningful_only_forwards_prune_membership(self) -> None:
        engine = _FakeEngine(shortest=1, paths=[_raw(2)])
        uc = _uc(engine, _FakeScorer({2: 0.5}))
        await uc.execute(_SRC, _TGT, meaningful_only=True)
        assert engine.last_prune_membership is True
        await uc.execute(_SRC, _TGT, meaningful_only=False)
        assert engine.last_prune_membership is False

    async def test_timeout_propagates(self) -> None:
        engine = _FakeEngine(shortest=None, raise_on_exists=CypherTimeoutError("boom"))
        uc = _uc(engine, _FakeScorer({}))
        with pytest.raises(CypherTimeoutError):
            await uc.execute(_SRC, _TGT)

    async def test_unscored_degrade_when_no_scorer(self) -> None:
        engine = _FakeEngine(shortest=2, paths=[_raw(2)])
        uc = _uc(engine, scorer=None)
        res = await uc.execute(_SRC, _TGT)
        assert res.connected is True
        assert res.paths[0].weirdness == 0.0
