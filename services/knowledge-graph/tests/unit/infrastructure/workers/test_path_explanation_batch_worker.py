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


def _make_session_factory(rows: list[tuple]) -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory that returns the given rows from execute()."""
    result_mock = MagicMock()
    result_mock.fetchall = MagicMock(return_value=rows)

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
