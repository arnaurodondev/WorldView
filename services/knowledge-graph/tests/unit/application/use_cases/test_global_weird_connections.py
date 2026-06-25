"""Unit tests for GlobalWeirdConnectionsUseCase (PLAN-0112 W5, T-5-01).

The endpoint-pair dedup + filtering live in the repository SQL
(``list_global_weird``).  These tests therefore cover the use-case
responsibilities:
  - parameter validation (limit / offset / min_weirdness / since_days → 422)
  - forwarding every filter param verbatim to the repo
  - DTO mapping (PathInsight → WeirdConnectionPublic incl. src/dst/computed_at)
  - ordering preserved from the repo (weirdness DESC)
  - endpoint-pair dedup honoured (the use case maps exactly what the repo returns)
  - pagination forwarded
  - freshness_ts = MAX(computed_at)
  - the DI factory binds the READ-ONLY session (R27)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW_1 = datetime(2026, 6, 10, 10, 0, 0, tzinfo=UTC)
_NOW_2 = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)  # later → MAX


def _make_insight(*, weirdness: float, computed_at: datetime = _NOW_1, dst: UUID | None = None) -> object:
    """Build a real PathInsight domain entity (hop_count=2, 3 nodes, 2 edges)."""
    from knowledge_graph.domain.entities.path_insight import PathEdge, PathInsight, PathNode

    anchor = uuid4()
    dst_id = dst if dst is not None else uuid4()
    nodes = (
        PathNode(entity_id=anchor, name="Apple Inc.", entity_type="company"),
        PathNode(entity_id=uuid4(), name="TSMC", entity_type="company"),
        PathNode(entity_id=dst_id, name="Nvidia", entity_type="company"),
    )
    edges = (
        PathEdge(relation_type="SUPPLIED_BY", confidence=0.9),
        PathEdge(relation_type="SUPPLIES", confidence=0.8),
    )
    return PathInsight(
        insight_id=uuid4(),
        anchor_entity_id=anchor,
        hop_count=2,
        path_nodes=nodes,
        path_edges=edges,
        harmonic_score=0.5,
        diversity_score=0.5,
        surprise_score=0.5,
        composite_score=weirdness,
        computed_at=computed_at,
        dst_entity_id=dst_id,
        reliability=0.85,
        unexpectedness=0.6,
        semantic_distance=0.7,
        novelty=0.2,
        weirdness=weirdness,
        scorer_version="weirdness-1.0",
    )


class _FakeRepo:
    """Records the args passed to list_global_weird and returns a canned list."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.calls: list[dict[str, object]] = []

    async def list_global_weird(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        min_weirdness: float = 0.0,
        since_days: int | None = None,
        entity_type: str | None = None,
    ) -> list[object]:
        self.calls.append(
            {
                "limit": limit,
                "offset": offset,
                "min_weirdness": min_weirdness,
                "since_days": since_days,
                "entity_type": entity_type,
            }
        )
        return self._rows


def _uc(rows: list[object]) -> tuple[object, _FakeRepo]:
    from knowledge_graph.application.use_cases.global_weird_connections import (
        GlobalWeirdConnectionsUseCase,
    )

    repo = _FakeRepo(rows)
    return GlobalWeirdConnectionsUseCase(repo), repo  # type: ignore[arg-type]


class TestValidation:
    async def test_invalid_limit_low(self) -> None:
        uc, _ = _uc([])
        with pytest.raises(ValueError, match="limit"):
            await uc.execute(limit=0)

    async def test_invalid_limit_high(self) -> None:
        uc, _ = _uc([])
        with pytest.raises(ValueError, match="limit"):
            await uc.execute(limit=101)

    async def test_invalid_offset(self) -> None:
        uc, _ = _uc([])
        with pytest.raises(ValueError, match="offset"):
            await uc.execute(offset=-1)

    async def test_invalid_min_weirdness(self) -> None:
        uc, _ = _uc([])
        with pytest.raises(ValueError, match="min_weirdness"):
            await uc.execute(min_weirdness=1.5)

    async def test_invalid_since_days(self) -> None:
        uc, _ = _uc([])
        with pytest.raises(ValueError, match="since_days"):
            await uc.execute(since_days=0)
        with pytest.raises(ValueError, match="since_days"):
            await uc.execute(since_days=366)


class TestForwardingAndMapping:
    async def test_all_filters_forwarded_to_repo(self) -> None:
        uc, repo = _uc([])
        await uc.execute(limit=5, offset=10, min_weirdness=0.4, since_days=7, entity_type="company")
        assert repo.calls == [
            {
                "limit": 5,
                "offset": 10,
                "min_weirdness": 0.4,
                "since_days": 7,
                "entity_type": "company",
            }
        ]

    async def test_dto_mapping_includes_src_dst_computed_at(self) -> None:
        dst = uuid4()
        insight = _make_insight(weirdness=0.42, dst=dst)
        uc, _ = _uc([insight])
        resp = await uc.execute()
        assert resp.total == 1
        conn = resp.connections[0]
        assert conn.src_entity_id == insight.anchor_entity_id  # type: ignore[attr-defined]
        assert conn.dst_entity_id == dst
        assert conn.computed_at == insight.computed_at  # type: ignore[attr-defined]
        assert conn.weirdness == 0.42
        assert conn.hop_count == 2
        assert len(conn.path_nodes) == 3
        assert len(conn.path_edges) == 2
        assert conn.reliability == 0.85

    async def test_ordering_preserved_from_repo(self) -> None:
        # Repo already returns weirdness DESC; the use case must preserve it.
        rows = [
            _make_insight(weirdness=0.9),
            _make_insight(weirdness=0.5),
            _make_insight(weirdness=0.1),
        ]
        uc, _ = _uc(rows)
        resp = await uc.execute()
        scores = [c.weirdness for c in resp.connections]
        assert scores == [0.9, 0.5, 0.1]

    async def test_endpoint_pair_dedup_passthrough(self) -> None:
        # The repo dedups by (src, dst); the use case maps exactly what it gets.
        # Two distinct pairs in, two out — no extra dedup or duplication.
        rows = [_make_insight(weirdness=0.8), _make_insight(weirdness=0.7)]
        uc, _ = _uc(rows)
        resp = await uc.execute()
        assert resp.total == 2
        pairs = {(c.src_entity_id, c.dst_entity_id) for c in resp.connections}
        assert len(pairs) == 2

    async def test_freshness_ts_is_max_computed_at(self) -> None:
        rows = [
            _make_insight(weirdness=0.8, computed_at=_NOW_1),
            _make_insight(weirdness=0.7, computed_at=_NOW_2),
        ]
        uc, _ = _uc(rows)
        resp = await uc.execute()
        assert resp.freshness_ts == _NOW_2

    async def test_empty_feed(self) -> None:
        uc, _ = _uc([])
        resp = await uc.execute()
        assert resp.total == 0
        assert resp.connections == []
        assert resp.freshness_ts is None

    async def test_pagination_forwarded(self) -> None:
        uc, repo = _uc([])
        await uc.execute(limit=10, offset=20)
        assert repo.calls[0]["limit"] == 10
        assert repo.calls[0]["offset"] == 20


class TestReadOnlySessionWiring:
    async def test_factory_binds_readonly_session(self) -> None:
        """The DI factory must build the use case over the READ-ONLY session (R27)."""
        from knowledge_graph.api.dependencies import get_global_weird_connections_uc

        session = AsyncMock()
        uc = get_global_weird_connections_uc(session)
        # The repo wired into the use case must hold the read-only session.
        assert uc._repo._session is session  # type: ignore[attr-defined]
