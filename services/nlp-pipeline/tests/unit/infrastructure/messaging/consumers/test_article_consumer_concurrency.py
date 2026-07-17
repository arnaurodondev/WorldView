"""Task #14 — bounded-concurrency poll loop for the article consumer.

These tests exercise ``ArticleProcessingConsumer._dispatch_batch`` and
``_contiguous_commit_targets`` directly with fake Kafka messages and a stubbed
``_handle_message``.  They assert the three correctness properties that make
concurrent processing safe under at-least-once delivery:

1. CONCURRENCY BOUND — at most ``concurrency`` handlers run at once (semaphore),
   and every message in the batch eventually completes.
2. CONTIGUOUS-OFFSET COMMIT — offsets commit only up to the highest *contiguous*
   successfully-handled offset per partition; a gap/failure stops the commit so
   the unfinished message (and everything after it) is re-polled.
3. PER-PARTITION INDEPENDENCE — a stall/failure on one partition never blocks
   commits on another partition.

The consumer is constructed via ``object.__new__`` so we avoid wiring the full
ML/DB dependency graph — only the attributes the dispatch path touches are set.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    """Minimal stand-in for a confluent_kafka.Message.

    ``value()`` returns a JSON envelope carrying a per-(partition, offset)
    ``event_id`` so the real ``_safe_event_id`` (deserialize → extract_event_id)
    keys the durable retry counter deterministically.
    """

    def __init__(self, topic: str, partition: int, offset: int) -> None:
        self._topic = topic
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return self._topic

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        import json

        return json.dumps({"event_id": f"evt-{self._partition}-{self._offset}"}).encode()


class _FakeConfig:
    enable_auto_commit = False
    poll_timeout_seconds = 1.0
    # ``_settle_message`` reads max_retries to bound in-place retries.
    max_retries = 3


class _FakeConfluentConsumer:
    """Records every ``commit(message=..., asynchronous=...)`` call.

    Captures the ``asynchronous`` kwarg so a test can assert commits are
    SYNCHRONOUS (the fix that stopped confluent's default fire-and-forget async
    commit from silently dropping rejected offset commits).
    """

    def __init__(self) -> None:
        self.committed: list[tuple[str, int, int]] = []
        self.commit_async_flags: list[bool] = []

    def commit(self, message: Any = None, asynchronous: bool = True) -> None:
        self.committed.append((message.topic(), message.partition(), message.offset()))
        self.commit_async_flags.append(asynchronous)


def _make_consumer(max_retries: int = 3) -> ArticleProcessingConsumer:
    """Build a consumer via ``object.__new__`` with only the settle/commit deps.

    Stubs the durable Valkey attempt counter with an in-memory dict, the backoff
    with a zero-sleep, and ``dead_letter`` with a recording sink — so the tests
    exercise the real ``_settle_message`` / ``_dispatch_batch`` control flow
    without any ML/DB/Kafka/Valkey wiring.
    """
    c = object.__new__(ArticleProcessingConsumer)
    cfg = _FakeConfig()
    cfg.max_retries = max_retries
    c._config = cfg  # type: ignore[attr-defined]
    c._consumer = _FakeConfluentConsumer()  # type: ignore[attr-defined]
    # _record_consumer_lag must be a no-op (no metrics/consumer wiring here).
    c._record_consumer_lag = lambda: None  # type: ignore[attr-defined,method-assign]
    # No real backoff sleeps in tests.
    c._compute_backoff = lambda attempt: 0.0  # type: ignore[attr-defined,method-assign]

    # In-memory durable attempt counter keyed by event_id (fake Valkey).
    c._attempts = {}  # type: ignore[attr-defined]

    async def _get_attempt_count(event_id: str) -> int:
        return c._attempts.get(event_id, 0)  # type: ignore[attr-defined]

    async def _record_attempt(event_id: str, attempt: int, exc: BaseException) -> None:
        c._attempts[event_id] = c._attempts.get(event_id, 0) + 1  # type: ignore[attr-defined]

    async def _durable_attempt_count(event_id: str) -> int:
        return c._attempts.get(event_id, 0)  # type: ignore[attr-defined]

    c._get_attempt_count = _get_attempt_count  # type: ignore[attr-defined,method-assign]
    c._durable_attempt_count = _durable_attempt_count  # type: ignore[attr-defined,method-assign]
    c._record_attempt = _record_attempt  # type: ignore[attr-defined,method-assign]

    # Recording dead-letter sink (topic, partition, offset, reason).
    c.dead_lettered = []  # type: ignore[attr-defined]

    async def _dead_letter(failure: Any, reason: str | None = None) -> None:
        c.dead_lettered.append((failure.topic, failure.partition, failure.offset, reason))  # type: ignore[attr-defined]

    c.dead_letter = _dead_letter  # type: ignore[attr-defined,method-assign]
    return c


def _committed(c: ArticleProcessingConsumer) -> list[tuple[str, int, int]]:
    return c._consumer.committed  # type: ignore[attr-defined]


def _dead_lettered(c: ArticleProcessingConsumer) -> list[tuple[str, int, int, str | None]]:
    return c.dead_lettered  # type: ignore[attr-defined]


async def test_concurrency_bound_respected_and_all_complete() -> None:
    """At most ``concurrency`` handlers run at once; all messages complete."""
    c = _make_consumer()
    concurrency = 4
    sem = asyncio.Semaphore(concurrency)

    in_flight = 0
    peak = 0
    processed: list[int] = []

    async def fake_handle(msg: Any) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        # Yield so the scheduler interleaves all admitted tasks before any exits.
        await asyncio.sleep(0.01)
        processed.append(msg.offset())
        in_flight -= 1

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    # 12 messages on one partition, offsets 0..11.
    batch = [_FakeMsg("content.article.stored.v1", 0, off) for off in range(12)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    assert sorted(processed) == list(range(12))  # all completed
    assert peak <= concurrency  # never exceeded the semaphore bound
    assert peak == concurrency  # and actually reached it (real overlap)
    # Single partition, all handled → commit the highest offset (11).
    assert _committed(c) == [("content.article.stored.v1", 0, 11)]


async def test_poison_head_message_dead_lettered_and_partition_drains() -> None:
    """A consistently-failing HEAD message is DLQ'd and the partition ADVANCES.

    This is the nlp-consumer-commit-stall regression: the poison sits at offset 0
    (the partition head).  Under the old seek-back path the partition's committed
    offset froze there forever.  Now the message is retried in place up to
    max_retries, dead-lettered, and marked 'handled' so the contiguous commit
    drains PAST it to the batch high-water — without a single consumer.seek().
    """
    c = _make_consumer(max_retries=3)
    sem = asyncio.Semaphore(8)
    attempts_at_offset_0 = 0

    async def fake_handle(msg: Any) -> None:
        nonlocal attempts_at_offset_0
        if msg.offset() == 0:  # poison at the HEAD, always fails
            attempts_at_offset_0 += 1
            raise RuntimeError("poison filing: deep extraction failed")
        # every other offset succeeds

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(5)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    # Poison retried IN PLACE up to max_retries (no seek), then dead-lettered.
    assert attempts_at_offset_0 == 3
    assert _dead_lettered(c) == [("t", 0, 0, "max_retries")]
    # Partition DRAINED: committed high-water is offset 4 (advanced past the head).
    assert _committed(c) == [("t", 0, 4)]


async def test_transient_failure_retries_in_place_then_succeeds() -> None:
    """A transient error retries IN PLACE (no seek) and commits once it succeeds.

    Good work is NOT dead-lettered: the message fails twice, then the third
    in-place attempt succeeds, so the offset commits and nothing is DLQ'd.
    """
    c = _make_consumer(max_retries=5)
    sem = asyncio.Semaphore(8)
    calls = 0

    async def fake_handle(msg: Any) -> None:
        nonlocal calls
        if msg.offset() == 2:
            calls += 1
            if calls < 3:  # fail attempts 1 and 2, succeed on attempt 3
                raise RuntimeError("transient DeepInfra 429")

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(5)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    assert calls == 3  # retried in place until success
    assert _dead_lettered(c) == []  # good work never dead-lettered
    assert _committed(c) == [("t", 0, 4)]  # partition commits the full prefix


async def test_good_messages_commit_synchronously() -> None:
    """All-good batch commits the high-water with a SYNCHRONOUS commit.

    Guards the second half of the fix: confluent's default async commit dropped
    rejections silently; the consumer now commits with ``asynchronous=False`` so
    a rejected commit surfaces (and is logged) instead of freezing the offset.
    """
    c = _make_consumer()
    sem = asyncio.Semaphore(8)

    async def fake_handle(msg: Any) -> None:
        return None  # everything succeeds

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(4)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    assert _committed(c) == [("t", 0, 3)]
    assert _dead_lettered(c) == []
    # Every commit was synchronous (asynchronous=False).
    assert c._consumer.commit_async_flags == [False]  # type: ignore[attr-defined]


async def test_durable_counter_bounds_retries_across_redelivery() -> None:
    """The durable attempt counter bounds retries ACROSS a redelivery/restart.

    Simulate a redelivery: the poison already has ``max_retries - 1`` recorded
    attempts from a prior delivery.  On this delivery it must fail only ONCE more
    (not a fresh full budget) before dead-lettering — otherwise a poison that is
    redelivered on every restart would burn a full retry budget forever.
    """
    c = _make_consumer(max_retries=3)
    sem = asyncio.Semaphore(8)
    # Pre-seed the durable counter as if 2 attempts already failed before restart.
    c._attempts["evt-0-0"] = 2  # type: ignore[attr-defined]
    calls = 0

    async def fake_handle(msg: Any) -> None:
        nonlocal calls
        if msg.offset() == 0:
            calls += 1
            raise RuntimeError("still poison after restart")

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(3)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    # base_attempts=2, so the first local attempt is attempt 3 >= max_retries → DLQ.
    assert calls == 1  # only one more attempt this delivery, not a fresh budget
    assert _dead_lettered(c) == [("t", 0, 0, "max_retries")]
    assert _committed(c) == [("t", 0, 2)]  # partition still drains past the poison


async def test_at_least_once_offset_advances_only_after_success_or_dlq() -> None:
    """At-least-once: an offset is committed only after success OR durable DLQ.

    Partition 0 succeeds fully; partition 1's head is a FatalError (malformed) →
    DLQ'd immediately (no retries) so it advances.  A message that is neither
    successfully processed nor dead-lettered must NEVER be committed — verified by
    the fact that dead_letter is awaited before the offset is marked handled.
    """
    from messaging.kafka.consumer.errors import FatalError  # type: ignore[import-untyped]

    c = _make_consumer(max_retries=3)
    sem = asyncio.Semaphore(8)
    dl_order: list[str] = []
    fatal_calls = 0

    async def fake_handle(msg: Any) -> None:
        nonlocal fatal_calls
        if msg.partition() == 1 and msg.offset() == 0:
            fatal_calls += 1
            raise FatalError("malformed payload")

    async def recording_dl(failure: Any, reason: str | None = None) -> None:
        dl_order.append(f"{failure.partition}:{failure.offset}:{reason}")
        c.dead_lettered.append((failure.topic, failure.partition, failure.offset, reason))  # type: ignore[attr-defined]

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]
    c.dead_letter = recording_dl  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(3)] + [_FakeMsg("t", 1, off) for off in range(2)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    # FatalError → dead-lettered immediately, no in-place retries.
    assert fatal_calls == 1
    assert dl_order == ["1:0:fatal"]
    # Both partitions advanced: p0 fully processed, p1 head DLQ'd then p1 drains.
    acked = sorted(_committed(c))
    assert acked == [("t", 0, 2), ("t", 1, 1)]


async def test_per_partition_independence_poison_does_not_block_other() -> None:
    """A poison on one partition never blocks commits on another partition."""
    c = _make_consumer(max_retries=2)
    sem = asyncio.Semaphore(8)

    async def fake_handle(msg: Any) -> None:
        if msg.partition() == 1:  # partition 1 entirely poison
            raise RuntimeError("partition 1 poison")

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(3)] + [_FakeMsg("t", 1, off) for off in range(2)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    # Partition 0 (all good) commits its high-water regardless of partition 1.
    acked = sorted(_committed(c))
    assert acked == [("t", 0, 2), ("t", 1, 1)]
    # Partition 1's messages were both dead-lettered (drained, not blocking p0).
    dl_offsets = sorted(o for (_t, p, o, _r) in _dead_lettered(c) if p == 1)
    assert dl_offsets == [0, 1]


async def test_dlq_write_failure_holds_offset_not_dropped() -> None:
    """At-least-once: a FAILED DLQ write must NOT advance the offset (no drop).

    Regression for the silent-drop hole: processing fails (e.g. Postgres down) →
    after max_retries the message routes to the DLQ → but the DLQ write ALSO needs
    Postgres → it fails too.  The message must be RETAINED (offset held as a
    barrier for retry on the next rebalance/restart), never committed-past and
    lost.  Higher offsets that succeeded cannot commit past the held poison head —
    a temporary head-of-line block is the correct trade vs. losing an article.
    """
    c = _make_consumer(max_retries=2)
    sem = asyncio.Semaphore(8)

    async def fake_handle(msg: Any) -> None:
        if msg.offset() == 0:  # poison HEAD, always fails
            raise RuntimeError("processing failed — nlp_db unavailable")

    async def failing_dead_letter(failure: Any, reason: str | None = None) -> None:
        # The DLQ store is ALSO down → the durable write fails.  Real DLQ-write
        # failures surface as DB/driver exceptions (NOT RuntimeError, which is
        # reserved for the intentional dead-letter-cap force-restart signal).
        raise ConnectionError("DLQ write failed — nlp_db unavailable")

    c._handle_message = fake_handle  # type: ignore[attr-defined,method-assign]
    c.dead_letter = failing_dead_letter  # type: ignore[attr-defined,method-assign]

    batch = [_FakeMsg("t", 0, off) for off in range(3)]
    await c._dispatch_batch(asyncio.get_event_loop(), batch, sem)

    # DLQ write failed → offset 0 is a commit BARRIER: nothing on partition 0
    # advances past it (offsets 1,2 succeeded but cannot commit past the held
    # head), so the poison is retried later rather than SILENTLY DROPPED.
    assert _committed(c) == []
    # It was NOT recorded as successfully dead-lettered.
    assert _dead_lettered(c) == []


async def test_dead_letter_persists_raw_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DLQ row carries the ORIGINAL message bytes so it is re-ingestable.

    Regression: ``_dead_letter_impl`` used to persist ``event_id.encode()`` and
    DISCARD ``failure.raw_payload`` — DLQ rows were not recoverable.  It must now
    write the real ``raw_payload`` bytes as ``payload_avro`` and RE-RAISE on a
    write failure (so ``_dead_letter_poison`` can hold the offset).
    """
    import nlp_pipeline.infrastructure.messaging.consumers.article_consumer as mod

    from messaging.kafka.consumer.base import FailureInfo  # type: ignore[import-untyped]

    captured: dict[str, Any] = {}

    class _FakeRepo:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def move_to_dlq(
            self,
            *,
            original_event_id: Any,
            topic: str,
            payload_avro: bytes,
            error_detail: str,
        ) -> None:
            captured["payload_avro"] = payload_avro
            captured["topic"] = topic
            captured["error_detail"] = error_detail

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(mod, "DLQRepository", _FakeRepo)

    c = object.__new__(ArticleProcessingConsumer)
    c._nlp_sf = lambda: _FakeSession()  # type: ignore[attr-defined,method-assign]

    raw = b"\x00\x01original-confluent-avro-bytes"
    failure: FailureInfo[None] = FailureInfo(
        event_id="019f6627-8af5-7686-b5c7-44da96ae1229",
        topic="content.article.stored.v1",
        partition=4,
        offset=262,
        attempt=5,
        last_error=RuntimeError("deep extraction failed"),
        raw_payload=raw,
    )
    await c._dead_letter_impl(failure)

    # The DLQ row carries the REAL message bytes (not the event_id), so the
    # dead-lettered article can be replayed later.
    assert captured["payload_avro"] == raw
    assert captured["topic"] == "content.article.stored.v1"


