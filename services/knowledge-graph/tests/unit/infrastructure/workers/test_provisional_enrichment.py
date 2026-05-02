"""Unit tests for ProvisionalEnrichmentWorker (Worker 13E).

Key invariant under test: entity.dirtied.v1 is produced AFTER session.commit(),
not before — so no orphaned Kafka messages if the transaction rolls back.

ARCH-003 fix: run() now uses read→release→I/O→acquire→write pattern.
Phase 1 reads pending rows + marks 'processing' + commits (releases session).
Phase 2 does LLM extraction + embedding outside any session.
Phase 3 opens a new session to persist results + commits.
Tests patch _extract_entity_profile (Phase 2 LLM) and _persist_enrichment (Phase 3 DB).

PLAN-0061 additions:
- retry_count column in SELECT (row index 6)
- max_retries cap: rows at limit transition to 'failed' (terminal)
- batch_limit / concurrency constructor params
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("01234567-89ab-7def-8012-345678901234")
_QUEUE_ID = UUID("01234567-89ab-7def-8012-000000000001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_with_rows(rows: list) -> tuple[AsyncMock, MagicMock]:
    """Return (session, session_factory) with pre-loaded pending-queue rows.

    The factory now returns a fresh context manager each time it's called
    (Phase 1 read + Phase 3 write open separate sessions).  Both sessions
    share the same mock so assertions work across phases.
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows

    session.execute = AsyncMock(return_value=result_mock)

    def _make_cm():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    factory = MagicMock(side_effect=lambda: _make_cm())
    return session, factory


def _make_producer() -> MagicMock:
    producer = MagicMock()
    producer.produce_bytes = MagicMock()
    return producer


def _make_pending_row(retry_count: int = 0) -> tuple:
    """Return a fake DB row matching the SELECT column order (incl. retry_count)."""
    return (
        str(_QUEUE_ID),  # queue_id
        "Apple Inc.",  # mention_text
        "apple inc.",  # normalized_surface
        "financial_instrument",  # mention_class
        "Apple is a tech company",  # context_snippet
        None,  # source_doc_id
        retry_count,  # retry_count (PLAN-0061 T-A-3)
    )


# ---------------------------------------------------------------------------
# Original tests (unchanged behaviour, constructor gains keyword-only defaults)
# ---------------------------------------------------------------------------


class TestProvisionalEnrichmentWorkerNoPendingRows:
    async def test_no_pending_rows_no_produce(self) -> None:
        """When no pending rows, producer.produce_bytes is never called."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)
        await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_no_pending_rows_still_commits(self) -> None:
        """run() commits in Phase 1 (read) even with no rows to process."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)
        await worker.run()

        # Phase 1 commits even when there are no rows (releases FOR UPDATE lock)
        assert session.commit.call_count >= 1


