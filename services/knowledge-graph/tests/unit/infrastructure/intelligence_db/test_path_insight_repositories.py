"""Unit tests for PathInsightJobRepository and PathInsightRepository (T-E1-02)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    fetchone_return: object = None,
    fetchall_return: list | None = None,
    rowcount: int = 0,
) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    result.fetchall.return_value = fetchall_return or []
    result.rowcount = rowcount
    session.execute = AsyncMock(return_value=result)
    return session


def _make_job_row(
    job_id: str | None = None,
    entity_id: str | None = None,
    status: str = "running",
    claimed_by: str | None = None,
    retry_count: int = 0,
) -> tuple:
    job_id = job_id or str(uuid4())
    entity_id = entity_id or str(uuid4())
    return (
        job_id,  # 0: job_id
        entity_id,  # 1: entity_id
        status,  # 2: status
        claimed_by,  # 3: claimed_by
        _NOW,  # 4: claimed_at
        retry_count,  # 5: retry_count
        None,  # 6: error_text
        _NOW,  # 7: created_at_approx
    )


# ---------------------------------------------------------------------------
# PathInsightJobRepository tests
# ---------------------------------------------------------------------------


class TestPathInsightJobRepository:
    def test_claim_batch_returns_jobs(self) -> None:
        """claim_batch returns PathInsightJob objects for each returned DB row."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        worker_id = uuid4()
        row = _make_job_row(claimed_by=str(worker_id))
        session = _make_session(fetchall_return=[row])
        repo = PathInsightJobRepository(session)
        jobs = asyncio.run(repo.claim_batch(worker_id, batch_size=5))
        assert len(jobs) == 1
        assert jobs[0].status.value == "running"
        assert jobs[0].claimed_by is not None

    @pytest.mark.asyncio
    async def test_claim_batch_skip_locked_no_overlap(self) -> None:
        """Two concurrent claim_batch calls return disjoint job sets (SKIP LOCKED).

        This test verifies the contract: each call gets a distinct set of rows.
        In unit test: we simulate with two separate sessions that return different rows.
        asyncio.gather requires a running event loop, so this test is async.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        worker_a = uuid4()
        worker_b = uuid4()
        job_a_id = str(uuid4())
        job_b_id = str(uuid4())

        session_a = _make_session(fetchall_return=[_make_job_row(job_id=job_a_id, claimed_by=str(worker_a))])
        session_b = _make_session(fetchall_return=[_make_job_row(job_id=job_b_id, claimed_by=str(worker_b))])

        repo_a = PathInsightJobRepository(session_a)
        repo_b = PathInsightJobRepository(session_b)

        jobs_a, jobs_b = await asyncio.gather(
            repo_a.claim_batch(worker_a, batch_size=5),
            repo_b.claim_batch(worker_b, batch_size=5),
        )
        ids_a = {j.job_id for j in jobs_a}
        ids_b = {j.job_id for j in jobs_b}
        # Disjoint (simulated via different mocked rows)
        assert ids_a.isdisjoint(ids_b)

    def test_reclaim_stuck_recovers_expired_running(self) -> None:
        """reclaim_stuck returns the rowcount of reset jobs (BP-112 pattern)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session(rowcount=3)
        repo = PathInsightJobRepository(session)
        count = asyncio.run(repo.reclaim_stuck(timeout_seconds=600))
        assert count == 3
        # Verify SQL was called (execute called once)
        assert session.execute.called

    def test_reclaim_stuck_zero_when_no_stuck_jobs(self) -> None:
        """reclaim_stuck returns 0 when no jobs are stuck."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session(rowcount=0)
        repo = PathInsightJobRepository(session)
        count = asyncio.run(repo.reclaim_stuck(timeout_seconds=600))
        assert count == 0

    def test_mark_done_calls_execute(self) -> None:
        """mark_done issues an UPDATE via session.execute."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session()
        repo = PathInsightJobRepository(session)
        asyncio.run(repo.mark_done(uuid4(), paths_found=42))
        assert session.execute.called
        # SQL should reference 'done'
        sql_str = str(session.execute.call_args_list[0][0][0]).lower()
        assert "done" in sql_str

    def test_mark_failed_increments_retry_count(self) -> None:
        """mark_failed SQL uses retry_count increment and handles < 3 case."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session()
        repo = PathInsightJobRepository(session)
        asyncio.run(repo.mark_failed(uuid4(), error_text="some error"))
        assert session.execute.called
        # SQL should reference retry_count
        sql_str = str(session.execute.call_args_list[0][0][0]).lower()
        assert "retry_count" in sql_str

    def test_mark_failed_final_sets_failed_status(self) -> None:
        """mark_failed SQL transitions to 'failed' when retry_count >= 2."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session()
        repo = PathInsightJobRepository(session)
        asyncio.run(repo.mark_failed(uuid4(), error_text="terminal failure"))
        sql_str = str(session.execute.call_args_list[0][0][0]).lower()
        # SQL should have the 'failed' terminal case
        assert "failed" in sql_str

    def test_insert_pending_returns_true_on_new_row(self) -> None:
        """insert_pending returns True when a new job is inserted."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        row = (str(uuid4()),)  # RETURNING job_id
        session = _make_session(fetchone_return=row)
        repo = PathInsightJobRepository(session)
        result = asyncio.run(repo.insert_pending(uuid4()))
        assert result is True

    def test_insert_pending_returns_false_on_conflict(self) -> None:
        """insert_pending returns False on ON CONFLICT DO NOTHING (no row returned)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_job_repository import (
            PathInsightJobRepository,
        )

        session = _make_session(fetchone_return=None)
        repo = PathInsightJobRepository(session)
        result = asyncio.run(repo.insert_pending(uuid4()))
        assert result is False


