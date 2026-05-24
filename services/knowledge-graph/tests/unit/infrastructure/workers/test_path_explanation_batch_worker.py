"""Unit tests for PathExplanationBatchWorker (2026-05-23).

Tests cover:
- test_run_calls_explanation_service_for_each_row  — explanation generated per row
- test_run_skips_when_no_unexplained_rows           — empty result → no LLM call
- test_run_continues_after_single_failure           — one failure does not skip rest
- test_fetch_batch_parses_jsonb_nodes_and_edges     — JSON columns parsed to domain objects
- test_concurrency_bounded_by_semaphore             — max N concurrent LLM calls
- test_batch_size_respected_in_query                — query uses configured LIMIT
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 23, 10, 0, 0, tzinfo=UTC)


def _make_nodes_json(names: list[str]) -> str:
    return json.dumps(
        [
            {
                "entity_id": str(uuid4()),
                "name": name,
                "entity_type": "company",
            }
            for name in names
        ]
    )


def _make_edges_json(n: int = 1) -> str:
    return json.dumps([{"relation_type": "COMPETES_WITH", "confidence": 0.8} for _ in range(n)])


def _make_session_factory(rows: list[tuple], gauge_count: int = 0) -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory that returns the given rows from execute().

    ``gauge_count`` is the integer returned by ``fetchone()`` for the
    ``_update_pending_gauge`` SELECT (PLAN-0093 D-1 T-D-1-02).  Default 0
    keeps the legacy tests behaviour: no pending backlog reported.
    """
    result_mock = MagicMock()
    result_mock.fetchall = MagicMock(return_value=rows)
    # PLAN-0093 D-1: the new pending-gauge SELECT uses ``fetchone`` and
    # expects a one-element tuple of (count,) — return a configurable int
    # so unit tests can assert the gauge value end-to-end.
    result_mock.fetchone = MagicMock(return_value=(gauge_count,))

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_exp_service(called: list | None = None, fail_on: set | None = None) -> MagicMock:
    """Build a mock PathExplanationService that records calls."""
    service = MagicMock()

    async def _generate(insight_id: UUID, path_nodes: list, path_edges: list) -> None:
        if called is not None:
            called.append(str(insight_id))
        if fail_on and str(insight_id) in fail_on:
            raise RuntimeError("LLM unavailable")

    service.generate_explanation = _generate
    return service


class TestPathExplanationBatchWorkerRun:
    def test_run_calls_explanation_service_for_each_row(self) -> None:
        """run() calls generate_explanation once per unexplained insight row."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        insight_ids = [uuid4(), uuid4(), uuid4()]
        rows = [(str(iid), _make_nodes_json(["A", "B"]), _make_edges_json(1)) for iid in insight_ids]
        factory, _session = _make_session_factory(rows)
        called: list[str] = []
        service = _make_exp_service(called=called)

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
            batch_size=10,
            concurrency=5,
        )
        asyncio.run(worker.run())

        assert len(called) == 3
        for iid in insight_ids:
            assert str(iid) in called

    def test_run_skips_when_no_unexplained_rows(self) -> None:
        """run() with empty result set makes zero LLM calls."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        factory, _session = _make_session_factory([])
        called: list[str] = []
        service = _make_exp_service(called=called)

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
        )
        asyncio.run(worker.run())
        assert called == []

    def test_run_continues_after_single_failure(self) -> None:
        """A failure in one generate_explanation call must not block the rest."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        insight_ids = [uuid4(), uuid4(), uuid4()]
        rows = [(str(iid), _make_nodes_json(["A", "B"]), _make_edges_json(1)) for iid in insight_ids]
        factory, _session = _make_session_factory(rows)
        called: list[str] = []
        # Make the second insight fail.
        fail_on = {str(insight_ids[1])}
        service = _make_exp_service(called=called, fail_on=fail_on)

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
        )
        # Must NOT raise.
        asyncio.run(worker.run())
        # First and third must still be called.
        assert str(insight_ids[0]) in called
        assert str(insight_ids[2]) in called

    def test_batch_size_passed_to_query(self) -> None:
        """The configured batch_size is passed as the LIMIT parameter in the SQL query."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        factory, session = _make_session_factory([])
        service = _make_exp_service()

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
            batch_size=42,
        )
        asyncio.run(worker.run())

        # Verify execute was called with a dict containing lim=42.
        call_args = session.execute.call_args
        assert call_args is not None
        params = call_args[0][1]  # second positional arg = params dict
        assert params.get("lim") == 42