class TestProvisionalEnrichmentWorkerPostCommitOrdering:
    async def test_dirtied_produced_after_commit(self) -> None:
        """entity.dirtied.v1 is produced AFTER Phase 3 session.commit(), never before."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        commit_called_at: list[int] = []
        produce_called_at: list[int] = []
        call_counter: list[int] = [0]

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        original_commit = session.commit

        async def _tracked_commit():
            call_counter[0] += 1
            commit_called_at.append(call_counter[0])
            await original_commit()

        session.commit = _tracked_commit

        def _tracked_produce(**kwargs: object) -> None:
            call_counter[0] += 1
            produce_called_at.append(call_counter[0])

        producer.produce_bytes = _tracked_produce

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        # Patch Phase 2 (LLM) and Phase 3 (DB persist) methods
        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
        ):
            await worker.run()

        # Phase 1 commit + Phase 3 commit = 2 commits
        assert len(commit_called_at) == 2
        assert len(produce_called_at) == 1
        # Produce must happen after the LAST commit (Phase 3)
        assert (
            commit_called_at[-1] < produce_called_at[0]
        ), "entity.dirtied.v1 must be produced AFTER Phase 3 commit, not before"

    async def test_commit_failure_suppresses_produce(self) -> None:
        """When Phase 3 commit raises, producer.produce_bytes is never called."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        # Make the second commit (Phase 3) fail; first commit (Phase 1) succeeds.
        commit_count = [0]
        original_commit = session.commit

        async def _fail_on_phase3():
            commit_count[0] += 1
            if commit_count[0] >= 2:  # Phase 3 commit
                raise RuntimeError("DB write failed")
            await original_commit()

        session.commit = _fail_on_phase3

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
        ):
            with pytest.raises(RuntimeError, match="DB write failed"):
                await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_dirty_payload_contains_entity_id(self) -> None:
        """Produced entity.dirtied.v1 payload includes the entity_id."""
        import json

        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(
            factory, AsyncMock(), direct_producer=producer, entity_dirtied_topic="entity.dirtied.v1"
        )

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
        ):
            await worker.run()

        producer.produce_bytes.assert_called_once()
        kwargs = producer.produce_bytes.call_args.kwargs
        assert kwargs["topic"] == "entity.dirtied.v1"
        assert kwargs["key"] == str(_ENTITY_ID).encode()
        payload = json.loads(kwargs["value"])
        assert payload["entity_id"] == str(_ENTITY_ID)

    async def test_multiple_entities_all_produced_after_commit(self) -> None:
        """All dirty IDs accumulated before commit — then produced in batch after."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        entity_id_1 = UUID("01234567-89ab-7def-8012-aaaaaaaaaaaa")
        entity_id_2 = UUID("01234567-89ab-7def-8012-bbbbbbbbbbbb")
        rows = [_make_pending_row(), _make_pending_row()]

        session, factory = _make_session_with_rows(rows)
        producer = _make_producer()

        call_order: list[str] = []
        original_commit = session.commit

        async def _track_commit():
            call_order.append("commit")
            await original_commit()

        session.commit = _track_commit

        def _track_produce(**kwargs: object) -> None:
            call_order.append("produce")

        producer.produce_bytes = _track_produce

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        # Phase 2: extract returns profiles for both rows
        extract_profiles = [
            {"canonical_name": "Apple", "entity_type": "financial_instrument"},
            {"canonical_name": "Google", "entity_type": "financial_instrument"},
        ]
        # Phase 3: persist returns different entity IDs for the two rows
        persist_ids = [entity_id_1, entity_id_2]

        with (
            patch.object(worker, "_extract_entity_profile", side_effect=extract_profiles),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", side_effect=persist_ids),
        ):
            await worker.run()

        # Last commit (Phase 3) appears before both produces
        last_commit_idx = len(call_order) - 1 - call_order[::-1].index("commit")
        produce_indices = [i for i, v in enumerate(call_order) if v == "produce"]
        assert len(produce_indices) == 2
        assert all(last_commit_idx < idx for idx in produce_indices)


class TestProvisionalEnrichmentWorkerFailedEnrichment:
    async def test_llm_failure_skips_dirty_produce(self) -> None:
        """When _extract_entity_profile returns None (LLM failed), no dirty event is produced."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with patch.object(worker, "_extract_entity_profile", return_value=None):
            await worker.run()

        producer.produce_bytes.assert_not_called()

    async def test_enrichment_exception_skips_dirty_produce(self) -> None:
        """When _extract_entity_profile raises, the row is logged as failed, not dirtied."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with patch.object(worker, "_extract_entity_profile", side_effect=RuntimeError("LLM timeout")):
            # run() should NOT re-raise — it logs and continues
            await worker.run()

        producer.produce_bytes.assert_not_called()


class TestProvisionalEnrichmentWorkerNoProducer:
    async def test_none_producer_completes_without_error(self) -> None:
        """When direct_producer=None, run() completes without AttributeError."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=None)

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
        ):
            # Should not raise even though producer is None
            await worker.run()


# ---------------------------------------------------------------------------
# PLAN-0061 T-A-3: retry cap + terminal 'failed' status
# ---------------------------------------------------------------------------