# ---------------------------------------------------------------------------
# PathInsightRepository tests
# ---------------------------------------------------------------------------


def _make_insight_row(
    insight_id: str | None = None,
    anchor_id: str | None = None,
    hop_count: int = 2,
    composite: float | None = None,
) -> tuple:
    """Build a fake path_insights DB row.

    ``composite`` defaults to the formula result for harmonic=0.8, diversity=0.5,
    surprise=0.5, template=None so PathInsight.__post_init__ invariant passes.
    Pass an explicit value only when testing non-default scores.
    """
    import json

    nodes = json.dumps(
        [{"entity_id": str(uuid4()), "name": f"E{i}", "entity_type": "company"} for i in range(hop_count + 1)]
    )
    edges = json.dumps([{"relation_type": "SUPPLIES_TO", "confidence": 0.8} for _ in range(hop_count)])
    # Derive a valid composite score: round(min(h*0.4 + d*0.35 + s*0.25, 1.0), 6)
    _h, _d, _s = 0.8, 0.5, 0.5
    _composite = composite if composite is not None else round(min(_h * 0.4 + _d * 0.35 + _s * 0.25, 1.0), 6)
    return (
        insight_id or str(uuid4()),  # 0: insight_id
        anchor_id or str(uuid4()),  # 1: anchor_entity_id
        hop_count,  # 2: hop_count
        nodes,  # 3: path_nodes JSONB
        edges,  # 4: path_edges JSONB
        _h,  # 5: harmonic_score
        _d,  # 6: diversity_score
        _s,  # 7: surprise_score
        None,  # 8: template_match
        _composite,  # 9: composite_score
        None,  # 10: llm_explanation
        None,  # 11: explanation_model
        _NOW,  # 12: computed_at
        # PLAN-0112 W3: the 7 new weirdness columns.  NULL here exercises the
        # backward-compat path (old rows pre-migration deserialize to defaults).
        None,  # 13: dst_entity_id
        None,  # 14: reliability
        None,  # 15: unexpectedness
        None,  # 16: semantic_distance
        None,  # 17: novelty
        None,  # 18: weirdness
        None,  # 19: scorer_version
    )


