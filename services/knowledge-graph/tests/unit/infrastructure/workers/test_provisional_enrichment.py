"""Unit tests for ProvisionalEnrichmentWorker (Worker 13E).

Key invariant under test: entity.dirtied.v1 is enqueued to the outbox AFTER
session.commit(), not before — so no orphaned events if the transaction rolls back.

D-014 (PLAN-0084 QA fix): entity.dirtied.v1 now uses the durable outbox pattern
(OutboxRepository.append) instead of fire-and-forget direct Kafka produce.  Tests
that previously asserted on producer.produce_bytes now assert on
OutboxRepository.append (patched via the module import path).

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
from structlog.testing import capture_logs

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
    # rowcount defaults to 0 so the B-7 recovery sweep doesn't accidentally
    # trip the s7_provisional_stuck_recovered_total counter increment in
    # tests that don't care about the recovery path.
    result_mock.rowcount = 0

    session.execute = AsyncMock(return_value=result_mock)

    def _make_cm():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    factory = MagicMock(side_effect=lambda: _make_cm())
    return session, factory


def _make_producer() -> MagicMock:
    # D-014: direct_producer is deprecated; kept for constructor backward-compat.
    # Tests that formerly tracked produce_bytes now patch OutboxRepository.append.
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
    async def test_no_pending_rows_no_outbox_append(self) -> None:
        """When no pending rows, OutboxRepository.append is never called.

        D-014: outbox replaces direct produce; with an empty batch the outbox
        transaction block is skipped entirely.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())
        with patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls:
            mock_outbox_cls.return_value.append = AsyncMock()
            await worker.run()

        mock_outbox_cls.return_value.append.assert_not_called()

    async def test_no_pending_rows_still_commits(self) -> None:
        """run() commits in Phase 1 (read) even with no rows to process."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())
        await worker.run()

        # Phase 1 commits even when there are no rows (releases FOR UPDATE lock)
        assert session.commit.call_count >= 1


class TestProvisionalEnrichmentWorkerPostCommitOrdering:
    async def test_dirtied_enqueued_after_commit(self) -> None:
        """entity.dirtied.v1 outbox row is written AFTER Phase 3 session.commit().

        D-014: the outbox INSERT for entity.dirtied.v1 now happens in a separate
        outbox session opened after all per-row Phase 3 commits complete.

        Call order:
          recovery-commit (1), Phase1-commit (2), Phase3-commit (3),
          outbox-append (4), outbox-commit (5).

        We verify that outbox-append (4) comes after Phase3-commit (3).
        The shared session mock means all commits (including the outbox session
        commit) are tracked together; we therefore assert append > 3rd commit.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        commit_called_at: list[int] = []
        outbox_called_at: list[int] = []
        call_counter: list[int] = [0]

        session, factory = _make_session_with_rows([_make_pending_row()])

        original_commit = session.commit

        async def _tracked_commit():
            call_counter[0] += 1
            commit_called_at.append(call_counter[0])
            await original_commit()

        session.commit = _tracked_commit

        # Patch OutboxRepository.append to track call ordering.
        async def _tracked_append(*_args: object, **_kwargs: object) -> None:
            call_counter[0] += 1
            outbox_called_at.append(call_counter[0])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        # Patch Phase 2 (LLM) and Phase 3 (DB persist) methods
        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=_tracked_append)
            await worker.run()

        # recovery-commit + Phase1-commit + Phase3-commit = 3 commits before outbox append
        assert len(outbox_called_at) == 1
        assert len(commit_called_at) >= 3
        # The 3rd commit is Phase 3; outbox append must come after it.
        phase3_commit_pos = commit_called_at[2]  # index 2 = 3rd commit
        assert phase3_commit_pos < outbox_called_at[0], (
            "entity.dirtied.v1 outbox row must be written AFTER Phase 3 commit, not before. "
            f"Phase3-commit at {phase3_commit_pos}, outbox-append at {outbox_called_at[0]}"
        )

    async def test_commit_failure_suppresses_outbox(self) -> None:
        """When Phase 3 commit raises, OutboxRepository.append is never called.

        BP-390 (per-row session fix): the RuntimeError is now caught inside the
        per-row except block and handled gracefully (retry update attempted),
        so worker.run() no longer raises.  The critical invariant remains:
        the outbox INSERT must NOT happen when the entity commit failed (the
        entity_id is not added to entity_ids_to_dirty).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        session, factory = _make_session_with_rows([_make_pending_row()])

        # Recovery sweep commit (1) + Phase 1 commit (2) succeed; Phase 3 (3) fails.
        commit_count = [0]
        original_commit = session.commit

        async def _fail_on_phase3():
            commit_count[0] += 1
            if commit_count[0] >= 3:  # Phase 3 commit
                raise RuntimeError("DB write failed")
            await original_commit()

        session.commit = _fail_on_phase3

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock()
            # Per-row session isolation: commit failure is caught and suppressed.
            await worker.run()

        # Outbox INSERT must NOT be called — entity commit failed, no dirty ID.
        mock_outbox_cls.return_value.append.assert_not_called()

    async def test_dirty_outbox_payload_contains_entity_id(self) -> None:
        """Outbox row for entity.dirtied.v1 contains valid Confluent-Avro payload.

        D-014: the outbox append receives (topic, partition_key, payload_avro).
        Verify the payload is valid Confluent-Avro with the correct entity_id.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            _ENTITY_DIRTIED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), entity_dirtied_topic="entity.dirtied.v1")

        captured_calls: list[dict] = []

        async def _capture_append(
            topic: str, partition_key: str, payload_avro: bytes, *, event_id: object = None
        ) -> None:
            captured_calls.append({"topic": topic, "partition_key": partition_key, "payload_avro": payload_avro})

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=_capture_append)
            await worker.run()

        assert len(captured_calls) == 1, f"Expected 1 outbox append, got {len(captured_calls)}"
        call = captured_calls[0]
        assert call["topic"] == "entity.dirtied.v1"
        assert call["partition_key"] == str(_ENTITY_ID)
        raw = call["payload_avro"]
        assert raw[:1] == b"\x00", "Expected Confluent-Avro wire format (magic byte 0x00)"
        payload = deserialize_confluent_avro(_ENTITY_DIRTIED_SCHEMA_PATH, raw)
        assert payload["entity_id"] == str(_ENTITY_ID)

    async def test_multiple_entities_all_enqueued_after_commits(self) -> None:
        """All dirty IDs are accumulated across per-row Phase 3 commits, then
        written to the outbox in one batch after all rows are processed.

        D-014: one outbox session is opened for the entire batch of dirty IDs
        (not one session per entity).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        entity_id_1 = UUID("01234567-89ab-7def-8012-aaaaaaaaaaaa")
        entity_id_2 = UUID("01234567-89ab-7def-8012-bbbbbbbbbbbb")
        rows = [_make_pending_row(), _make_pending_row()]

        _session, factory = _make_session_with_rows(rows)

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        partition_keys_appended: list[str] = []

        async def _capture_append(
            topic: str, partition_key: str, payload_avro: bytes, *, event_id: object = None
        ) -> None:
            partition_keys_appended.append(partition_key)

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
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=_capture_append)
            await worker.run()

        # Both entity IDs must have been enqueued to the outbox.
        assert str(entity_id_1) in partition_keys_appended
        assert str(entity_id_2) in partition_keys_appended
        assert len(partition_keys_appended) == 2


class TestProvisionalEnrichmentWorkerFailedEnrichment:
    async def test_llm_failure_skips_dirty_outbox(self) -> None:
        """When _extract_entity_profile returns None (LLM failed), no outbox row is written.

        D-014: no entity_id is added to entity_ids_to_dirty, so the outbox
        transaction block is skipped entirely.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock()
            await worker.run()

        mock_outbox_cls.return_value.append.assert_not_called()

    async def test_enrichment_exception_skips_dirty_outbox(self) -> None:
        """When _extract_entity_profile raises, the row is logged as failed, not dirtied.

        D-014: no entity_id is added to entity_ids_to_dirty on exception path.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(worker, "_extract_entity_profile", side_effect=RuntimeError("LLM timeout")),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock()
            # run() should NOT re-raise — it logs and continues
            await worker.run()

        mock_outbox_cls.return_value.append.assert_not_called()


class TestProvisionalEnrichmentWorkerNoProducer:
    async def test_none_producer_completes_without_error(self) -> None:
        """When direct_producer=None, run() completes without AttributeError.

        D-014: direct_producer is deprecated and no longer used in run().
        Passing None is always safe — entity.dirtied.v1 goes through the outbox.
        """
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
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock()
            # Should not raise even though producer is None
            await worker.run()


# ---------------------------------------------------------------------------
# PLAN-0061 T-A-3: retry cap + terminal 'failed' status
# ---------------------------------------------------------------------------


class TestRetryCapAndFailedStatus:
    async def test_retry_cap_transitions_to_failed(self) -> None:
        """Row at max_retries-1 + LLM None → atomic CASE returns is_terminal=True → counter increments.

        T-A-3: After retry_count+1 >= max_retries the row must become terminal.
        Wave-B-2026-05-03 refactor: ``apply_retry_transition`` is now a single
        atomic ``UPDATE ... CASE ... RETURNING (status='failed')`` so we drive
        the test by setting the ``fetchone()`` return value (the RETURNING row)
        rather than introspecting the SQL string (both 'failed' and 'pending'
        literals appear in the CASE expression at all times).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # retry_count=4, max_retries=5 → next count (5) >= 5 → CASE='failed' → RETURNING is_terminal=True
        session, factory = _make_session_with_rows([_make_pending_row(retry_count=4)])
        # Simulate the DB returning is_terminal=True from the RETURNING clause.
        session.execute.return_value.fetchone.return_value = (True,)

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch(
                # patch where the name is used (already imported at module level)
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total",
            ) as mock_counter,
        ):
            await worker.run()

        mock_counter.inc.assert_called_once()

    async def test_retry_below_cap_stays_pending(self) -> None:
        """Row below max_retries + LLM None → atomic CASE returns is_terminal=False → counter NOT called.

        T-A-3: Row with retry_count=2 < max_retries=5 should be re-queued.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # retry_count=2, max_retries=5 → next count (3) < 5 → CASE='pending' → RETURNING is_terminal=False
        session, factory = _make_session_with_rows([_make_pending_row(retry_count=2)])
        session.execute.return_value.fetchone.return_value = (False,)

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total",
            ) as mock_counter,
        ):
            await worker.run()

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


# ---------------------------------------------------------------------------
# P-3: Kafka emit failure must not crash the worker
# ---------------------------------------------------------------------------


class TestProvisionalEnrichmentWorkerOutboxResilience:
    """D-014: outbox append failure must not crash the worker (same resilience as
    the former fire-and-forget path)."""

    async def test_outbox_error_does_not_crash(self) -> None:
        """OutboxRepository.append raising must not propagate out of run() (P-3)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=RuntimeError("outbox DB error"))
            # Must not raise even though outbox append raises
            await worker.run()

    async def test_outbox_error_logs_warning(self) -> None:
        """OutboxRepository.append raising emits provisional_enrichment_dirtied_outbox_failed warning."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.logger") as mock_logger,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=RuntimeError("outbox DB error"))
            await worker.run()

        warning_events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "provisional_enrichment_dirtied_outbox_failed" in warning_events


# ---------------------------------------------------------------------------
# P-5: Success counter increments on enriched rows
# ---------------------------------------------------------------------------


class TestProvisionalEnrichmentSuccessCounter:
    async def test_success_counter_increments_once_per_enriched_row(self) -> None:
        """s7_provisional_enrichment_success_total.inc() is called once per resolved row (P-5)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_success_total",
            ) as mock_counter,
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock()
            await worker.run()

        mock_counter.inc.assert_called_once()

    async def test_success_counter_not_incremented_on_llm_failure(self) -> None:
        """s7_provisional_enrichment_success_total.inc() is NOT called when LLM returns None (P-5)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(worker, "_extract_entity_profile", return_value=None),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_success_total",
            ) as mock_counter,
        ):
            await worker.run()

        mock_counter.inc.assert_not_called()


# ---------------------------------------------------------------------------
# P-1: direct_producer is deprecated (D-014) — no init warning any more
# ---------------------------------------------------------------------------


class TestDirectProducerBackwardCompat:
    """D-014: direct_producer is accepted for backward-compat but is no longer
    used in run().  No init-time warning is emitted; the entity.dirtied.v1 event
    goes through the outbox regardless of whether direct_producer is provided."""

    def test_none_producer_no_warning_at_init(self) -> None:
        """direct_producer=None must NOT log a warning at init time (D-014).

        Previously a warning was logged; now the parameter is silently accepted
        because it is deprecated and the outbox handles delivery.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])

        with capture_logs() as cap:
            ProvisionalEnrichmentWorker(
                session_factory=factory,
                llm_client=AsyncMock(),
                direct_producer=None,
            )

        assert not any(
            e.get("event") == "provisional_enrichment_worker_no_producer" for e in cap
        ), f"Unexpected no_producer warning found: {cap}"

    def test_producer_present_no_warning_at_init(self) -> None:
        """direct_producer provided must also produce no 'no_producer' warning."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])

        with capture_logs() as cap:
            ProvisionalEnrichmentWorker(
                session_factory=factory,
                llm_client=AsyncMock(),
                direct_producer=MagicMock(),
            )

        assert not any(
            e.get("event") == "provisional_enrichment_worker_no_producer" for e in cap
        ), f"Unexpected no_producer warning found in: {cap}"


# ---------------------------------------------------------------------------
# B-2: embed model default must not be "nomic-embed-text" (768-dim vs 1024)
# ---------------------------------------------------------------------------


class TestEmbedModelIdDefault:
    def test_embed_model_id_is_not_nomic_embed_text(self) -> None:
        """Default embed_model_id must not be 'nomic-embed-text' (produces 768-dim vectors).

        B-2 fix: entity_embedding_state.embedding is vector(1024). Using
        nomic-embed-text causes a FatalError on every provisional embed call.
        The correct default is a 1024-dim model such as 'bge-large:latest'.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
        )

        assert worker._embed_model_id != "nomic-embed-text", (
            f"Default embed model '{worker._embed_model_id}' is nomic-embed-text, "
            "which produces 768-dim vectors incompatible with vector(1024) column"
        )
        # Assert the model is a known 1024-dim model.
        assert worker._embed_model_id in {
            "bge-large:latest",
            "BAAI/bge-large-en-v1.5",
        }, f"Default embed model '{worker._embed_model_id}' is not a known 1024-dim model"


