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
import contextlib
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


def test_ledger_pending_counts_retained_offsets() -> None:
    """pending() reflects retained (registered + settled-uncommitted) offsets."""
    ledger = _PartitionCommitLedger()
    assert ledger.pending() == 0
    msgs = [_FakeMsg(0, off) for off in range(3)]
    for m in msgs:
        ledger.register(m)
    assert ledger.pending() == 3  # all in flight
    # Head barrier: settle 0 handled, 1 as barrier(False), 2 handled.
    ledger.settle(msgs[0], True)
    ledger.settle(msgs[1], False)
    ledger.settle(msgs[2], True)
    ledger.drain()  # commits only offset 0; 1(barrier) + 2 stay retained
    assert ledger.pending() == 2  # offset 0 forgotten, 1 and 2 held behind barrier


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
    # Only read by the base self-heal (not the run loop); a real value keeps any
    # incidental base-method call sane.
    max_poll_interval_ms = 1_800_000


class _FakeConfluentConsumer:
    def __init__(self) -> None:
        self.committed: list[tuple[int, int]] = []
        # RC-B barrier heartbeat instrumentation.
        self.poll_calls = 0
        self.paused: list[Any] = []
        self.resumed: list[Any] = []
        self._assignment: list[Any] = []

    def commit(self, msg: Any) -> None:
        self.committed.append((msg.partition(), msg.offset()))

    # ── RC-B: the barrier pauses the assignment and keeps polling to hold group
    # membership.  These stubs let the real ``_pause_all_assigned`` /
    # ``_resume_barrier_paused`` / barrier poll run without a live broker.
    def assignment(self) -> list[Any]:
        return list(self._assignment)

    def pause(self, tps: Any) -> None:
        self.paused.extend(tps)

    def resume(self, tps: Any) -> None:
        self.resumed.extend(tps)

    def poll(self, _timeout: float) -> None:
        self.poll_calls += 1
        return None


def _make_consumer(concurrency: int) -> ArticleProcessingConsumer:
    c = object.__new__(ArticleProcessingConsumer)
    c._config = _FakeConfig()  # type: ignore[attr-defined]
    c._consumer = _FakeConfluentConsumer()  # type: ignore[attr-defined]
    c._settings = SimpleNamespace(  # type: ignore[attr-defined]
        article_consumer_concurrency=concurrency,
        # Large default → the RC-B grace ceiling never trips in tests that do not
        # opt into it; the membership-preserving pause/resume path is exercised.
        article_consumer_barrier_drain_grace_s=1200.0,
    )
    c._stop_event = asyncio.Event()  # type: ignore[attr-defined]
    # RC-B state normally set in __init__ (bypassed by object.__new__).
    c._barrier_paused_partitions = set()  # type: ignore[attr-defined]
    c._paused_partitions = set()  # type: ignore[attr-defined]
    c._last_fetch_poll_ts = -1.0  # type: ignore[attr-defined]
    c._last_progress_ts = -1.0  # type: ignore[attr-defined]
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


def _drain_source_poll_batch(source: deque[_FakeMsg], idle_sleep: float = 0.002) -> Any:
    """Return a ``_poll_batch`` stub that drains up to ``max_records`` from a deque."""

    def fake_poll_batch(_loop: Any, max_records: int) -> Any:
        async def _poll() -> list[_FakeMsg]:
            out: list[_FakeMsg] = []
            while source and len(out) < max_records:
                out.append(source.popleft())
            if not out:
                await asyncio.sleep(idle_sleep)
            return out

        return _poll()

    return fake_poll_batch