class TestPathInsightRepository:
    def test_replace_for_anchor_deletes_old_rows(self) -> None:
        """replace_for_anchor issues a DELETE before the INSERT."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        result.rowcount = 0
        session.execute = AsyncMock(return_value=result)

        repo = PathInsightRepository(session)
        anchor = uuid4()
        asyncio.run(repo.replace_for_anchor(anchor, []))

        # First execute call must be the DELETE
        first_sql = str(session.execute.call_args_list[0][0][0]).lower()
        assert "delete" in first_sql
        assert "path_insights" in first_sql

    def test_replace_for_anchor_inserts_provided_insights(self) -> None:
        """replace_for_anchor issues INSERT when insights list is non-empty."""
        from datetime import UTC, datetime

        from knowledge_graph.domain.entities.path_insight import PathEdge, PathInsight, PathNode
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        result.rowcount = 0
        session.execute = AsyncMock(return_value=result)

        anchor = uuid4()
        node1 = PathNode(entity_id=uuid4(), name="A", entity_type="company")
        node2 = PathNode(entity_id=uuid4(), name="B", entity_type="company")
        node3 = PathNode(entity_id=uuid4(), name="C", entity_type="company")
        edge1 = PathEdge(relation_type="SUPPLIES_TO", confidence=0.8)
        edge2 = PathEdge(relation_type="OWNS", confidence=0.7)

        # composite = round(min(h*0.4 + d*0.35 + s*0.25, 1.0), 6)
        # h = harmonic_mean(0.8, 0.7), d = 0.5, s = 0.5
        from knowledge_graph.application.services.path_scorer import _harmonic_mean

        h = _harmonic_mean((0.8, 0.7))
        composite = round(min(h * 0.4 + 0.5 * 0.35 + 0.5 * 0.25, 1.0), 6)

        insight = PathInsight(
            insight_id=uuid4(),
            anchor_entity_id=anchor,
            hop_count=2,
            path_nodes=(node1, node2, node3),
            path_edges=(edge1, edge2),
            harmonic_score=round(h, 6),
            diversity_score=0.5,
            surprise_score=0.5,
            composite_score=composite,
            computed_at=datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC),
        )

        repo = PathInsightRepository(session)
        asyncio.run(repo.replace_for_anchor(anchor, [insight]))

        # Second execute call must be the INSERT
        assert session.execute.call_count == 2
        second_sql = str(session.execute.call_args_list[1][0][0]).lower()
        assert "insert" in second_sql
        assert "path_insights" in second_sql

    def test_list_by_anchor_filters_min_score(self) -> None:
        """list_by_anchor passes min_score as a parameter."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        anchor = uuid4()
        # Use default composite (derived from formula) so PathInsight invariant passes.
        row = _make_insight_row(anchor_id=str(anchor), hop_count=2)
        session = _make_session(fetchall_return=[row])
        repo = PathInsightRepository(session)
        asyncio.run(repo.list_by_anchor(anchor, min_score=0.5))
        # The SQL query should have been issued; results are populated.
        assert session.execute.called
        # Verify min_score param was passed
        params = session.execute.call_args_list[0][0][1]
        assert params["min_score"] == 0.5

    def test_list_by_anchor_filters_hop_count_range(self) -> None:
        """list_by_anchor passes min_hops and max_hops parameters."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        anchor = uuid4()
        session = _make_session(fetchall_return=[])
        repo = PathInsightRepository(session)
        asyncio.run(repo.list_by_anchor(anchor, min_hops=3, max_hops=4))
        params = session.execute.call_args_list[0][0][1]
        assert params["min_hops"] == 3
        assert params["max_hops"] == 4

    def test_list_by_anchor_sorted_by_weirdness_desc(self) -> None:
        """PLAN-0112 W3: list_by_anchor ranks by weirdness (COALESCE-ing to the
        legacy composite_score for un-backfilled rows)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        anchor = uuid4()
        session = _make_session(fetchall_return=[])
        repo = PathInsightRepository(session)
        asyncio.run(repo.list_by_anchor(anchor))
        sql_str = str(session.execute.call_args_list[0][0][0]).lower()
        assert "coalesce(weirdness, composite_score) desc" in sql_str

    def test_update_explanation_calls_update(self) -> None:
        """update_explanation issues an UPDATE SQL."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        session = _make_session()
        repo = PathInsightRepository(session)
        asyncio.run(repo.update_explanation(uuid4(), "an explanation", "llama-3.1-8b"))
        assert session.execute.called
        sql_str = str(session.execute.call_args_list[0][0][0]).lower()
        assert "update" in sql_str
        assert "llm_explanation" in sql_str

    def test_list_by_anchor_returns_path_insight_objects(self) -> None:
        """list_by_anchor maps DB rows to PathInsight domain objects."""
        from knowledge_graph.domain.entities.path_insight import PathInsight
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            PathInsightRepository,
        )

        anchor = uuid4()
        # Use default composite so PathInsight formula invariant passes.
        row = _make_insight_row(anchor_id=str(anchor), hop_count=2)
        session = _make_session(fetchall_return=[row])
        repo = PathInsightRepository(session)
        results = asyncio.run(repo.list_by_anchor(anchor))
        assert len(results) == 1
        assert isinstance(results[0], PathInsight)
        assert results[0].hop_count == 2


class TestEdgeForwardRoundTrip:
    """_edges_to_json / _parse_edges persist + restore the ``forward`` flag."""

    def test_forward_roundtrips_through_json(self) -> None:
        from knowledge_graph.domain.entities.path_insight import PathEdge
        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            _edges_to_json,
            _parse_edges,
        )

        edges = (
            PathEdge(relation_type="ACQUIRED_BY", confidence=0.9, forward=False),
            PathEdge(relation_type="COMPETES_WITH", confidence=0.8, forward=True),
        )
        restored = _parse_edges(_edges_to_json(edges))
        assert [e.forward for e in restored] == [False, True]

    def test_legacy_row_without_forward_defaults_true(self) -> None:
        """Rows persisted before the fix have no ``forward`` key → default True."""
        import json

        from knowledge_graph.infrastructure.intelligence_db.repositories.path_insight_repository import (
            _parse_edges,
        )

        legacy = json.dumps([{"relation_type": "ACQUIRED_BY", "confidence": 0.9}])
        restored = _parse_edges(legacy)
        assert restored[0].forward is True