# ---------------------------------------------------------------------------
# B-3: entity.dirtied.v1 payload must include all required Avro fields
# ---------------------------------------------------------------------------


class TestDirtiedEventPayload:
    def test_dirtied_event_includes_all_avro_fields(self) -> None:
        """_build_dirtied_event() must produce valid Confluent-Avro with all required fields.

        B-3 fix: previously callers emitted {"entity_id": "<uuid>"} which is
        missing event_id, event_type, schema_version, occurred_at, dirty_reason
        — all required by infra/kafka/schemas/entity.dirtied.v1.avsc.

        PLAN-0062 R28 update: _build_dirtied_event now emits Confluent-Avro
        wire-format bytes (5-byte header + Avro body), not JSON. Test updated
        to decode via deserialize_confluent_avro.
        """
        from uuid import uuid4

        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            _ENTITY_DIRTIED_SCHEMA_PATH,
            _build_dirtied_event,
        )

        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        entity_id = _ENTITY_ID
        raw = _build_dirtied_event(entity_id, event_id=uuid4())

        # Must start with Confluent magic byte 0x00
        assert raw[:1] == b"\x00", "Expected Confluent-Avro wire format (magic byte 0x00)"

        payload = deserialize_confluent_avro(_ENTITY_DIRTIED_SCHEMA_PATH, raw)

        # All required Avro fields must be present.
        required_fields = {"event_id", "event_type", "schema_version", "occurred_at", "entity_id", "dirty_reason"}
        missing = required_fields - payload.keys()
        assert not missing, f"Missing required Avro fields: {missing}"

        assert (
            payload["event_type"] == "entity.dirtied"
        ), f"event_type must be 'entity.dirtied', got '{payload['event_type']}'"
        assert payload["schema_version"] == 1, f"schema_version must be 1, got {payload['schema_version']}"
        assert payload["entity_id"] == str(entity_id), f"entity_id must be '{entity_id}', got '{payload['entity_id']}'"
        assert (
            payload["dirty_reason"] == "profile_updated"
        ), f"Default dirty_reason must be 'profile_updated', got '{payload['dirty_reason']}'"
        # Optional fields should also be present (nullable in Avro).
        assert "source_doc_id" in payload
        assert "correlation_id" in payload


