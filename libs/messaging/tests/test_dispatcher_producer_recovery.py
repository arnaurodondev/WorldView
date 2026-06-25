"""Tests for producer recovery + error visibility + staleness gauge.

Regression coverage for the production outage where the cached rdkafka
producer entered an unrecoverable broken state after a transient broker
blip: every ``produce()`` then timed out *forever* (no reconnect logic),
and because ``asyncio.TimeoutError.__str__()`` returns ``""`` the failure
logged ``error: ""`` and was invisible for ~23h. See
``docs/bug-patterns/kafka-messaging.md`` (BP outbox-dispatcher-wedged-producer).

This module pins three behaviours on :class:`BaseOutboxDispatcher`:

1. A delivery ``TimeoutError`` triggers a producer reset, so the *next*
   dispatch builds a FRESH producer (reconnect) instead of reusing the
   wedged one.
2. The failure log record carries the exception *type name* (``error_type``)
   so a ``TimeoutError`` — whose ``str`` is empty — is never invisible again.
3. The ``outbox_last_delivery_timestamp`` gauge is updated on a successful
   delivery (the staleness signal a >30-min-stall alert is built on).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from prometheus_client import CollectorRegistry

from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DispatcherConfig,
    OutboxRecordProtocol,
    UnitOfWorkWithOutboxProtocol,
)
from observability import create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime

# ── Test doubles ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class _Record:
    """Minimal outbox record."""

    id: int
    event_type: str
    topic: str
    payload: dict[str, Any]
    attempts: int = 0
    partition_key: str | None = None
    leased_until: datetime | None = None


class _InMemoryOutboxRepo:
    """In-memory ``OutboxRepositoryProtocol``."""

    def __init__(self, records: list[Any]) -> None:
        self._records = {r.id: r for r in records}
        self.published_ids: list[int] = []
        self.dead_letter_ids: list[int] = []

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

    async def move_to_dead_letter(self, record_id: Any) -> None:
        self.dead_letter_ids.append(record_id)


class _InMemoryUoW:
    """Mock unit of work wrapping the in-memory repo."""

    def __init__(self, repo: _InMemoryOutboxRepo) -> None:
        self.outbox: _InMemoryOutboxRepo = repo  # type: ignore[assignment]

    async def __aenter__(self) -> _InMemoryUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _TimingOutProducer:
    """Producer whose ``produce()`` raises ``asyncio.TimeoutError``.

    Simulates the wedged cached producer: the produce call never completes.
    """

    def __init__(self) -> None:
        self.flush_called = False

    def produce(self, *args: Any, **kwargs: Any) -> None:
        # This is the exact failure that froze the outbox: a TimeoutError whose
        # ``str()`` is empty. Raised here so ``_dispatch_record`` records it as
        # ``delivery_error`` via its ``except Exception`` guard.
        raise TimeoutError

    def flush(self, timeout: float = -1.0) -> int:
        # Called by ``_reset_producer`` during teardown — must not raise.
        self.flush_called = True
        return 0


class _HealthyProducer:
    """Producer that immediately fires the delivery callback with success."""

    def __init__(self) -> None:
        self._pending: list[Any] = []

    def produce(self, topic: str, value: Any = None, key: Any = None, on_delivery: Any = None, **kw: Any) -> None:
        self._pending.append(on_delivery)

    def flush(self, timeout: float = -1.0) -> int:
        for cb in self._pending:
            if cb is not None:
                cb(None, None)  # err=None => success
        self._pending.clear()
        return 0


class _RebuildingDispatcher(BaseOutboxDispatcher):
    """Dispatcher that rebuilds its producer from a queue, like a real subclass.

    ``get_producer()`` honours the ``self._producer is None`` convention so
    that ``_reset_producer`` (which sets it to ``None``) forces a fresh build —
    pulling the NEXT producer from ``producer_sequence``. This lets a test
    assert that a TimeoutError on producer #1 causes producer #2 to be built.
    """

    def __init__(self, repo: _InMemoryOutboxRepo, producer_sequence: list[Any], metrics: Any = None) -> None:
        super().__init__(DispatcherConfig(max_attempts=5), metrics=metrics)
        self._repo = repo
        self._producer: Any = None
        self._sequence = list(producer_sequence)
        self.build_count = 0

    async def get_unit_of_work(self) -> UnitOfWorkWithOutboxProtocol:
        return _InMemoryUoW(self._repo)  # type: ignore[return-value]

    def get_serializer(self, event_type: str) -> Any:
        return lambda v, ctx: b"{}"

    def get_producer(self) -> Any:
        if self._producer is None:
            self._producer = self._sequence[self.build_count]
            self.build_count += 1
        return self._producer


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestProducerRecovery:
    async def test_timeout_resets_producer_and_next_call_rebuilds(self) -> None:
        """A delivery TimeoutError nulls the cached producer; next dispatch builds a fresh one."""
        record = _Record(id=1, event_type="content.article.raw.v1", topic="content.article.raw.v1", payload={})
        repo = _InMemoryOutboxRepo([record])
        wedged = _TimingOutProducer()
        healthy = _HealthyProducer()
        dispatcher = _RebuildingDispatcher(repo, [wedged, healthy])

        # First cycle: wedged producer times out → record not published, producer reset.
        await dispatcher.dispatch_now()
        assert dispatcher.build_count == 1  # built the wedged producer
        assert dispatcher._producer is None  # reset cleared the cache
        assert wedged.flush_called is True  # best-effort drain happened
        assert 1 not in repo.published_ids

        # Second cycle: a FRESH (healthy) producer is built and delivery succeeds.
        await dispatcher.dispatch_now()
        assert dispatcher.build_count == 2  # rebuilt → reconnect
        assert 1 in repo.published_ids

    async def test_failure_log_includes_exception_type_name(self) -> None:
        """The dispatch-failure log carries error_type so an empty-str TimeoutError is visible."""
        record = _Record(id=2, event_type="content.article.raw.v1", topic="content.article.raw.v1", payload={})
        repo = _InMemoryOutboxRepo([record])
        dispatcher = _RebuildingDispatcher(repo, [_TimingOutProducer()])

        captured: list[dict[str, Any]] = []

        # Patch the bound logger used inside base.py to capture structured kwargs.
        import messaging.kafka.dispatcher.base as base_mod

        original_warning = base_mod.logger.warning

        def _capture(event: str, **kwargs: Any) -> None:
            captured.append({"event": event, **kwargs})

        base_mod.logger.warning = _capture  # type: ignore[assignment]
        try:
            await dispatcher.dispatch_now()
        finally:
            base_mod.logger.warning = original_warning  # type: ignore[assignment]

        failed = [c for c in captured if c["event"] == "outbox_record_dispatch_failed"]
        assert len(failed) == 1
        # The whole point: the type name is present even though str(TimeoutError) == "".
        assert failed[0]["error_type"] == "TimeoutError"
        assert "TimeoutError" in failed[0]["error_repr"]

    async def test_gauge_updates_on_successful_delivery(self) -> None:
        """outbox_last_delivery_timestamp is set to a positive epoch on success."""
        record = _Record(id=3, event_type="content.article.raw.v1", topic="content.article.raw.v1", payload={})
        repo = _InMemoryOutboxRepo([record])
        # Isolated registry so this test never collides with the global one.
        metrics = create_metrics("test-dispatcher-gauge", registry=CollectorRegistry())
        dispatcher = _RebuildingDispatcher(repo, [_HealthyProducer()], metrics=metrics)

        # Gauge starts unset (0.0).
        assert metrics.outbox_last_delivery_timestamp._value.get() == pytest.approx(0.0)

        await dispatcher.dispatch_now()

        assert 3 in repo.published_ids
        # Now reflects a real wall-clock delivery time (seconds since epoch).
        assert metrics.outbox_last_delivery_timestamp._value.get() > 1_700_000_000
