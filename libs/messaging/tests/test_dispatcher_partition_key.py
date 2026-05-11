"""Tests for the ``partition_key`` wiring in :class:`BaseOutboxDispatcher`.

PLAN-0057-followup Wave B (F-DATA-06): the dispatcher must forward the
optional ``OutboxRecordProtocol.partition_key`` to Kafka as the message
``key=`` so that all events for a given aggregate (e.g., a single
``instrument_id``) land on the same partition and preserve ordering.

This module pins three behaviours:

1. A record exposing a non-empty ``partition_key`` is produced with the
   key encoded as UTF-8 bytes.
2. A record exposing ``partition_key=None`` is produced with ``key=None``
   (Kafka's sticky/round-robin partitioner is fine for events without an
   ordering invariant).
3. A *legacy* record type that does **not** declare ``partition_key`` at
   all (no attribute) still works — the dispatcher reads via ``getattr``
   with a ``None`` default. This protects services that have not yet
   migrated to the new protocol.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DispatcherConfig,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
)

# ── Test doubles ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class _RecordWithPartitionKey:
    """Outbox record that exposes the new ``partition_key`` property."""

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    partition_key: str | None
    attempts: int = 0
    leased_until: datetime | None = None


@dataclasses.dataclass
class _LegacyRecord:
    """Outbox record that PRE-DATES PLAN-0057-followup (no ``partition_key``).

    Used to assert backwards compatibility: services that have not yet
    added the new column / property must keep working with the dispatcher.
    """

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    attempts: int = 0
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """Minimal in-memory ``OutboxRepositoryProtocol`` for the dispatcher."""

    def __init__(self, records: list[Any]) -> None:
        self._records = {r.id: r for r in records}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecordProtocol]:
        # Return any record not yet published or dead-lettered.
        pending = [
            r for r in self._records.values() if r.id not in self.published_ids and r.id not in self.dead_letter_ids
        ]
        return list(pending[:batch_size])  # type: ignore[return-value]

    async def mark_published(self, record_id: Any) -> None:
        self.published_ids.append(record_id)

    async def increment_attempts(self, record_id: Any) -> None:
        if record_id in self._records:
            self._records[record_id].attempts += 1

    async def move_to_dead_letter(self, record_id: Any) -> None:
        self.dead_letter_ids.append(record_id)


class _InMemoryUoW:
    """Mock unit of work that wraps the in-memory repo."""

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


class _RecordingProducer:
    """Mock SerializingProducer that records every ``produce()`` call.

    Unlike the integration-test ``_MockProducer``, this one stores the full
    keyword arguments so the partition_key wiring can be asserted exactly.
    """

    def __init__(self) -> None:
        self.produced: list[dict[str, Any]] = []
        self._pending: list[Any] = []

    def produce(
        self,
        topic: str,
        value: Any = None,
        key: Any = None,
        headers: Any = None,
        on_delivery: Any = None,
    ) -> None:
        self.produced.append({"topic": topic, "value": value, "key": key, "headers": headers})
        self._pending.append(on_delivery)

    def flush(self, timeout: float = -1.0) -> int:
        # Fire all pending delivery callbacks with success (None) so the
        # dispatcher marks records as published and we can assert the
        # produce(...) call shape without wrestling with the failure path.
        for cb in self._pending:
            if cb is not None:
                cb(None, None)
        self._pending.clear()
        return 0


class _TestDispatcher(BaseOutboxDispatcher):
    """Concrete dispatcher wired to the in-memory repo + recording producer."""

    def __init__(
        self,
        repo: _InMemoryOutboxRepo,
        producer: _RecordingProducer,
        config: DispatcherConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._repo = repo
        self._producer = producer
        self._uow = _InMemoryUoW(repo)

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        # Re-create the UoW each cycle so successive dispatch_now() calls
        # don't see a stale ``committed`` flag.
        self._uow = _InMemoryUoW(self._repo)
        return self._uow  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        return self._producer


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPartitionKey:
    """Each test is a single behaviour pinned by F-DATA-06."""

    async def test_non_empty_partition_key_passed_as_utf8_bytes(self) -> None:
        """A ``partition_key="AAPL"`` becomes ``key=b"AAPL"`` on produce()."""
        record = _RecordWithPartitionKey(
            id=1,
            event_type="market.instrument.created",
            topic="market.instrument.created",
            payload={"instrument_id": "abc"},
            partition_key="AAPL",
        )
        repo = _InMemoryOutboxRepo([record])
        producer = _RecordingProducer()
        dispatcher = _TestDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        assert len(producer.produced) == 1
        # Must be UTF-8 encoded bytes — that is what librdkafka expects.
        assert producer.produced[0]["key"] == b"AAPL"
        assert 1 in repo.published_ids

    async def test_none_partition_key_passed_as_none(self) -> None:
        """An explicit ``partition_key=None`` becomes ``key=None``."""
        record = _RecordWithPartitionKey(
            id=2,
            event_type="market.dataset.fetched",
            topic="market.dataset.fetched",
            payload={"sha": "x"},
            partition_key=None,
        )
        repo = _InMemoryOutboxRepo([record])
        producer = _RecordingProducer()
        dispatcher = _TestDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        assert len(producer.produced) == 1
        # None — Kafka falls back to sticky/round-robin partitioning, which
        # is fine for events with no ordering invariants.
        assert producer.produced[0]["key"] is None

    async def test_legacy_record_without_partition_key_attr_still_works(self) -> None:
        """A record type with NO ``partition_key`` attribute → ``key=None``.

        Backwards compatibility shield: the dispatcher uses
        ``getattr(record, "partition_key", None)`` so services that haven't
        adopted the new property continue to work unchanged.
        """
        record = _LegacyRecord(
            id=3,
            event_type="legacy.event",
            topic="legacy.topic",
            payload={"x": 1},
        )
        # Sanity check: the record really has no attribute.
        assert not hasattr(record, "partition_key")

        repo = _InMemoryOutboxRepo([record])
        producer = _RecordingProducer()
        dispatcher = _TestDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        assert len(producer.produced) == 1
        assert producer.produced[0]["key"] is None
        assert 3 in repo.published_ids

    async def test_empty_string_partition_key_is_treated_as_none(self) -> None:
        """An empty-string ``partition_key`` is falsy → ``key=None``.

        Defensive: prevents accidentally producing with ``key=b""`` which
        would route every "empty" record to a single partition (a hot spot).
        """
        record = _RecordWithPartitionKey(
            id=4,
            event_type="market.instrument.created",
            topic="market.instrument.created",
            payload={"instrument_id": "abc"},
            partition_key="",
        )
        repo = _InMemoryOutboxRepo([record])
        producer = _RecordingProducer()
        dispatcher = _TestDispatcher(repo, producer)

        await dispatcher.dispatch_now()

        assert producer.produced[0]["key"] is None
