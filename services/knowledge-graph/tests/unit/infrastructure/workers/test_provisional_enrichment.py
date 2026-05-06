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

        # Recovery sweep commit + Phase 1 commit + Phase 3 commit = 3 commits
        assert len(commit_called_at) == 3
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

        # Recovery sweep commit (1) + Phase 1 commit (2) succeed; Phase 3 (3) fails.
        commit_count = [0]
        original_commit = session.commit

        async def _fail_on_phase3():
            commit_count[0] += 1
            if commit_count[0] >= 3:  # Phase 3 commit
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
        """Produced entity.dirtied.v1 payload includes the entity_id in Confluent-Avro format.

        PLAN-0062 R28 update: the emitted bytes are now Confluent-Avro
        wire-format (5-byte header + Avro body), not JSON.
        """
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            _ENTITY_DIRTIED_SCHEMA_PATH,
        )

        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

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
        assert kwargs["value"][:1] == b"\x00", "Expected Confluent-Avro wire format (magic byte 0x00)"
        payload = deserialize_confluent_avro(_ENTITY_DIRTIED_SCHEMA_PATH, kwargs["value"])
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
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total"
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
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_failed_total"
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


class TestProvisionalEnrichmentWorkerKafkaResilience:
    async def test_kafka_error_does_not_crash(self) -> None:
        """produce_bytes raising must not propagate out of run() (P-3)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()
        producer.produce_bytes = MagicMock(side_effect=RuntimeError("kafka down"))

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
            # Must not raise even though produce_bytes raises
            await worker.run()

    async def test_kafka_error_logs_warning(self) -> None:
        """produce_bytes raising emits provisional_enrichment_dirtied_emit_failed warning (P-3)."""
        from knowledge_graph.infrastructure.workers.provisional_enrichment import (
            ProvisionalEnrichmentWorker,
        )

        _session, factory = _make_session_with_rows([_make_pending_row()])
        producer = _make_producer()
        producer.produce_bytes = MagicMock(side_effect=RuntimeError("kafka down"))

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch("knowledge_graph.infrastructure.workers.provisional_enrichment.logger") as mock_logger,
        ):
            await worker.run()

        warning_events = [c.args[0] for c in mock_logger.warning.call_args_list]
        assert "provisional_enrichment_dirtied_emit_failed" in warning_events


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
        producer = _make_producer()

        worker = ProvisionalEnrichmentWorker(factory, AsyncMock(), direct_producer=producer)

        with (
            patch.object(
                worker,
                "_extract_entity_profile",
                return_value={"canonical_name": "Apple Inc.", "entity_type": "financial_instrument"},
            ),
            patch.object(worker, "_compute_embedding", return_value=[0.1, 0.2]),
            patch.object(worker, "_persist_enrichment", return_value=_ENTITY_ID),
            patch(
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_success_total"
            ) as mock_counter,
        ):
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
                "knowledge_graph.infrastructure.workers.provisional_enrichment.s7_provisional_enrichment_success_total"
            ) as mock_counter,
        ):
            await worker.run()

        mock_counter.inc.assert_not_called()


# ---------------------------------------------------------------------------
# P-1: init warning when direct_producer is None (ProvisionalEnrichmentWorker)
# ---------------------------------------------------------------------------


class TestInitWarningNoProducerEnrichmentWorker:
    def test_provisional_enrichment_worker_warns_when_no_producer(self) -> None:
        """When direct_producer=None, a WARNING is logged at init time."""
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

        assert any(
            e.get("event") == "provisional_enrichment_worker_no_producer" and e.get("log_level") == "warning"
            for e in cap
        ), f"Expected warning log not found in: {cap}"

    def test_provisional_enrichment_worker_no_warning_when_producer_present(self) -> None:
        """When direct_producer is provided, no 'no_producer' warning is logged."""
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
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            _ENTITY_DIRTIED_SCHEMA_PATH,
            _build_dirtied_event,
        )

        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        entity_id = _ENTITY_ID
        raw = _build_dirtied_event(entity_id)

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

        l1, l2, remaining = await worker._run_noise_filters(rows)

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
            "choices": [{"message": {"content": _json.dumps({"is_entity": True, "confidence": 0.5})}}]
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