async def test_run_poison_storm_cap_triggers_clean_shutdown_not_barrier() -> None:
    """The base dead_letter_cap RuntimeError must RESTART the consumer, not silently barrier.

    ``_settle_message`` deliberately re-raises the poison-storm cap RuntimeError
    (via ``_dead_letter_poison``).  The pipelined ``_worker`` must (a) NOT swallow
    it into a per-partition ``handled=False`` hold, (b) set the stop event for a
    clean drain, and (c) let ``run`` RE-RAISE it so the supervisor exits non-zero
    and the container restarts.
    """
    concurrency = 4
    c = _make_consumer(concurrency)
    # offset 0 OK; offset 1 trips the cap; offset 2 would be fine.
    source: deque[_FakeMsg] = deque([_FakeMsg(0, 0), _FakeMsg(0, 1), _FakeMsg(0, 2)])

    async def fake_settle(msg: Any) -> bool:
        if msg.offset() == 1:
            # Exact shape of messaging.kafka.consumer.base.dead_letter's cap raise.
            raise RuntimeError("Dead-letter cap 5000 exceeded — forcing restart")
        return True

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]
    c._poll_batch = _drain_source_poll_batch(source)  # type: ignore[attr-defined,method-assign]

    with pytest.raises(RuntimeError, match="Dead-letter cap"):
        await asyncio.wait_for(c.run(), timeout=5.0)

    # (b) clean-shutdown signal set — not a silent degraded barrier.
    assert c._stop_event.is_set()  # type: ignore[attr-defined]
    # (a)/(c) the capped offset (1) and everything after it were NOT acked; only
    # the contiguous prefix before the poison (offset 0) committed.
    committed_offsets = sorted(o for (_p, o) in c._consumer.committed)  # type: ignore[attr-defined]
    assert committed_offsets == [0]


async def test_run_backpressures_on_sustained_barrier_bounds_memory() -> None:
    """A sustained commit barrier must NOT let the ledger retain messages unbounded.

    offset 0 is a permanent barrier (DLQ/DB outage → handled=False); every later
    offset settles fine but is stuck behind it.  The loop must stop admitting once
    the ledger hits its cap so retained Message payloads stay bounded (no OOM),
    rather than draining all 400 available messages into memory.
    """
    concurrency = 4
    c = _make_consumer(concurrency)
    max_pending = max(concurrency * 8, 64)  # mirrors run()'s bound
    total_available = 400
    source: deque[_FakeMsg] = deque(_FakeMsg(0, off) for off in range(total_available))
    settled = {"count": 0}

    async def fake_settle(msg: Any) -> bool:
        settled["count"] += 1
        return msg.offset() != 0  # offset 0 is the permanent barrier

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]
    c._poll_batch = _drain_source_poll_batch(source, idle_sleep=0.001)  # type: ignore[attr-defined,method-assign]

    # The loop never self-stops under a sustained barrier; time-box it.
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(c.run(), timeout=0.5)

    # Backpressure held: admitted (== settle calls) is bounded by the ledger cap
    # plus at most one window of overshoot — NOT the full 400.
    assert settled["count"] <= max_pending + concurrency
    assert settled["count"] < total_available
    # Nothing committed: offset 0's barrier blocks the whole partition.
    assert c._consumer.committed == []  # type: ignore[attr-defined]


# ───────────────── RC-B: barrier keeps group membership ─────────────────────
# fix/pollloop-selfheal-ceiling.  The OLD saturated-window barrier stopped
# calling ``consumer.poll()`` entirely while it waited for in-flight work to
# drain, refreshing only the BP-700 heartbeat.  A hung in-flight coroutine then
# stalled the barrier forever → no poll → the broker session-timed-out and
# FENCED the consumer out of the group (0 members → the 2.4 h backlog wedge).
# The barrier now PAUSES the assignment and KEEPS polling (paused → no records
# admitted, but the group heartbeat is maintained), and bounds a genuinely hung
# drain so it eventually stops faking liveness and lets the base self-heal act.

from collections import namedtuple

_TP = namedtuple("_TP", ["topic", "partition"])


async def test_barrier_keeps_polling_to_hold_group_membership_during_slow_drain() -> None:
    """A saturated window KEEPS calling poll() (heartbeat) while the drain runs.

    concurrency=1, so admitting one slow handler saturates the window.  While it
    drains, the barrier must PAUSE the assignment and keep polling — proving the
    consumer stays a live group member through a slow batch — and both messages
    must still commit exactly once (at-least-once preserved, no data loss).
    """
    c = _make_consumer(concurrency=1)
    c._consumer._assignment = [_TP(_TOPIC, 0)]  # type: ignore[attr-defined]

    source: deque[_FakeMsg] = deque([_FakeMsg(0, 0, tier="deep"), _FakeMsg(0, 1, tier="light")])
    done = {"n": 0}

    async def fake_settle(msg: Any) -> bool:
        # First (offset 0) is slow enough to force a barrier while offset 1 waits.
        await asyncio.sleep(0.20 if msg.offset() == 0 else 0.01)
        done["n"] += 1
        if done["n"] >= 2:
            c._stop_event.set()  # type: ignore[attr-defined]
        return True

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]
    c._poll_batch = _drain_source_poll_batch(source, idle_sleep=0.005)  # type: ignore[attr-defined,method-assign]

    await asyncio.wait_for(c.run(), timeout=5.0)

    # Membership maintained: the barrier drove real poll() calls (heartbeat) and
    # paused the assignment while the slow handler drained.
    assert c._consumer.poll_calls > 0, "barrier never polled → consumer would be fenced out of the group"  # type: ignore[attr-defined]
    assert c._consumer.paused, "barrier never paused the assignment before polling"  # type: ignore[attr-defined]
    assert c._consumer.resumed, "barrier never resumed the assignment"  # type: ignore[attr-defined]
    # At-least-once preserved: both offsets processed and committed exactly once.
    assert done["n"] == 2
    assert sorted(c._consumer.committed) == [(0, 0), (0, 1)]  # type: ignore[attr-defined]