# ---------------------------------------------------------------------------
# B-7: recovery sweep for rows stuck in 'processing'
# ---------------------------------------------------------------------------


class TestRecoverStaleProcessingRows:
    async def test_recover_stale_processing_rows_resets_to_pending(self) -> None:
        """_recover_stale_processing_rows() issues UPDATE resetting stuck rows to 'pending'.

        B-7 fix: rows stuck in 'processing' after a crash are never retried
        because Phase 1 SELECT only queries WHERE status = 'pending'.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        # Set up a session where execute() returns rowcount=3.
        session = AsyncMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 3
        session.execute = AsyncMock(return_value=result_mock)

        recovered = await worker._recover_stale_processing_rows(session)

        assert recovered == 3, f"Expected 3 recovered rows, got {recovered}"

        # The UPDATE SQL must reference 'processing' and pass max_retries.
        session.execute.assert_awaited_once()
        call_args = session.execute.call_args
        sql_text = str(call_args.args[0])
        assert "processing" in sql_text, "SQL must filter on status = 'processing'"
        params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("parameters", {})
        assert "max_retries" in params, "SQL must pass max_retries parameter"
        assert params["max_retries"] == 5

        session.commit.assert_awaited_once()

    async def test_recovery_uses_processing_started_at_coalesce(self) -> None:
        """D-016: recovery WHERE clause must use COALESCE(processing_started_at, created_at).

        Using ``created_at`` alone causes false recovery of recently-started rows
        that have been in the queue for a long time (BP-417).  The COALESCE falls
        back to ``created_at`` for rows that pre-date the migration (NULL column).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), max_retries=5)

        session = AsyncMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute = AsyncMock(return_value=result_mock)

        await worker._recover_stale_processing_rows(session)

        call_args = session.execute.call_args
        sql_text = str(call_args.args[0])
        assert "COALESCE(processing_started_at, created_at)" in sql_text, (
            "Recovery WHERE clause must use COALESCE(processing_started_at, created_at) "
            "to avoid false recovery of recently-started rows (D-016 / BP-417). "
            f"Actual SQL: {sql_text}"
        )

    async def test_recovery_sweep_sets_next_retry_at(self) -> None:
        """The recovery UPDATE must persist a ``next_retry_at`` deadline so that
        recovered rows respect the same exponential backoff as rows that fail
        the regular code path.  Without this, a recovered row would be re-claimed
        immediately on the next polling tick and bypass the backoff window.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            factory,
            AsyncMock(),
            max_retries=5,
            base_retry_minutes=7,  # arbitrary non-default
            max_retry_minutes=42,  # arbitrary non-default
        )

        session = AsyncMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute = AsyncMock(return_value=result_mock)

        await worker._recover_stale_processing_rows(session)

        # The UPDATE SQL must touch next_retry_at AND bind the configured
        # backoff window so the recovered row's deadline matches the operator
        # configuration — not the function defaults.
        session.execute.assert_awaited_once()
        call_args = session.execute.call_args
        sql_text = str(call_args.args[0])
        assert "next_retry_at" in sql_text, (
            "Recovery UPDATE must set next_retry_at — recovered rows would "
            "otherwise bypass the exponential backoff window."
        )
        params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("parameters", {})
        assert params["base_minutes"] == 7
        assert params["max_minutes"] == 42
        assert "now" in params, "Recovery UPDATE must bind :now from common.time.utc_now()"

    async def test_run_calls_recovery_before_processing(self) -> None:
        """run() calls _recover_stale_processing_rows before fetching pending rows.

        B-7 fix: the recovery sweep must happen at the start of every run()
        cycle to unblock stuck rows.
        """
        from unittest.mock import patch as _patch

        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        call_order: list[str] = []

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        async def _mock_recover(session: object) -> int:
            call_order.append("recover")
            return 0

        async def _mock_fetch_pending(session: object) -> list:  # type: ignore[return]
            call_order.append("fetch_pending")
            return []

        with (
            _patch.object(worker, "_recover_stale_processing_rows", side_effect=_mock_recover),
            _patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.ProvisionalEnrichmentWorker._recover_stale_processing_rows",
                side_effect=_mock_recover,
            ),
        ):
            await worker.run()

        # _recover_stale_processing_rows must have been called exactly once.
        assert call_order.count("recover") == 1, f"Expected 1 recovery call, got {call_order.count('recover')}"


# ---------------------------------------------------------------------------
# PLAN-0072 T-72-1-01 — two-layer noise pre-filter
# ---------------------------------------------------------------------------


def _make_noise_row(mention_text: str, retry_count: int = 0) -> tuple:
    return (
        str(UUID("01234567-89ab-7def-8012-aaaaaaaaaaaa")),
        mention_text,
        mention_text.lower(),
        "financial_instrument",
        "some context",
        None,
        retry_count,
    )


class TestNoiseFilters:
    """Tests for _run_noise_filters() and _layer2_classify() (PLAN-0072 T-72-1-01)."""

    def _make_worker(self, noise_api_key: str = "") -> ProvisionalEnrichmentWorker:
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        return ProvisionalEnrichmentWorker(
            factory,
            AsyncMock(),
            noise_classifier_api_key=noise_api_key,
        )

    async def test_layer1_blocklist_marks_noise_no_llm_calls(self) -> None:
        """Layer 1 blocklist hit → noise ID returned; _layer2_classify never called."""
        from uuid import UUID

        worker = self._make_worker(noise_api_key="fake-key")
        rows = [
            (UUID("01234567-89ab-7def-8012-000000000001"), "he", "financial_instrument", "", 0),
        ]

        with patch.object(worker, "_layer2_classify", new=AsyncMock()) as mock_l2:
            l1, l2, remaining = await worker._run_noise_filters(rows)

        assert len(l1) == 1
        assert rows[0][0] in l1
        assert l2 == []
        assert remaining == []
        mock_l2.assert_not_called()

    async def test_blocklist_case_insensitive(self) -> None:
        """Layer 1 check is case-insensitive — 'ANALYSTS' matches the blocklist."""
        from uuid import UUID

        worker = self._make_worker()
        rows = [
            (UUID("01234567-89ab-7def-8012-000000000002"), "ANALYSTS", "financial_instrument", "", 0),
        ]

        l1, _l2, remaining = await worker._run_noise_filters(rows)

        assert len(l1) == 1
        assert remaining == []

    async def test_layer2_not_entity_marks_noise(self) -> None:
        """Layer 1 passes; Layer 2 returns is_entity=false → noise, Layer 3 not reached."""
        from uuid import UUID

        worker = self._make_worker(noise_api_key="fake-key")
        qid = UUID("01234567-89ab-7def-8012-000000000003")
        rows = [(qid, "generic phrase", "financial_instrument", "", 0)]

        with patch.object(worker, "_layer2_classify", new=AsyncMock(return_value=True)):
            l1, l2, remaining = await worker._run_noise_filters(rows)

        assert l1 == []
        assert qid in l2
        assert remaining == []

    async def test_layer2_low_confidence_marks_noise(self) -> None:
        """Confidence < 0.7 → noise even when is_entity field might be true.

        _layer2_classify encapsulates the confidence check and returns True for noise.
        We test _layer2_classify directly with a mocked HTTP response.
        """
        import json as _json
        from unittest.mock import MagicMock

        worker = self._make_worker(noise_api_key="fake-key")

        # Inject a pre-created http client with a mock post method.
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": _json.dumps({"is_entity": True, "confidence": 0.5})}}],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        worker._noise_http_client = mock_client

        result = await worker._layer2_classify("constant currency")
        assert result is True  # confidence 0.5 < 0.7 → noise

    async def test_confirmed_entity_reaches_layer3(self) -> None:
        """'Apple Inc.' with high confidence passes both layers → goes to Layer 3."""
        from uuid import UUID

        worker = self._make_worker(noise_api_key="fake-key")
        qid = UUID("01234567-89ab-7def-8012-000000000005")
        rows = [(qid, "Apple Inc.", "financial_instrument", "", 0)]

        # Layer 2 returns False (= not noise)
        with patch.object(worker, "_layer2_classify", new=AsyncMock(return_value=False)):
            l1, l2, remaining = await worker._run_noise_filters(rows)

        assert l1 == []
        assert l2 == []
        assert len(remaining) == 1 and remaining[0][0] == qid

    async def test_layer2_failure_falls_through_to_layer3(self) -> None:
        """Layer 2 HTTP exception → fail-open (_layer2_classify returns False, no silent drop)."""
        import httpx

        worker = self._make_worker(noise_api_key="fake-key")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        worker._noise_http_client = mock_client

        result = await worker._layer2_classify("valid entity")
        assert result is False  # fail-open: error → pass to Layer 3

    async def test_noise_batch_update_issued_for_blocklist_row(self) -> None:
        """F-QA-001: run() issues a batch UPDATE with ANY(CAST(:ids AS uuid[])) for noise rows.

        Verifies that the DB write path actually executes the single-batch UPDATE
        SQL (not N individual per-row UPDATEs) when a blocklist mention is processed.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        # Row with a blocklist mention — will be caught by Layer 1.
        noise_row = _make_noise_row("analysts")
        session, factory = _make_session_with_rows([noise_row])

        worker = ProvisionalEnrichmentWorker(
            factory,
            AsyncMock(),
            noise_classifier_api_key="",  # no Layer 2 key; Layer 1 suffices
        )

        await worker.run()

        # Collect all SQL strings sent to session.execute across all sessions.
        execute_calls = session.execute.call_args_list
        sql_strings = [str(call.args[0]) for call in execute_calls if call.args]

        # The batch noise UPDATE must have been issued.
        noise_update_calls = [s for s in sql_strings if "status = 'noise'" in s and "ANY(CAST(:ids AS uuid[]))" in s]
        assert noise_update_calls, (
            "Expected a batch UPDATE with status='noise' and ANY(CAST(:ids AS uuid[])) "
            f"but got SQL strings: {sql_strings}"
        )

        # The params must include the noise queue_id converted to a string list.
        noise_update_params = [
            call.args[1]
            for call in execute_calls
            if call.args
            and "status = 'noise'" in str(call.args[0])
            and "ANY(CAST(:ids AS uuid[]))" in str(call.args[0])
            and len(call.args) > 1
        ]
        assert noise_update_params, "Batch noise UPDATE must pass :ids parameter"
        ids_param = noise_update_params[0].get("ids", [])
        assert len(ids_param) == 1, f"Expected 1 noise ID, got {ids_param}"