async def test_dead_letter_impl_reraises_on_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DLQ-store write failure PROPAGATES (so the caller can hold the offset)."""
    import nlp_pipeline.infrastructure.messaging.consumers.article_consumer as mod

    from messaging.kafka.consumer.base import FailureInfo  # type: ignore[import-untyped]

    class _BoomRepo:
        def __init__(self, session: Any) -> None:
            pass

        async def move_to_dlq(self, **kwargs: Any) -> None:
            raise RuntimeError("nlp_db down")

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(mod, "DLQRepository", _BoomRepo)

    c = object.__new__(ArticleProcessingConsumer)
    c._nlp_sf = lambda: _FakeSession()  # type: ignore[attr-defined,method-assign]

    failure: FailureInfo[None] = FailureInfo(
        event_id="019f6627-8af5-7686-b5c7-44da96ae1229",
        topic="content.article.stored.v1",
        partition=4,
        offset=262,
        attempt=5,
        last_error=RuntimeError("boom"),
        raw_payload=b"bytes",
    )
    with pytest.raises(RuntimeError, match="nlp_db down"):
        await c._dead_letter_impl(failure)


def test_contiguous_commit_targets_helper() -> None:
    """Unit-test the pure offset-selection helper directly."""
    msgs = [
        _FakeMsg("t", 0, 0),
        _FakeMsg("t", 0, 1),
        _FakeMsg("t", 0, 2),
        _FakeMsg("t", 1, 5),
        _FakeMsg("t", 1, 6),
    ]
    # Partition 0: 0,1 handled, 2 NOT → high-water = offset 1.
    # Partition 1: 5 NOT handled (first) → nothing committed.
    outcomes: dict[tuple[str, int], dict[int, bool]] = {
        ("t", 0): {0: True, 1: True, 2: False},
        ("t", 1): {5: False, 6: True},
    }
    targets = ArticleProcessingConsumer._contiguous_commit_targets(msgs, outcomes)
    acked = sorted((m.topic(), m.partition(), m.offset()) for m in targets)
    assert acked == [("t", 0, 1)]