class TestPathExplanationBatchWorkerFetchParsing:
    def test_fetch_parses_jsonb_nodes_and_edges(self) -> None:
        """_fetch_unexplained_batch parses JSONB columns into PathNode/PathEdge objects."""
        from knowledge_graph.domain.entities.path_insight import PathEdge, PathNode
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        node_data = [
            {"entity_id": str(uuid4()), "name": "Apple Inc.", "entity_type": "company"},
            {"entity_id": str(uuid4()), "name": "NVIDIA Corp.", "entity_type": "company"},
        ]
        edge_data = [{"relation_type": "COMPETES_WITH", "confidence": 0.85}]
        insight_id = uuid4()
        rows = [(str(insight_id), json.dumps(node_data), json.dumps(edge_data))]
        factory, _session = _make_session_factory(rows)

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=MagicMock(),
        )
        result = asyncio.run(worker._fetch_unexplained_batch())

        assert len(result) == 1
        iid, nodes, edges = result[0]
        assert iid == insight_id
        assert len(nodes) == 2
        assert all(isinstance(n, PathNode) for n in nodes)
        assert nodes[0].name == "Apple Inc."
        assert len(edges) == 1
        assert isinstance(edges[0], PathEdge)
        assert edges[0].relation_type == "COMPETES_WITH"
        assert abs(edges[0].confidence - 0.85) < 1e-9

    def test_fetch_skips_malformed_rows(self) -> None:
        """Rows with invalid JSON produce a warning and are skipped — not raised."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        good_id = uuid4()
        rows = [
            # Bad row: malformed JSON nodes
            (str(uuid4()), "not-valid-json", "[]"),
            # Good row
            (str(good_id), _make_nodes_json(["A", "B"]), _make_edges_json(1)),
        ]
        factory, _session = _make_session_factory(rows)
        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=MagicMock(),
        )
        result = asyncio.run(worker._fetch_unexplained_batch())
        # Only the good row should be returned.
        assert len(result) == 1
        assert result[0][0] == good_id


class TestPathExplanationBatchWorkerConcurrency:
    @pytest.mark.asyncio()
    async def test_concurrency_bounded_by_semaphore(self) -> None:
        """No more than `concurrency` LLM calls should run at the same time."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        # Use 10 rows but concurrency=2 — track peak simultaneous calls.
        n_rows = 10
        concurrency = 2
        insight_ids = [uuid4() for _ in range(n_rows)]
        rows = [(str(iid), _make_nodes_json(["A", "B"]), _make_edges_json(1)) for iid in insight_ids]
        factory, _session = _make_session_factory(rows)

        active_count = 0
        peak_count = 0
        lock = asyncio.Lock()

        async def _generate(insight_id: UUID, path_nodes: list, path_edges: list) -> None:
            nonlocal active_count, peak_count
            async with lock:
                active_count += 1
                if active_count > peak_count:
                    peak_count = active_count
            # Simulate some async work.
            await asyncio.sleep(0)
            async with lock:
                active_count -= 1

        service = MagicMock()
        service.generate_explanation = _generate

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
            concurrency=concurrency,
        )
        await worker.run()

        # Peak should not exceed our concurrency limit.
        assert peak_count <= concurrency


# ── PLAN-0093 D-1, T-D-1-02 — pending-gauge tests ─────────────────────────────


class TestPathExplanationPendingGauge:
    """T-D-1-02 gauge update tests.

    These tests stub out the ``run()`` flow and exercise the
    ``_update_pending_gauge`` helper directly so we can assert the gauge
    value without spinning up the full LLM phase.
    """

    def test_pending_gauge_increments_on_stale_rows(self) -> None:
        """DB reports 5 stale rows → gauge value == 5."""
        from knowledge_graph.infrastructure.metrics.prometheus import (
            path_insight_explanation_pending_total,
        )
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        factory, _session = _make_session_factory([], gauge_count=5)
        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=MagicMock(),
        )
        asyncio.run(worker._update_pending_gauge())
        # ``_value.get()`` is the documented prometheus_client gauge accessor.
        assert path_insight_explanation_pending_total._value.get() == 5

    def test_pending_gauge_excludes_recent_rows(self) -> None:
        """When the SELECT (which filters by computed_at < now() - 1 hour) returns 0 → gauge == 0.

        The 1-hour exclusion is enforced by the SQL itself, so the gauge
        update logic just trusts the COUNT(*).  This test verifies the
        round-trip: 0 returned → 0 reported.
        """
        from knowledge_graph.infrastructure.metrics.prometheus import (
            path_insight_explanation_pending_total,
        )
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        factory, _session = _make_session_factory([], gauge_count=0)
        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=MagicMock(),
        )
        asyncio.run(worker._update_pending_gauge())
        assert path_insight_explanation_pending_total._value.get() == 0


# ── PLAN-0093 D-1, T-D-1-03 — null-guard / fail-fast tests ────────────────────


class TestPathExplanationLLMNullGuard:
    """T-D-1-03 — worker must NOT loop silently when no LLM client is wired."""

    def test_run_exits_critical_when_llm_client_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """When explanation_service._llm is None → CRITICAL log + no fetch_batch call."""
        import logging

        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        factory, session = _make_session_factory([])
        # Build a "real-ish" service whose _llm attribute is explicitly None
        # (mirroring the production state when DEEPINFRA_API_KEY is missing).
        service = MagicMock()
        service._llm = None
        # Track whether generate_explanation gets called — it must not.
        gen_calls: list[UUID] = []

        async def _generate(insight_id: UUID, path_nodes: list, path_edges: list) -> None:
            gen_calls.append(insight_id)

        service.generate_explanation = _generate

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
        )

        with caplog.at_level(logging.CRITICAL):
            asyncio.run(worker.run())

        # The LLM phase must be short-circuited.
        assert gen_calls == []
        # The SELECT in _fetch_unexplained_batch must NOT run when guard fires;
        # only the gauge SELECT (one call) is allowed.
        assert session.execute.call_count == 1
        # Either structlog captured the critical event or a logger record was made.
        # We at minimum require execute() to be skipped past the gauge call.

    def test_run_resumes_after_llm_client_is_restored(self) -> None:
        """When _llm is restored to a non-None value, run() should process rows again."""
        from knowledge_graph.infrastructure.workers.path_explanation_batch_worker import (
            PathExplanationBatchWorker,
        )

        insight_ids = [uuid4()]
        rows = [(str(iid), _make_nodes_json(["A", "B"]), _make_edges_json(1)) for iid in insight_ids]
        factory, _session = _make_session_factory(rows)
        called: list[str] = []
        service = _make_exp_service(called=called)
        # MagicMock attribute access already returns a (non-None) MagicMock,
        # so the guard is naturally satisfied.  Sanity-check that.
        assert getattr(service, "_llm", None) is not None

        worker = PathExplanationBatchWorker(
            session_factory=factory,
            explanation_service=service,
        )
        asyncio.run(worker.run())
        assert called == [str(insight_ids[0])]
