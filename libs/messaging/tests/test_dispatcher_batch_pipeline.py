"""Tests for the pipelined batch dispatch path (BP outbox-dispatcher-throughput).

The base dispatcher used to produce → flush → await *each* record individually,
so a batch of N records paid N sequential Kafka round-trips. Under the
high-volume Polymarket CLOB firehose the single FIFO dispatcher could not keep
up and ``content_ingestion_db.outbox_events`` grew to ~111k undispatched rows.

The fix (:meth:`BaseOutboxDispatcher._dispatch_records_pipelined`) produces the
WHOLE batch before ONE ``flush()``, and the run loop no longer sleeps
``poll_interval`` between *full* batches (drain-when-full). This module pins:

1. A batch is produced in full BEFORE a single ``flush()`` (throughput).
2. Produce order == FIFO input order, and per-record keys are forwarded
   (ordering preserved).
3. A mixed batch marks the successes published and increments only the failures.
4. A never-acked record (callback never fired) is retried, not lost.
5. A produce-time ``TimeoutError`` fails only that record, still flushes the
   rest, and resets the wedged producer exactly once.
6. The run loop drains a multi-batch backlog without waiting ``poll_interval``.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING, Any

from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DispatcherConfig,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
    run_dispatcher,
)

if TYPE_CHECKING:
    from datetime import datetime

# ── Test doubles ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class _Record:
    """Minimal outbox record with an optional ``partition_key``."""

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    attempts: int = 0
    partition_key: str | None = None
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """In-memory ``OutboxRepositoryProtocol`` that returns rows in FIFO order."""

    def __init__(self, records: list[_Record]) -> None:
        # Preserve insertion order so fetch_pending mimics ``ORDER BY created_at``.
        self._records: dict[int, _Record] = {r.id: r for r in records}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []
        self.dead_letter_errors: dict[int, str] = {}
        self.increment_calls: list[int] = []

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        pending = [
            r for r in self._records.values() if r.id not in self.published_ids and r.id not in self.dead_letter_ids
        ]
        return list(pending[:batch_size])  # type: ignore[return-value]

    async def mark_published(self, record_id: Any) -> None:
        self.published_ids.append(record_id)

    async def increment_attempts(self, record_id: Any) -> None:
        self.increment_calls.append(record_id)
        if record_id in self._records:
            self._records[record_id].attempts += 1

    async def move_to_dead_letter(self, record_id: Any, error_detail: str = "") -> None:
        self.dead_letter_ids.append(record_id)
        self.dead_letter_errors[record_id] = error_detail


class _InMemoryUoW:
    """UnitOfWorkWithOutboxProtocol backed by the in-memory repo."""

    def __init__(self, repo: _InMemoryOutboxRepo) -> None:
        self.outbox: _InMemoryOutboxRepo = repo  # type: ignore[assignment]
        self.committed = False

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass


class _BatchProducer:
    """Mock producer that records the exact produce/flush call sequence.

    ``events`` captures the interleaving so a test can assert every produce
    happened BEFORE the single flush. Delivery callbacks fire during flush().
    A record is failed when its ``topic`` is in ``fail_topics``; a record whose
    ``topic`` is in ``drop_topics`` never has its callback fired (simulates a
    never-acked delivery). ``raise_on_topic`` makes ``produce()`` raise a
    TimeoutError for that topic (wedged-producer signature).
    """

    def __init__(
        self,
        *,
        fail_topics: frozenset[str] = frozenset(),
        drop_topics: frozenset[str] = frozenset(),
        raise_on_topic: str | None = None,
    ) -> None:
        self._fail_topics = fail_topics
        self._drop_topics = drop_topics
        self._raise_on_topic = raise_on_topic
        self._pending: list[tuple[Any, str]] = []
        self.events: list[str] = []
        self.produced: list[dict[str, Any]] = []
        self.flush_count = 0

    def produce(self, topic: str, value: Any = None, key: Any = None, on_delivery: Any = None, **_kw: Any) -> None:
        if self._raise_on_topic is not None and topic == self._raise_on_topic:
            # Wedged-producer signature: str(TimeoutError) == "".
            raise TimeoutError
        self.events.append(f"produce:{topic}")
        self.produced.append({"topic": topic, "key": key})
        self._pending.append((on_delivery, topic))

    def flush(self, timeout: float = -1.0) -> int:
        self.events.append("flush")
        self.flush_count += 1
        for cb, topic in self._pending:
            if cb is None or topic in self._drop_topics:
                continue  # never-acked delivery
            err = "mock delivery error" if topic in self._fail_topics else None
            cb(err, None)
        self._pending.clear()
        return 0


class _PipelineDispatcher(BaseOutboxDispatcher):
    """Concrete dispatcher using the BASE (pipelined) ``_dispatch_batch``."""

    def __init__(
        self,
        repo: _InMemoryOutboxRepo,
        producer: _BatchProducer,
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._repo = repo
        self._producer = producer
        self._uow = _InMemoryUoW(repo)
        self.reset_count = 0

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        self._uow = _InMemoryUoW(self._repo)
        return self._uow  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        return self._producer

    def _reset_producer(self) -> None:
        # Count resets so a test can assert we reset the wedged producer once.
        self.reset_count += 1


# ── Helpers ───────────────────────────────────────────────────────────────────


def _records(n: int, *, topic_prefix: str = "t") -> list[_Record]:
    return [
        _Record(id=i, event_type="market.prediction.history", topic=f"{topic_prefix}.{i}", payload={"n": i})
        for i in range(1, n + 1)
    ]


# ── Throughput / ordering ──────────────────────────────────────────────────────


class TestBatchPipeline:
    async def test_whole_batch_produced_before_single_flush(self) -> None:
        repo = _InMemoryOutboxRepo(_records(4))
        producer = _BatchProducer()
        dispatcher = _PipelineDispatcher(repo, producer, DispatcherConfig(batch_size=10))

        results = await dispatcher.dispatch_now()

        assert len(results) == 4
        assert all(r.success for r in results)
        # THE throughput property: 4 produces, THEN exactly one flush.
        assert producer.events == ["produce:t.1", "produce:t.2", "produce:t.3", "produce:t.4", "flush"]
        assert producer.flush_count == 1
        assert set(repo.published_ids) == {1, 2, 3, 4}

    async def test_produce_order_and_keys_preserved(self) -> None:
        recs = [
            _Record(id=1, event_type="e", topic="t.a", payload={}, partition_key="AAPL"),
            _Record(id=2, event_type="e", topic="t.b", payload={}, partition_key=None),
            _Record(id=3, event_type="e", topic="t.c", payload={}, partition_key="MSFT"),
        ]
        repo = _InMemoryOutboxRepo(recs)
        producer = _BatchProducer()
        dispatcher = _PipelineDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        # Ordering preserved: produce order == FIFO input order.
        assert [p["topic"] for p in producer.produced] == ["t.a", "t.b", "t.c"]
        # partition_key forwarded as UTF-8 bytes (or None).
        assert [p["key"] for p in producer.produced] == [b"AAPL", None, b"MSFT"]

    async def test_mixed_success_and_failure_in_one_batch(self) -> None:
        repo = _InMemoryOutboxRepo(_records(3))  # topics t.1, t.2, t.3
        producer = _BatchProducer(fail_topics=frozenset({"t.2"}))
        dispatcher = _PipelineDispatcher(repo, producer, DispatcherConfig(max_attempts=5))

        results = await dispatcher.dispatch_now()

        assert producer.flush_count == 1  # still a single flush
        assert set(repo.published_ids) == {1, 3}
        assert repo.increment_calls == [2]  # only the failed record
        assert repo._records[2].attempts == 1
        assert [r.success for r in results] == [True, False, True]

    async def test_never_acked_record_is_retried_not_lost(self) -> None:
        repo = _InMemoryOutboxRepo(_records(2))  # t.1, t.2
        # t.2 is produced but its delivery callback never fires (undelivered).
        producer = _BatchProducer(drop_topics=frozenset({"t.2"}))
        dispatcher = _PipelineDispatcher(repo, producer, DispatcherConfig(max_attempts=5))

        results = await dispatcher.dispatch_now()

        assert 1 in repo.published_ids
        assert 2 not in repo.published_ids  # NOT lost
        assert repo.increment_calls == [2]  # retried next cycle
        # A never-acked delivery is a TimeoutError → wedged-producer → reset once.
        assert dispatcher.reset_count == 1
        assert results[1].success is False

    async def test_produce_time_error_fails_only_that_record_and_resets_once(self) -> None:
        repo = _InMemoryOutboxRepo(_records(3))  # t.1, t.2, t.3
        # produce() raises TimeoutError on t.2 only; t.1 and t.3 still produced.
        producer = _BatchProducer(raise_on_topic="t.2")
        dispatcher = _PipelineDispatcher(repo, producer, DispatcherConfig(max_attempts=5))

        results = await dispatcher.dispatch_now()

        assert set(repo.published_ids) == {1, 3}
        assert repo.increment_calls == [2]
        # Exactly one flush despite the produce-time raise, and one producer reset.
        assert producer.flush_count == 1
        assert dispatcher.reset_count == 1
        assert [r.success for r in results] == [True, False, True]

    async def test_batch_failure_dead_letters_at_max_attempts_with_detail(self) -> None:
        # One record already at max_attempts - 1 → next failure dead-letters it.
        recs = _records(1)
        recs[0].attempts = 2
        repo = _InMemoryOutboxRepo(recs)
        producer = _BatchProducer(fail_topics=frozenset({"t.1"}))
        dispatcher = _PipelineDispatcher(repo, producer, DispatcherConfig(max_attempts=3))

        await dispatcher.dispatch_now()

        assert 1 in repo.dead_letter_ids
        detail = repo.dead_letter_errors[1]
        assert "RuntimeError" in detail  # cause is triageable (BUG-1 preserved)
        assert "mock delivery error" in detail

    async def test_empty_batch_commits_and_returns_empty(self) -> None:
        repo = _InMemoryOutboxRepo([])
        dispatcher = _PipelineDispatcher(repo, _BatchProducer())

        results = await dispatcher.dispatch_now()

        assert results == []
        assert dispatcher._uow.committed is True


# ── Drain-when-full run loop ────────────────────────────────────────────────────


class TestDrainWhenFull:
    async def test_run_loop_drains_backlog_without_idle_wait(self) -> None:
        """A 5-record backlog with batch_size=2 drains in 3 cycles quickly.

        ``poll_interval_seconds`` is set to a large value: if the loop slept
        between full batches (the pre-fix behaviour) the backlog would take
        >2 poll intervals to drain. With drain-when-full it clears near-instantly.
        """
        repo = _InMemoryOutboxRepo(_records(5))
        producer = _BatchProducer()
        # Large poll interval — the test would time out if we slept between batches.
        config = DispatcherConfig(batch_size=2, poll_interval_seconds=30.0)
        dispatcher = _PipelineDispatcher(repo, producer, config)

        task = asyncio.create_task(run_dispatcher(dispatcher))
        # Give the loop a few ticks to drain the backlog (no real sleeps involved).
        for _ in range(50):
            if len(repo.published_ids) == 5:
                break
            await asyncio.sleep(0.01)
        dispatcher.stop()
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert set(repo.published_ids) == {1, 2, 3, 4, 5}

    async def test_continue_when_batch_full_disabled_restores_legacy_cadence(self) -> None:
        """With the flag off, a full batch still sleeps — only one batch drains fast."""
        repo = _InMemoryOutboxRepo(_records(5))
        producer = _BatchProducer()
        config = DispatcherConfig(
            batch_size=2,
            poll_interval_seconds=30.0,
            continue_when_batch_full=False,
        )
        dispatcher = _PipelineDispatcher(repo, producer, config)

        task = asyncio.create_task(run_dispatcher(dispatcher))
        await asyncio.sleep(0.1)  # one dispatch cycle, then it sleeps 30s
        dispatcher.stop()
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Only the first full batch (2) drained before the loop parked on the
        # 30s sleep — proving the flag gates the drain behaviour.
        assert len(repo.published_ids) == 2


# ── Config default ──────────────────────────────────────────────────────────────


class TestConfigDefault:
    def test_continue_when_batch_full_defaults_true(self) -> None:
        assert DispatcherConfig().continue_when_batch_full is True
