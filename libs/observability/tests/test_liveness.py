"""Tests for the consumer liveness probe (FAILURE MODE 2 — consumer wedge).

These prove the probe flips ``/healthz`` to unhealthy when a consumer wedges or
its run() task dies, and stays healthy during normal startup/progress.
"""

from __future__ import annotations

import asyncio

import pytest

from observability.liveness import ConsumerLivenessProbe, make_liveness_probe


class _FakeConsumer:
    """Stand-in exposing only ``seconds_since_progress`` (the probe's contract)."""

    def __init__(self, seconds: float | None) -> None:
        self._seconds = seconds

    def seconds_since_progress(self) -> float | None:
        return self._seconds


def test_unbound_probe_is_healthy() -> None:
    """Before any consumer is bound the process is still wiring up → healthy."""
    probe = make_liveness_probe()
    assert probe() is True


def test_bound_with_fresh_progress_is_healthy() -> None:
    probe = make_liveness_probe(stale_after_s=660.0)
    probe.bind(_FakeConsumer(seconds=5.0))
    assert probe() is True


def test_bound_with_stale_progress_is_unhealthy() -> None:
    """A poll loop that stopped progressing past the ceiling is wedged."""
    probe = make_liveness_probe(stale_after_s=660.0)
    probe.bind(_FakeConsumer(seconds=999.0))
    assert probe() is False


def test_no_progress_within_grace_is_healthy() -> None:
    """A just-started consumer (no tick yet) is healthy inside the grace window."""
    probe = ConsumerLivenessProbe(startup_grace_s=90.0)
    probe.bind(_FakeConsumer(seconds=None))
    assert probe() is True


def test_no_progress_past_grace_is_unhealthy() -> None:
    """A consumer that never makes its first tick past the grace is wedged."""
    probe = ConsumerLivenessProbe(startup_grace_s=0.01)
    probe.bind(_FakeConsumer(seconds=None))
    # Force the bind timestamp comfortably into the past so the 0.01s grace has
    # elapsed deterministically (no real sleep needed).
    probe._bound_at = (probe._bound_at or 0.0) - 1.0
    assert probe() is False


@pytest.mark.asyncio
async def test_finished_run_task_is_unhealthy_even_with_no_progress() -> None:
    """The load-bearing case: run() crashed before its first poll tick.

    ``seconds_since_progress`` would still be ``None`` (looks like startup), but
    a finished run() task means the loop is dead → must report unhealthy.
    """

    async def _boom() -> None:
        raise ConnectionError("GroupCoordinator: Connection setup timed out")

    probe = ConsumerLivenessProbe(startup_grace_s=10_000.0)  # generous grace
    probe.bind(_FakeConsumer(seconds=None))

    task: asyncio.Task[None] = asyncio.create_task(_boom())
    probe.attach_task(task)
    # Let the task run to completion (and fail).
    with pytest.raises(ConnectionError):
        await task

    # Even though we're well within the startup grace and have no progress tick,
    # the dead run() task forces an unhealthy verdict.
    assert probe() is False


@pytest.mark.asyncio
async def test_live_run_task_does_not_force_unhealthy() -> None:
    """A still-running run() task must not by itself fail the probe."""

    async def _runs() -> None:
        await asyncio.sleep(10.0)

    probe = ConsumerLivenessProbe(startup_grace_s=90.0)
    probe.bind(_FakeConsumer(seconds=2.0))
    task: asyncio.Task[None] = asyncio.create_task(_runs())
    probe.attach_task(task)
    try:
        assert probe() is True
    finally:
        task.cancel()