class TestRetryCapAndFailedStatus:
    async def test_retry_cap_transitions_to_failed(self) -> None:
        """Row at max_retries-1 + LLM None → Phase 3 UPDATE sets status='failed'.

        T-A-3: After retry_count+1 >= max_retries the row must become terminal.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # retry_count=4, max_retries=5 → next count (5) >= 5 → 'failed'
        session, factory = _make_session_with_rows([_make_pending_row(retry_count=4)])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch(
                # patch where the name is used (already imported at module level)
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total"
            ) as mock_counter,
        ):
            await worker.run()

        # Verify that the Phase 3 execute was called with SQL containing 'failed'
        execute_calls = session.execute.call_args_list
        failed_calls = [c for c in execute_calls if "failed" in str(c.args[0] if c.args else "")]
        assert len(failed_calls) >= 1, "Expected an UPDATE setting status='failed'"
        mock_counter.inc.assert_called_once()

    async def test_retry_below_cap_stays_pending(self) -> None:
        """Row below max_retries + LLM None → status stays 'pending' (not 'failed').

        T-A-3: Row with retry_count=2 < max_retries=5 should be re-queued.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # retry_count=2, max_retries=5 → next count (3) < 5 → 'pending'
        session, factory = _make_session_with_rows([_make_pending_row(retry_count=2)])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total"
            ) as mock_counter,
        ):
            await worker.run()

        execute_calls = session.execute.call_args_list
        # Must NOT have any 'failed' update
        failed_calls = [c for c in execute_calls if "failed" in str(c.args[0] if c.args else "")]
        assert len(failed_calls) == 0, "Row below cap must NOT be set to 'failed'"
        # pending update must be present
        pending_calls = [c for c in execute_calls if "pending" in str(c.args[0] if c.args else "")]
        assert len(pending_calls) >= 1, "Row below cap must be reset to 'pending'"
        mock_counter.inc.assert_not_called()

    async def test_phase1_select_includes_max_retries_param(self) -> None:
        """Phase 1 SELECT passes max_retries to the WHERE clause.

        T-A-3: The SQL must gate on retry_count < :max_retries so exhausted
        rows are never fetched again.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=7)
        await worker.run()

        # Phase 1 execute call params must include max_retries=7
        execute_calls = session.execute.call_args_list
        select_params = [
            c.args[1]
            for c in execute_calls
            if len(c.args) > 1 and isinstance(c.args[1], dict) and "max_retries" in c.args[1]
        ]
        assert select_params, "Phase 1 SELECT must pass max_retries as a SQL parameter"
        assert select_params[0]["max_retries"] == 7


# ---------------------------------------------------------------------------
# PLAN-0061 T-A-4: configurable batch_limit + concurrent Phase 2
# ---------------------------------------------------------------------------


class TestBatchLimitAndConcurrency:
    async def test_batch_limit_passed_to_select(self) -> None:
        """Phase 1 SELECT passes batch_limit as the LIMIT parameter.

        T-A-4: The hardcoded constant _BATCH_LIMIT is gone; the constructor
        param drives the query.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), batch_limit=15)
        await worker.run()

        execute_calls = session.execute.call_args_list
        limit_params = [
            c.args[1] for c in execute_calls if len(c.args) > 1 and isinstance(c.args[1], dict) and "limit" in c.args[1]
        ]
        assert limit_params, "Phase 1 SELECT must pass batch_limit via 'limit' param"
        assert limit_params[0]["limit"] == 15

    async def test_concurrency_limits_simultaneous_llm_calls(self) -> None:
        """Phase 2 never exceeds `concurrency` simultaneous _extract_entity_profile calls.

        T-A-4: asyncio.gather with a semaphore must cap inflight LLM calls.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # 10 rows, concurrency=3 → at most 3 extract calls active at any instant.
        rows = [_make_pending_row() for _ in range(10)]
        _session, factory = _make_session_with_rows(rows)

        active = [0]
        max_seen = [0]

        async def _mock_extract(*_args: object, **_kwargs: object) -> dict:
            active[0] += 1
            max_seen[0] = max(max_seen[0], active[0])
            await asyncio.sleep(0)  # yield so other coroutines can enter
            active[0] -= 1
            return {"canonical_name": "Ent", "entity_type": "org"}

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), concurrency=3)

        with (
            patch.object(worker, "_extract_entity_profile", side_effect=_mock_extract),
            patch.object(worker, "_compute_embedding", return_value=None),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
        ):
            await worker.run()

        assert max_seen[0] <= 3, f"Max concurrent calls was {max_seen[0]}, expected ≤ 3"