# ---------------------------------------------------------------------------
# F-QA-201: aclose() lifecycle
# ---------------------------------------------------------------------------


class TestAcloseLifecycle:
    """aclose() must be a no-op when no HTTP client was created, and close when present."""

    @pytest.mark.asyncio()
    async def test_aclose_when_no_client_is_noop(self) -> None:
        """aclose() with no HTTP client created should not raise (noise_api_key='')."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            # Empty key → _noise_http_client is never lazily created during run()
            noise_classifier_api_key="",
        )

        # Must not raise
        await worker.aclose()
        assert worker._noise_http_client is None

    @pytest.mark.asyncio()
    async def test_aclose_closes_http_client(self) -> None:
        """aclose() calls aclose() on the shared httpx client when one exists."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            noise_classifier_api_key="test-key",
        )

        # Inject a pre-created mock client (simulates a run() that triggered lazy creation)
        mock_client = AsyncMock()
        worker._noise_http_client = mock_client

        await worker.aclose()

        mock_client.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# F-DS-202 regression guard: per-row session isolation
# ---------------------------------------------------------------------------


class TestPhase3PerRowSessionIsolation:
    """Per-row session: a failure on one row must not prevent subsequent rows from committing."""

    @pytest.mark.asyncio()
    async def test_second_row_committed_even_if_first_row_persist_fails(self) -> None:
        """Per-row session: a failure on row 1 does not prevent row 2 from committing.

        The worker processes each row's Phase 3 _persist_enrichment independently.
        Row 2's entity_id must appear in entity_ids_to_dirty and be written to the
        outbox even when row 1 raises.

        D-014: we track via OutboxRepository.append (outbox) instead of
        produce_bytes (deprecated direct produce).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        entity_id_2 = UUID("01234567-89ab-7def-8012-cccccccccccc")
        rows = [_make_pending_row(), _make_pending_row()]
        _session, factory = _make_session_with_rows(rows)

        # _persist_enrichment: row 1 raises, row 2 returns a valid UUID.
        persist_side_effects = [RuntimeError("persist failed on row 1"), entity_id_2]

        outbox_partition_keys: list[str] = []

        async def _capture_append(
            topic: str, partition_key: str, payload_avro: bytes, *, event_id: object = None
        ) -> None:
            outbox_partition_keys.append(partition_key)

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock())

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Corp", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", side_effect=persist_side_effects),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.OutboxRepository") as mock_outbox_cls,
        ):
            mock_outbox_cls.return_value.append = AsyncMock(side_effect=_capture_append)
            # Must not raise — per-row exception is logged and skipped.
            await worker.run()

        # Row 2's entity_id must have been written to the outbox.
        assert (
            str(entity_id_2) in outbox_partition_keys
        ), f"Row 2 entity_id {entity_id_2} not in outbox partition keys: {outbox_partition_keys}"


# ---------------------------------------------------------------------------
# F-QA-202/203/204 (Wave C-1): noise pipeline coverage gaps
# ---------------------------------------------------------------------------
# Notes on coverage already present (do not duplicate):
#   • F-QA-201 aclose() lifecycle: covered by TestAcloseLifecycle above
#     (test_aclose_when_no_client_is_noop, test_aclose_closes_http_client).
#   • F-QA-203 fail-open semantics: _run_noise_filters() already calls
#     asyncio.gather(..., return_exceptions=True) and recovers via index.
#     We add a test below that exercises the recovery branch directly.


class TestNoiseLayer2EmptyApiKey:
    """F-QA-202: when noise_classifier_api_key='' Layer 2 must be a no-op (no HTTP)."""

    @pytest.mark.asyncio()
    async def test_layer2_classify_returns_false_with_empty_api_key(self) -> None:
        """Empty noise_api_key → _layer2_classify returns False without creating an HTTP client."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            noise_classifier_api_key="",
        )

        # Layer 2 must short-circuit on the empty-key guard at the top of
        # _layer2_classify (returns False) without ever instantiating an
        # httpx.AsyncClient or making a network call.
        result = await worker._layer2_classify("any mention text")

        assert result is False
        # The guard must NOT lazily create a client when the key is empty.
        assert worker._noise_http_client is None

    @pytest.mark.asyncio()
    async def test_run_noise_filters_with_empty_api_key_passes_rows_to_layer3(self) -> None:
        """With empty noise_api_key, non-blocklisted rows pass through to Layer 3.

        F-QA-202: Layer 2 disabled (empty key) must NOT silently drop rows.  All
        rows that survive Layer 1 should appear in `remaining` (i.e. Layer 3
        candidates).
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            noise_classifier_api_key="",
        )

        qid = UUID("01234567-89ab-7def-8012-fff000000001")
        # Mention is NOT in the blocklist → must pass to Layer 2; Layer 2
        # short-circuits (empty key) → row appears in remaining.
        rows = [(qid, "Apple Inc.", "financial_instrument", "context", 0)]

        l1, l2, remaining = await worker._run_noise_filters(rows)

        assert l1 == [], "No Layer 1 (blocklist) hits expected for 'Apple Inc.'"
        assert l2 == [], "No Layer 2 hits expected when API key is empty"
        assert len(remaining) == 1
        assert remaining[0][0] == qid
        # Confirm no HTTP client was created.
        assert worker._noise_http_client is None


class TestNoiseGatherFailOpen:
    """F-QA-203: asyncio.gather(return_exceptions=True) → wrapper exceptions
    must NOT silently drop rows; they must propagate to Layer 3 instead."""

    @pytest.mark.asyncio()
    async def test_gather_wrapper_exception_recovers_row_via_index(self) -> None:
        """If gather() returns an Exception in slot i, layer2_candidates[i] is
        recovered into the `remaining` (Layer 3) bucket — never dropped.

        We patch asyncio.gather inside the worker module so that one of the
        results is an Exception instance; the recovery branch (lines 619-625
        of provisional_enrichment.py) must place the corresponding original
        row into `layer2_pass`.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            noise_classifier_api_key="fake-key",
        )

        qid_a = UUID("01234567-89ab-7def-8012-aaa000000001")
        qid_b = UUID("01234567-89ab-7def-8012-bbb000000002")
        row_a = (qid_a, "Foo Corp", "financial_instrument", "ctx", 0)
        row_b = (qid_b, "Bar Inc", "financial_instrument", "ctx", 0)
        rows = [row_a, row_b]

        # Replace asyncio.gather inside the worker module with a stub that
        # returns one Exception (slot 0) + one valid (row, False) tuple
        # (slot 1).  This exercises the index-based recovery branch.
        async def _fake_gather(*coros: object, **_kwargs: object) -> list[object]:
            # Cancel the unused coros so pytest does not warn about
            # un-awaited coroutines.
            for c in coros:
                if asyncio.iscoroutine(c):
                    c.close()
            return [RuntimeError("simulated wrapper failure"), (row_b, False)]

        with patch(
            "knowledge_graph.infrastructure.workers.provisional_enrichment.asyncio.gather",
            new=_fake_gather,
        ):
            l1, l2, remaining = await worker._run_noise_filters(rows)

        # Row A was lost in the gather wrapper; the recovery branch must put
        # it back into `remaining` so Layer 3 still sees it.
        assert l1 == []
        assert l2 == []
        remaining_ids = {r[0] for r in remaining}
        assert qid_a in remaining_ids, "Row recovered from gather exception must reach Layer 3"
        assert qid_b in remaining_ids, "Row that classified as not-noise must reach Layer 3"


