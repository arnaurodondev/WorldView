"""Integration tests for BaseOutboxDispatcher outbox flow.

Uses an in-memory repository and a mock producer (no live Kafka required).
Tests the full dispatch → mark_published / increment_attempts / dead-letter paths.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DeliveryResult,
    DispatcherConfig,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
    run_dispatcher,
)

# ── Test doubles ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class _OutboxRecord:
    """Minimal concrete outbox record."""

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    attempts: int = 0
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """In-memory OutboxRepositoryProtocol implementation."""

    def __init__(self, records: list[_OutboxRecord]) -> None:
        self._records = {r.id: r for r in records}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []
        # BUG-1: capture the error_detail threaded into move_to_dead_letter so a
        # test can assert the DLQ failure cause is persisted (not NULL).
        self.dead_letter_errors: dict[int, str] = {}

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        pending = [
            r for r in self._records.values() if r.id not in self.published_ids and r.id not in self.dead_letter_ids
        ]
        return list(pending[:batch_size])  # type: ignore[return-value]

    async def mark_published(self, record_id: Any) -> None:
        self.published_ids.append(record_id)

    async def increment_attempts(self, record_id: Any) -> None:
        if record_id in self._records:
            self._records[record_id].attempts += 1

    async def move_to_dead_letter(self, record_id: Any, error_detail: str = "") -> None:
        self.dead_letter_ids.append(record_id)
        self.dead_letter_errors[record_id] = error_detail


class _InMemoryUoW:
    """UnitOfWorkWithOutboxProtocol backed by an in-memory repo."""

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


class _MockProducer:
    """Mock Confluent SerializingProducer.

    Calls the delivery callback synchronously on flush() with either None
    (success) or an error string (failure).
    """

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self._pending: list[Any] = []
        self.produced_topics: list[str] = []

    def produce(
        self,
        topic: str,
        value: Any = None,
        key: Any = None,
        headers: Any = None,
        on_delivery: Any = None,
    ) -> None:
        self.produced_topics.append(topic)
        self._pending.append(on_delivery)

    def flush(self, timeout: float = -1.0) -> int:
        for cb in self._pending:
            if cb is not None:
                err = "mock delivery error" if self._fail else None
                cb(err, None)
        self._pending.clear()
        return 0


class _TestDispatcher(BaseOutboxDispatcher):
    """Concrete dispatcher wired to the in-memory repo and mock producer."""

    def __init__(
        self,
        repo: _InMemoryOutboxRepo,
        producer: _MockProducer,
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._repo = repo
        self._producer = producer
        self._uow = _InMemoryUoW(repo)

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        self._uow = _InMemoryUoW(self._repo)
        return self._uow  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        return self._producer


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_record(
    record_id: int = 1,
    event_type: str = "market.dataset.fetched",
    topic: str = "market.dataset.fetched",
    attempts: int = 0,
) -> _OutboxRecord:
    return _OutboxRecord(
        id=record_id,
        event_type=event_type,
        topic=topic,
        payload={"symbol": "AAPL", "timeframe": "1d"},
        attempts=attempts,
    )


# ── Success path ──────────────────────────────────────────────────────────────


class TestDispatchSuccess:
    async def test_record_marked_published_on_success(self) -> None:
        record = _make_record(record_id=1)
        repo = _InMemoryOutboxRepo([record])
        producer = _MockProducer(fail=False)
        dispatcher = _TestDispatcher(repo, producer)

        results = await dispatcher.dispatch_now()

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].record_id == 1
        assert 1 in repo.published_ids

    async def test_produced_to_correct_topic(self) -> None:
        record = _make_record(topic="market.dataset.fetched")
        repo = _InMemoryOutboxRepo([record])
        producer = _MockProducer(fail=False)
        dispatcher = _TestDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        assert "market.dataset.fetched" in producer.produced_topics

    async def test_multiple_records_dispatched(self) -> None:
        records = [_make_record(record_id=i) for i in range(1, 4)]
        repo = _InMemoryOutboxRepo(records)
        producer = _MockProducer(fail=False)
        dispatcher = _TestDispatcher(repo, producer)

        results = await dispatcher.dispatch_now()

        assert len(results) == 3
        assert all(r.success for r in results)
        assert set(repo.published_ids) == {1, 2, 3}

    async def test_empty_outbox_returns_empty_results(self) -> None:
        repo = _InMemoryOutboxRepo([])
        dispatcher = _TestDispatcher(repo, _MockProducer())

        results = await dispatcher.dispatch_now()
        assert results == []

    async def test_unit_of_work_committed_on_success(self) -> None:
        record = _make_record()
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _TestDispatcher(repo, _MockProducer(fail=False))

        await dispatcher.dispatch_now()

        assert dispatcher._uow.committed is True


# ── Failure path ──────────────────────────────────────────────────────────────


class TestDispatchFailure:
    async def test_failed_delivery_increments_attempts(self) -> None:
        record = _make_record(record_id=1, attempts=0)
        repo = _InMemoryOutboxRepo([record])
        producer = _MockProducer(fail=True)
        config = DispatcherConfig(max_attempts=5)
        dispatcher = _TestDispatcher(repo, producer, config)

        results = await dispatcher.dispatch_now()

        assert len(results) == 1
        assert results[0].success is False
        assert repo._records[1].attempts == 1
        assert 1 not in repo.published_ids

    async def test_failed_delivery_result_has_error(self) -> None:
        record = _make_record()
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _TestDispatcher(repo, _MockProducer(fail=True))

        results = await dispatcher.dispatch_now()

        assert results[0].error is not None

    async def test_dead_lettered_when_max_attempts_exceeded(self) -> None:
        # attempts already at max_attempts - 1, so next failure triggers dead-letter
        config = DispatcherConfig(max_attempts=3)
        record = _make_record(record_id=1, attempts=2)  # 2 + 1 = 3 = max_attempts
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _TestDispatcher(repo, _MockProducer(fail=True), config)

        results = await dispatcher.dispatch_now()

        assert 1 in repo.dead_letter_ids
        assert results[0].success is False

    async def test_dead_letter_persists_error_detail(self) -> None:
        """BUG-1 regression: move_to_dead_letter must receive a non-empty cause.

        Previously the dispatcher called move_to_dead_letter WITHOUT the error,
        and the repos default error_detail="" → NULL, leaving every DLQ row
        un-triageable. The dispatcher now threads "<ErrorType>: <repr>" through.
        """
        config = DispatcherConfig(max_attempts=3)
        record = _make_record(record_id=1, attempts=2)  # next failure dead-letters
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _TestDispatcher(repo, _MockProducer(fail=True), config)

        await dispatcher.dispatch_now()

        assert 1 in repo.dead_letter_ids
        detail = repo.dead_letter_errors[1]
        assert detail, "error_detail must be populated (was NULL — BUG-1)"
        # The mock raises a delivery error surfaced as RuntimeError(str(err)).
        assert "RuntimeError" in detail
        assert "mock delivery error" in detail

    async def test_second_attempt_not_dead_lettered(self) -> None:
        config = DispatcherConfig(max_attempts=5)
        record = _make_record(record_id=1, attempts=1)
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _TestDispatcher(repo, _MockProducer(fail=True), config)

        await dispatcher.dispatch_now()

        assert 1 not in repo.dead_letter_ids
        assert repo._records[1].attempts == 2


# ── Delivery result ───────────────────────────────────────────────────────────


class TestDeliveryResult:
    def test_successful_result_attributes(self) -> None:
        result = DeliveryResult(record_id=1, success=True, topic="t.events")
        assert result.record_id == 1
        assert result.success is True
        assert result.topic == "t.events"
        assert result.error is None

    def test_failed_result_carries_error(self) -> None:
        err = RuntimeError("kafka down")
        result = DeliveryResult(record_id=2, success=False, topic="t.events", error=err)
        assert result.success is False
        assert result.error is err


# ── Stop / worker-id ─────────────────────────────────────────────────────────


class TestDispatcherLifecycle:
    def test_stop_sets_event(self) -> None:
        dispatcher = _TestDispatcher(_InMemoryOutboxRepo([]), _MockProducer())
        assert not dispatcher._stop_event.is_set()
        dispatcher.stop()
        assert dispatcher._stop_event.is_set()

    def test_worker_id_auto_generated(self) -> None:
        config = DispatcherConfig()
        assert len(config.worker_id) > 0

    def test_custom_worker_id_preserved(self) -> None:
        config = DispatcherConfig(worker_id="my-worker-01")
        assert config.worker_id == "my-worker-01"

    async def test_run_dispatcher_handles_cancellation(self) -> None:
        """run_dispatcher should stop gracefully when task is cancelled."""
        import asyncio

        dispatcher = _TestDispatcher(
            _InMemoryOutboxRepo([]),
            _MockProducer(),
            DispatcherConfig(poll_interval_seconds=0.01),
        )
        task = asyncio.create_task(run_dispatcher(dispatcher))
        await asyncio.sleep(0.05)
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task
        # No assertion needed — just verifying no unhandled exception
