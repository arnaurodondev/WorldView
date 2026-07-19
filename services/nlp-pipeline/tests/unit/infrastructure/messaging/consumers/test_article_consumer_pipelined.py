"""fix/nlp-throughput — continuously-refilled (pipelined) article dispatch.

The prior dispatch path polled a batch of up to ``article_consumer_concurrency``
messages and blocked on ``asyncio.gather`` until EVERY one settled before
polling again.  With ~40% of live articles routing to the DEEP tier
(Qwen3-235B, ~170s) a 16-message batch almost always contained a DEEP article,
so the whole batch — and its 15 fast LIGHT slots — was gated by ~170s.  These
tests lock in the fix:

1. LEDGER SAFETY — :class:`_PartitionCommitLedger` commits an offset only once
   every lower offset on its partition has SETTLED-and-handled; an in-flight or
   barrier(``False``) head blocks the ack (no silent-drop under at-least-once),
   and partitions advance independently.
2. NO BATCH BARRIER — in the real ``run`` loop a slow DEEP article on one
   partition must NOT delay fast LIGHT articles on other partitions from
   completing and committing; the concurrency window stays continuously full.

The consumer is built via ``object.__new__`` so only the attributes the dispatch
path touches are wired (mirrors ``test_article_consumer_concurrency.py``).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from types import SimpleNamespace
from typing import Any

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
    _PartitionCommitLedger,
)

pytestmark = pytest.mark.asyncio

_TOPIC = "content.article.stored.v1"


class _FakeMsg:
    """Minimal stand-in for a confluent_kafka.Message."""

    def __init__(self, partition: int, offset: int, tier: str = "light") -> None:
        self._partition = partition
        self._offset = offset
        self.tier = tier

    def topic(self) -> str:
        return _TOPIC

    def partition(self) -> int:
        return self._partition

    def offset(self) -> int:
        return self._offset


# ─────────────────────────── ledger unit tests ────────────────────────────


def test_ledger_commits_contiguous_settled_prefix() -> None:
    """Offsets ack only through the unbroken settled-and-handled prefix."""
    ledger = _PartitionCommitLedger()
    msgs = [_FakeMsg(0, off) for off in range(4)]
    for m in msgs:
        ledger.register(m)

    # Settle out of order: 0, 2, 3 handled but 1 still in flight → cursor stuck at 0.
    ledger.settle(msgs[0], True)
    ledger.settle(msgs[2], True)
    ledger.settle(msgs[3], True)
    targets = ledger.drain()
    assert [(m.partition(), m.offset()) for m in targets] == [(0, 0)]

    # Now offset 1 settles → the whole 1,2,3 prefix becomes committable to 3.
    ledger.settle(msgs[1], True)
    targets = ledger.drain()
    assert [(m.partition(), m.offset()) for m in targets] == [(0, 3)]

    # Nothing left to commit.
    assert ledger.drain() == []


def test_ledger_barrier_false_blocks_commit_past_it() -> None:
    """A ``handled=False`` head is a commit barrier (retry on restart, never acked past)."""
    ledger = _PartitionCommitLedger()
    msgs = [_FakeMsg(0, off) for off in range(3)]
    for m in msgs:
        ledger.register(m)

    ledger.settle(msgs[0], True)
    ledger.settle(msgs[1], False)  # not durably settled → barrier
    ledger.settle(msgs[2], True)  # completed, but stuck behind the barrier

    targets = ledger.drain()
    # Only offset 0 is safe to commit; 1 (False) blocks, so 2 stays uncommitted.
    assert [(m.offset()) for m in targets] == [0]
    # Draining again must not advance past the barrier.
    assert ledger.drain() == []


def test_ledger_partitions_advance_independently() -> None:
    """A stalled head on one partition never blocks another partition's commit."""
    ledger = _PartitionCommitLedger()
    p0 = [_FakeMsg(0, off) for off in range(2)]
    p1 = [_FakeMsg(1, off) for off in range(2)]
    for m in (*p0, *p1):
        ledger.register(m)

    # Partition 0 head (offset 0) still in flight; partition 1 fully settled.
    ledger.settle(p0[1], True)
    ledger.settle(p1[0], True)
    ledger.settle(p1[1], True)

    targets = sorted((m.partition(), m.offset()) for m in ledger.drain())
    # p0 blocked at its in-flight head; p1 advances to its high-water (offset 1).
    assert targets == [(1, 1)]


def test_ledger_cursor_anchors_to_first_seen_offset() -> None:
    """The commit cursor starts at the first offset seen (mid-partition resume)."""
    ledger = _PartitionCommitLedger()
    # Fetch position resumed at offset 100 (earlier offsets already committed).
    msgs = [_FakeMsg(0, off) for off in (100, 101, 102)]
    for m in msgs:
        ledger.register(m)
        ledger.settle(m, True)

    targets = ledger.drain()
    assert [m.offset() for m in targets] == [102]


# ─────────────────────── run-loop anti-barrier test ────────────────────────


class _FakeConfig:
    enable_auto_commit = False
    poll_timeout_seconds = 0.02
    group_id = "nlp-pipeline-group"


class _FakeConfluentConsumer:
    def __init__(self) -> None:
        self.committed: list[tuple[int, int]] = []

    def commit(self, msg: Any) -> None:
        self.committed.append((msg.partition(), msg.offset()))


