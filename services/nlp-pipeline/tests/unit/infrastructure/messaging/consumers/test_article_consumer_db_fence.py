"""fix/selfheal-db-fence — per-message DB-retry wall-time ceiling (FIX 1).

The root cause of the observed 8 h consumer freeze: when Postgres is OOM/dead,
``_settle_message`` retried a failing message IN PLACE (up to ``max_retries``
handler attempts, each up to the 900 s watchdog) and then wrote a dead-letter
row to the (also-dead) ``nlp_db.dlq`` with NO timeout.  A single message could
occupy its concurrency slot for well past ``max.poll.interval.ms`` (30 min), so
the run loop stopped calling ``consumer.poll()``, librdkafka fenced the consumer
out of the group (``MAXPOLL``), and it never rejoined.

These tests lock in the two ceilings that cap that wall time so a dead DB can
NEVER block one handler (and thus the poll loop) past ``max.poll.interval.ms``:

1. ``article_consumer_db_retry_ceiling_s`` — a persistently-failing DB yields
   control back to the poll loop within the ceiling with the offset UNCOMMITTED
   (barrier → redelivered), instead of exhausting all retries in one occupation.
2. ``article_consumer_dlq_write_timeout_s`` — a hung DLQ write returns (holding
   the offset, never dropping the article) instead of blocking forever.

The consumer is built via ``object.__new__`` so only the attributes the settle
path touches are wired (mirrors ``test_article_consumer_pipelined.py``).
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

from messaging.kafka.consumer.errors import FatalError, RetryableError

pytestmark = pytest.mark.asyncio

_TOPIC = "content.article.stored.v1"


class _FakeMsg:
    """Minimal stand-in for a confluent_kafka.Message."""

    def __init__(self, partition: int = 0, offset: int = 0) -> None:
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return _TOPIC

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset

    def value(self) -> bytes:
        return b"{}"


class _FakeConfig:
    # Small backoffs so the ceiling — not the backoff — dominates the timing.
    max_retries = 5
    initial_backoff_seconds = 0.001
    max_backoff_seconds = 0.01
    backoff_multiplier = 2.0
    enable_auto_commit = False
    group_id = "nlp-pipeline-group"


def _make_consumer(
    *,
    retry_ceiling_s: float,
    dlq_timeout_s: float = 30.0,
) -> ArticleProcessingConsumer:
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._settings = SimpleNamespace(  # type: ignore[attr-defined]
        article_consumer_db_retry_ceiling_s=retry_ceiling_s,
        article_consumer_dlq_write_timeout_s=dlq_timeout_s,
    )
    c._dedup_client = None  # type: ignore[attr-defined]  # → _durable_attempt_count returns 0

    async def _fixed_event_id(_msg: Any) -> str:
        return "evt-1"

    async def _noop_record(*_a: Any, **_k: Any) -> None:
        return None

    c._safe_event_id = _fixed_event_id  # type: ignore[attr-defined,method-assign]
    c._record_attempt = _noop_record  # type: ignore[attr-defined,method-assign]
    return c


async def test_persistent_db_failure_does_not_block_past_ceiling() -> None:
    """A persistently-failing DB must yield within the ceiling, NOT run all retries.

    ``_handle_message`` always raises a transient error with a small per-attempt
    delay.  With ``max_retries=5`` and a 0.15 s ceiling the handler must return a
    BARRIER (False → offset uncommitted → redelivered) well before 5 attempts
    could complete, and well under the wall time an unbounded retry loop would
    take.  This is what keeps the poll loop cycling (membership/heartbeats).
    """
    c = _make_consumer(retry_ceiling_s=0.15)

    attempts = {"n": 0}

    async def _always_fails(_msg: Any) -> None:
        attempts["n"] += 1
        await asyncio.sleep(0.05)  # simulate a slow-failing DB round-trip
        raise RetryableError("db is dead")

    c._handle_message = _always_fails  # type: ignore[attr-defined,method-assign]

    start = time.monotonic()
    handled = await c._settle_message(_FakeMsg())
    elapsed = time.monotonic() - start

    assert handled is False, "a ceiling-bounded persistent failure must return a barrier (uncommitted, redeliver)"
    # It stopped EARLY — did not burn the full 5-attempt budget.
    assert attempts["n"] < _FakeConfig.max_retries, f"expected early yield, ran all {attempts['n']} attempts"
    # And it returned within a small multiple of the ceiling (never the ~5x900s
    # a dead DB would otherwise take).
    assert elapsed < 0.15 + 0.20, f"settle took {elapsed:.3f}s — must stay near the 0.15s ceiling"


async def test_hung_dlq_write_returns_within_timeout() -> None:
    """A hung DLQ write (dead DB) must return a barrier within the DLQ timeout, not hang forever.

    A ``FatalError`` routes straight to ``_dead_letter_poison``; if the DLQ store
    (Postgres) hangs, the ``asyncio.timeout`` bound must fire so the handler
    returns False (hold the offset, redeliver on recovery) instead of blocking
    the concurrency slot — and the whole poll loop — indefinitely.
    """
    c = _make_consumer(retry_ceiling_s=5.0, dlq_timeout_s=0.15)

    async def _fatal(_msg: Any) -> None:
        raise FatalError("malformed / permanent")

    async def _hanging_dead_letter(*_a: Any, **_k: Any) -> None:
        await asyncio.sleep(3600)  # DLQ store is dead → write never returns

    c._handle_message = _fatal  # type: ignore[attr-defined,method-assign]
    c.dead_letter = _hanging_dead_letter  # type: ignore[attr-defined,method-assign]

    start = time.monotonic()
    handled = await c._settle_message(_FakeMsg())
    elapsed = time.monotonic() - start

    assert handled is False, "a timed-out DLQ write must HOLD the offset (barrier), never advance/drop"
    assert elapsed < 1.0, f"DLQ write hung for {elapsed:.3f}s — the timeout bound did not fire"


async def test_healthy_article_succeeds_and_is_unaffected_by_ceiling() -> None:
    """A healthy article SUCCEEDS on attempt 1 and returns True — the ceiling never interferes.

    Guards the #1 regression risk: the ceiling must NOT clip a legitimately slow
    (but succeeding) deep-extraction article.  Success returns before any ceiling
    logic runs.
    """
    c = _make_consumer(retry_ceiling_s=0.05)  # tiny ceiling — must be irrelevant to success

    async def _succeeds(_msg: Any) -> None:
        await asyncio.sleep(0.10)  # slower than the ceiling, but SUCCEEDS
        return None

    c._handle_message = _succeeds  # type: ignore[attr-defined,method-assign]

    handled = await c._settle_message(_FakeMsg())
    assert handled is True, "a successful (even slow) article must advance — the ceiling only bounds FAILURES"


async def test_exhausted_retries_dead_letter_on_recovered_db_advances() -> None:
    """When the DB is UP, retries still exhaust to a durable DLQ and the offset advances.

    Confirms FIX(1) did not break the poison-drain path: with a generous ceiling
    and a fast-failing (but writable) DLQ, a persistently-bad message reaches
    ``max_retries`` and is dead-lettered (handled=True → partition drains past it).
    """
    c = _make_consumer(retry_ceiling_s=60.0, dlq_timeout_s=30.0)

    async def _always_fails(_msg: Any) -> None:
        raise RetryableError("bad message")

    dlq_writes = {"n": 0}

    async def _ok_dead_letter(*_a: Any, **_k: Any) -> None:
        dlq_writes["n"] += 1  # DLQ store is healthy

    c._handle_message = _always_fails  # type: ignore[attr-defined,method-assign]
    c.dead_letter = _ok_dead_letter  # type: ignore[attr-defined,method-assign]

    handled = await c._settle_message(_FakeMsg())
    assert handled is True, "an exhausted-retry message with a healthy DLQ must advance (drain the poison)"
    assert dlq_writes["n"] == 1, "the message must be durably dead-lettered exactly once"