class TestNoiseLayer1CounterMetric:
    """F-QA-204: s7_provisional_noise_filtered_total.inc() must be called
    once per Layer-1 noise hit (1:1 with blocklist matches)."""

    @pytest.mark.asyncio()
    async def test_layer1_counter_incremented_per_blocklist_row(self) -> None:
        """N blocklist rows → counter.inc() called exactly N times."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([])
        worker = ProvisionalEnrichmentWorker(
            session_factory=factory,
            llm_client=AsyncMock(),
            noise_classifier_api_key="",  # Layer 2 disabled — only Layer 1 fires.
        )

        # Three blocklist mentions ("analysts" is in _NOISE_BLOCKLIST, plus
        # variants).  We rely on case-insensitive match for one of them.
        rows = [
            (UUID("01234567-89ab-7def-8012-1111aaaa0001"), "analysts", "financial_instrument", "", 0),
            (UUID("01234567-89ab-7def-8012-1111aaaa0002"), "ANALYSTS", "financial_instrument", "", 0),
            (UUID("01234567-89ab-7def-8012-1111aaaa0003"), "analysts", "financial_instrument", "", 0),
        ]

        with patch(
            "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_noise_filtered_total",
        ) as mock_counter:
            l1, _l2, _remaining = await worker._run_noise_filters(rows)

        assert len(l1) == 3, f"Expected 3 Layer-1 noise hits, got {len(l1)}"
        assert (
            mock_counter.inc.call_count == 3
        ), f"Counter must be incremented once per Layer-1 hit; got {mock_counter.inc.call_count}"
