"""BUG-1 regression — the article consumer's overridden ``run()`` must heartbeat.

Background (docs/audits/2026-06-22-backend-e2e-coverage-gaps.md, BUG-1)
----------------------------------------------------------------------
``ArticleProcessingConsumer`` overrides ``BaseKafkaConsumer.run`` with a
bounded-concurrency poll loop. The base loop calls ``_record_progress()`` on
EVERY healthy poll cycle (idle OR message) so the BP-704 ``ConsumerLivenessProbe``
sees a fresh heartbeat via ``seconds_since_progress()``. The overridden loop
previously NEVER recorded progress, so ``seconds_since_progress()`` stayed
``None`` forever; once the 90s startup grace elapsed the probe logged
``consumer_liveness_unhealthy_no_progress`` and ``/healthz`` returned 503
PERMANENTLY — even while articles were being processed successfully
(``article_processed`` logged).

These tests assert that one poll cycle of the overridden ``run()`` records
progress (so the liveness probe stays green), for BOTH an idle poll (empty
batch) and a poll that yields a batch. We drive ``run()`` directly with a
patched ``_poll_batch`` and stop after the first cycle, mirroring how
``test_article_consumer_concurrency`` constructs the consumer via
``object.__new__`` to avoid the full ML/DB dependency graph.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.asyncio


class _FakeMsg:
    """Minimal confluent_kafka.Message stand-in for the pipelined dispatch path."""

    def __init__(self, partition: int = 0, offset: int = 0) -> None:
        self._partition = partition
        self._offset = offset

    def topic(self) -> str:
        return "content.article.stored.v1"

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset


class _FakeConfig:
    enable_auto_commit = False
    poll_timeout_seconds = 0.01
    group_id = "nlp-article-consumer-test"


class _FakeSettings:
    article_consumer_concurrency = 4


def _make_consumer() -> ArticleProcessingConsumer:
    """Build a consumer with only the attributes ``run()`` touches.

    ``_last_progress_ts`` mirrors the base-class init value (-1.0 → "no tick
    yet") so we can assert the loop flips it to a real timestamp.
    """
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._settings = _FakeSettings()  # type: ignore[attr-defined]
    c._stop_event = asyncio.Event()  # type: ignore[attr-defined]
    # Base-class liveness state: -1.0 means "no progress tick recorded yet",
    # which makes seconds_since_progress() return None (the wedged-looking state).
    c._last_progress_ts = -1.0  # type: ignore[attr-defined]
    # fix/consumer-stall-selfheal: separate fetch-poll timestamp, -1.0 → "no real
    # consumer.poll() return yet" (seconds_since_fetch_poll() returns None).
    c._last_fetch_poll_ts = -1.0  # type: ignore[attr-defined]
    c._metrics = None  # type: ignore[attr-defined]
    # No-op the kafka/loop plumbing run() calls that we are not exercising.
    c._init_kafka = lambda: None  # type: ignore[attr-defined,method-assign]
    c._shutdown_kafka = lambda: None  # type: ignore[attr-defined,method-assign]
    c._maybe_apply_backpressure = lambda: None  # type: ignore[attr-defined,method-assign]

    async def _noop_loop() -> None:
        # Stand-in for _retry_loop / _connectivity_probe_loop: block until
        # cancelled by run()'s finally so the background tasks behave normally.
        await asyncio.Event().wait()

    c._retry_loop = _noop_loop  # type: ignore[attr-defined,method-assign]
    c._connectivity_probe_loop = _noop_loop  # type: ignore[attr-defined,method-assign]
    return c


async def _run_one_cycle(c: ArticleProcessingConsumer, batch: list[Any]) -> None:
    """Drive ``run()`` for exactly one poll cycle, then stop the loop.

    ``_poll_batch`` is patched to return ``batch`` once, then set the stop event
    so the ``while not self._stop_event.is_set()`` loop exits after this cycle.
    The settle/commit hooks are stubbed so we isolate the heartbeat behaviour
    (the dispatch path itself is covered by the concurrency/pipelined tests).
    """
    calls = {"poll": 0}

    async def fake_poll_batch(loop: Any, max_records: int) -> list[Any]:
        calls["poll"] += 1
        # Stop the loop AFTER this cycle so the heartbeat for this cycle runs.
        c._stop_event.set()  # type: ignore[attr-defined]
        return batch

    async def fake_settle(msg: Any) -> bool:
        return True

    c._poll_batch = fake_poll_batch  # type: ignore[attr-defined,method-assign]
    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]
    c._commit_sync = lambda msg: None  # type: ignore[attr-defined,method-assign]
    c._record_consumer_lag = lambda: None  # type: ignore[attr-defined,method-assign]

    await asyncio.wait_for(c.run(), timeout=2.0)
    assert calls["poll"] >= 1


async def test_run_records_progress_on_idle_poll() -> None:
    """An idle poll cycle (empty batch) still records a liveness heartbeat."""
    c = _make_consumer()
    assert c.seconds_since_progress() is None  # no tick yet

    await _run_one_cycle(c, batch=[])

    # The overridden run() must have heartbeated even though the poll was idle.
    assert c.seconds_since_progress() is not None
    assert c.seconds_since_progress() < 5.0


async def test_run_records_progress_on_batch_poll() -> None:
    """A poll cycle that yields a batch records a liveness heartbeat."""
    c = _make_consumer()
    assert c.seconds_since_progress() is None  # no tick yet

    await _run_one_cycle(c, batch=[_FakeMsg(partition=0, offset=0)])

    assert c.seconds_since_progress() is not None
    assert c.seconds_since_progress() < 5.0


async def test_poll_batch_records_fetch_poll_timestamp() -> None:
    """The REAL ``_poll_batch`` timestamps a fetch-poll on each ``consumer.poll()`` return.

    fix/consumer-stall-selfheal — this is the load-bearing discriminator for the
    lag-stall self-heal Gate 2.  ``_last_fetch_poll_ts`` is set ONLY where
    ``consumer.poll()`` actually returned (here, inside ``_poll_batch``), and is
    DELIBERATELY NOT set in the barrier-halt branch of ``run()`` (which keeps the
    BP-700 heartbeat fresh but does NOT call ``_poll_batch``).  So a wedged Kafka
    fetch — poll still called — keeps this fresh (→ self-heal), while a DB/DLQ
    outage halt that stops polling lets it go stale (→ self-heal SUPPRESSED, no
    crashloop).  We drive the real ``_poll_batch`` (not a patched stub).
    """
    c = _make_consumer()
    assert c.seconds_since_fetch_poll() is None  # no real poll yet

    fake_consumer = MagicMock()
    fake_consumer.poll.return_value = None  # idle poll → one call, then break
    c._consumer = fake_consumer  # type: ignore[attr-defined]

    loop = asyncio.get_running_loop()
    batch = await c._poll_batch(loop, max_records=4)

    assert batch == []
    assert fake_consumer.poll.called, "the real _poll_batch must invoke consumer.poll()"
    # Fetch-poll timestamp is now fresh — the wedge-vs-halt discriminator.
    assert c.seconds_since_fetch_poll() is not None
    assert c.seconds_since_fetch_poll() < 5.0