def _make_consumer(concurrency: int) -> ArticleProcessingConsumer:
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._consumer = _FakeConfluentConsumer()  # type: ignore[attr-defined]
    c._settings = SimpleNamespace(article_consumer_concurrency=concurrency)  # type: ignore[attr-defined]
    c._stop_event = asyncio.Event()  # type: ignore[attr-defined]
    # No-op the infra hooks the loop calls.
    c._init_kafka = lambda: None  # type: ignore[attr-defined,method-assign]
    c._shutdown_kafka = lambda: None  # type: ignore[attr-defined,method-assign]
    c._record_progress = lambda: None  # type: ignore[attr-defined,method-assign]
    c._maybe_apply_backpressure = lambda: None  # type: ignore[attr-defined,method-assign]
    c._record_consumer_lag = lambda: None  # type: ignore[attr-defined,method-assign]
    c._commit_sync = lambda msg: c._consumer.commit(msg)  # type: ignore[attr-defined,method-assign]

    async def _idle_bg() -> None:  # retry/probe loops — never fire in the test
        await asyncio.sleep(3600)

    c._retry_loop = _idle_bg  # type: ignore[attr-defined,method-assign]
    c._connectivity_probe_loop = _idle_bg  # type: ignore[attr-defined,method-assign]
    return c


async def test_run_no_batch_barrier_light_commits_while_deep_runs() -> None:
    """A slow DEEP article must not gate fast LIGHT articles (the whole fix).

    Partition 0 offset 0 is a slow DEEP article (0.30s).  Partitions 1..N carry
    fast LIGHT articles (0.01s).  Under the OLD batch barrier every LIGHT article
    that shared the poll batch would wait for the DEEP one before ANY commit.
    Here we assert the LIGHT articles both COMPLETE and COMMIT well before the
    DEEP article finishes — proving the window refills continuously.
    """
    concurrency = 8
    c = _make_consumer(concurrency)

    # One slow DEEP on p0, then many fast LIGHT on p1..p6 (offset 0 each).
    source: deque[_FakeMsg] = deque()
    source.append(_FakeMsg(0, 0, tier="deep"))
    for p in range(1, 7):
        source.append(_FakeMsg(p, 0, tier="light"))

    total = len(source)
    settle_order: list[tuple[int, int, str]] = []
    commit_times: dict[tuple[int, int], float] = {}
    deep_done_at: dict[str, float] = {}
    in_flight = 0
    peak = 0
    done = 0
    t0 = time.monotonic()

    async def fake_settle(msg: Any) -> bool:
        nonlocal in_flight, peak, done
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.30 if msg.tier == "deep" else 0.01)
        in_flight -= 1
        settle_order.append((msg.partition(), msg.offset(), msg.tier))
        if msg.tier == "deep":
            deep_done_at["t"] = time.monotonic() - t0
        done += 1
        if done >= total:
            c._stop_event.set()  # type: ignore[attr-defined]
        return True

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]

    # Record commit wall-clock the moment each offset is acked.
    _orig_commit = c._consumer.commit  # type: ignore[attr-defined]

    def _timed_commit(msg: Any) -> None:
        commit_times[(msg.partition(), msg.offset())] = time.monotonic() - t0
        _orig_commit(msg)

    c._commit_sync = _timed_commit  # type: ignore[attr-defined,method-assign]

    def fake_poll_batch(_loop: Any, max_records: int) -> Any:
        async def _poll() -> list[_FakeMsg]:
            out: list[_FakeMsg] = []
            while source and len(out) < max_records:
                out.append(source.popleft())
            if not out:
                await asyncio.sleep(0.005)  # mimic poll_timeout idle
            return out

        return _poll()

    c._poll_batch = fake_poll_batch  # type: ignore[attr-defined,method-assign]

    await asyncio.wait_for(c.run(), timeout=5.0)

    # All messages processed and committed exactly once each.
    assert done == total
    assert len(c._consumer.committed) == total  # type: ignore[attr-defined]
    assert sorted(c._consumer.committed) == sorted(  # type: ignore[attr-defined]
        [(0, 0)] + [(p, 0) for p in range(1, 7)]
    )

    # Concurrency ran wide (DEEP + several LIGHT overlapped), never exceeding bound.
    assert peak <= concurrency
    assert peak >= 3  # real overlap: the DEEP and LIGHTs ran together

    # THE FIX: every LIGHT partition committed BEFORE the slow DEEP finished.
    deep_finish = deep_done_at["t"]
    light_commit_times = [t for (p, _o), t in commit_times.items() if p != 0]
    assert light_commit_times, "expected LIGHT commits"
    assert max(light_commit_times) < deep_finish, (
        f"LIGHT commits ({max(light_commit_times):.3f}s) must precede DEEP finish "
        f"({deep_finish:.3f}s) — batch barrier regression"
    )


async def test_run_respects_concurrency_bound() -> None:
    """The in-flight window never exceeds ``article_consumer_concurrency``."""
    concurrency = 4
    c = _make_consumer(concurrency)

    source: deque[_FakeMsg] = deque(_FakeMsg(p, 0) for p in range(20))
    total = len(source)
    in_flight = 0
    peak = 0
    done = 0

    async def fake_settle(_msg: Any) -> bool:
        nonlocal in_flight, peak, done
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        done += 1
        if done >= total:
            c._stop_event.set()  # type: ignore[attr-defined]
        return True

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]

    def fake_poll_batch(_loop: Any, max_records: int) -> Any:
        async def _poll() -> list[_FakeMsg]:
            out: list[_FakeMsg] = []
            while source and len(out) < max_records:
                out.append(source.popleft())
            if not out:
                await asyncio.sleep(0.005)
            return out

        return _poll()

    c._poll_batch = fake_poll_batch  # type: ignore[attr-defined,method-assign]

    await asyncio.wait_for(c.run(), timeout=5.0)

    assert done == total
    assert peak <= concurrency
    assert peak == concurrency  # actually saturated the window
    assert len(c._consumer.committed) == total  # type: ignore[attr-defined]