async def test_hung_drain_past_grace_stops_faking_liveness_so_selfheal_can_act() -> None:
    """A genuinely hung drain (no completion for the grace) stops polling + heartbeating.

    concurrency=1 with a handler that NEVER completes saturates the window with
    zero progress.  Within the (tiny) grace the barrier keeps polling +
    heartbeating; PAST the grace it must stop BOTH so the base lag-stall self-heal
    (fetch-poll + heartbeat both stale → RC-C / fence force-exit) can escalate,
    instead of the consumer faking liveness forever (the residual wedge).
    """
    c = _make_consumer(concurrency=1)
    c._consumer._assignment = [_TP(_TOPIC, 0)]  # type: ignore[attr-defined]
    c._settings.article_consumer_barrier_drain_grace_s = 0.15  # type: ignore[attr-defined]

    # Count real liveness refreshes.  ``_record_fetch_poll`` is a base method;
    # wrap it so we can see when the barrier stops calling poll (fetch-poll stale).
    progress_calls = {"n": 0}
    c._record_progress = lambda: progress_calls.__setitem__("n", progress_calls["n"] + 1)  # type: ignore[attr-defined,method-assign]

    hung = asyncio.Event()  # never set → the handler blocks forever

    async def fake_settle(_msg: Any) -> bool:
        await hung.wait()  # simulates the hung DB await (never returns)
        return True

    c._settle_message = fake_settle  # type: ignore[attr-defined,method-assign]
    source: deque[_FakeMsg] = deque([_FakeMsg(0, 0), _FakeMsg(0, 1)])
    c._poll_batch = _drain_source_poll_batch(source, idle_sleep=0.005)  # type: ignore[attr-defined,method-assign]

    run_task = asyncio.create_task(c.run())
    # Let the window saturate and the barrier run WITHIN grace (polls + heartbeats).
    await asyncio.sleep(0.10)
    polls_in_grace = c._consumer.poll_calls  # type: ignore[attr-defined]
    progress_in_grace = progress_calls["n"]
    assert polls_in_grace > 0, "barrier did not poll during the in-grace window"
    assert progress_in_grace > 0, "barrier did not heartbeat during the in-grace window"

    # Now cross the grace and let several poll_timeouts elapse.
    await asyncio.sleep(0.40)
    polls_after_grace_1 = c._consumer.poll_calls  # type: ignore[attr-defined]
    progress_after_grace_1 = progress_calls["n"]
    await asyncio.sleep(0.20)
    polls_after_grace_2 = c._consumer.poll_calls  # type: ignore[attr-defined]
    progress_after_grace_2 = progress_calls["n"]

    # Past the grace both liveness signals FREEZE — poll() and the BP-700
    # heartbeat stop — so ``seconds_since_fetch_poll`` / ``seconds_since_progress``
    # climb and the base self-heal escalates instead of a silent forever-wedge.
    assert polls_after_grace_2 == polls_after_grace_1, "barrier still polling past grace → self-heal can never act"
    assert (
        progress_after_grace_2 == progress_after_grace_1
    ), "barrier still heartbeating past grace → self-heal suppressed forever"
    # The assignment was resumed (not left paused) so its frozen position reads as
    # a real wedge to the self-heal (paused partitions are excluded).
    assert not c._barrier_paused_partitions, "assignment must be resumed once the barrier gives up"  # type: ignore[attr-defined]
    # Nothing was committed (the head never settled) — at-least-once preserved.
    assert c._consumer.committed == []  # type: ignore[attr-defined]

    # Teardown: release the hung handler and stop the loop.
    hung.set()
    c._stop_event.set()  # type: ignore[attr-defined]
    with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
        await asyncio.wait_for(run_task, timeout=2.0)
    run_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await run_task
