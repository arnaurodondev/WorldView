"""Tests for run()-task supervision (FAILURE MODE 2 — consumer wedge/crash).

These prove that a crashed ``run()`` no longer becomes a silent dead task while
the entry point hangs — instead it is logged loudly and raises ``ConsumerExited``
so the entry point exits non-zero (Docker restart), and that a normal stop-event
shutdown returns cleanly.
"""

from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from messaging.kafka.consumer.supervisor import ConsumerExited, run_consumer_supervised


class _RaisingConsumer:
    """run() raises immediately — models the connection-setup-timeout crash."""

    def __init__(self) -> None:
        self.stop_called = False

    async def run(self) -> None:
        raise ConnectionError("GroupCoordinator: Connection setup timed out in state CONNECT")

    def stop(self) -> None:
        self.stop_called = True


class _HangingConsumer:
    """run() blocks until stop() is signalled — models a healthy consumer."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self.stop_called = False

    async def run(self) -> None:
        await self._stop.wait()

    def stop(self) -> None:
        self.stop_called = True
        self._stop.set()


class _IgnoresStopConsumer:
    """run() never returns and ignores stop() — models a wedged drain."""

    async def run(self) -> None:
        await asyncio.sleep(3600)

    def stop(self) -> None:  # deliberately a no-op
        pass


class _RecordingProbe:
    """Captures the run() task attached by the supervisor."""

    def __init__(self) -> None:
        self.attached: asyncio.Task[object] | None = None

    def attach_task(self, task: asyncio.Task[object]) -> None:
        self.attached = task


@pytest.mark.asyncio
async def test_crashed_run_raises_consumer_exited() -> None:
    """A raising run() surfaces as ConsumerExited (so the entry point exits 1)."""
    consumer = _RaisingConsumer()
    stop_event = asyncio.Event()  # never set — proves we don't hang on it

    with pytest.raises(ConsumerExited) as excinfo:
        await run_consumer_supervised(consumer, stop_event)

    # The original connection error is preserved as the cause for logging.
    assert isinstance(excinfo.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_crashed_run_does_not_hang_on_unset_stop_event() -> None:
    """Regression: the wedge bug parked main() on ``stop_event.wait()`` forever.

    With the supervisor, a crash returns within the timeout regardless of the
    stop event never being set.
    """
    consumer = _RaisingConsumer()
    stop_event = asyncio.Event()

    with pytest.raises(ConsumerExited):
        await asyncio.wait_for(run_consumer_supervised(consumer, stop_event), timeout=5.0)


@pytest.mark.asyncio
async def test_crashed_run_logs_critical() -> None:
    """The crash is logged loudly — never a silent ``Task exception``."""
    consumer = _RaisingConsumer()
    stop_event = asyncio.Event()

    with capture_logs() as logs:
        with pytest.raises(ConsumerExited):
            await run_consumer_supervised(consumer, stop_event)

    assert any(
        entry.get("event") == "consumer_run_task_crashed" and entry.get("log_level") == "critical" for entry in logs
    )


@pytest.mark.asyncio
async def test_stop_event_drives_clean_shutdown() -> None:
    """A stop signal drains run() and returns normally (exit 0)."""
    consumer = _HangingConsumer()
    stop_event = asyncio.Event()

    async def _signal_stop() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    await asyncio.gather(
        run_consumer_supervised(consumer, stop_event),
        _signal_stop(),
    )
    assert consumer.stop_called is True


@pytest.mark.asyncio
async def test_attaches_run_task_to_liveness_probe() -> None:
    """The run() task is attached to the probe so /healthz sees a dead task."""
    consumer = _RaisingConsumer()
    stop_event = asyncio.Event()
    probe = _RecordingProbe()

    with pytest.raises(ConsumerExited):
        await run_consumer_supervised(consumer, stop_event, liveness_probe=probe)

    assert probe.attached is not None


@pytest.mark.asyncio
async def test_drain_timeout_cancels_wedged_run() -> None:
    """If run() ignores stop(), the drain times out and cancels — no hang."""
    consumer = _IgnoresStopConsumer()
    stop_event = asyncio.Event()

    async def _signal_stop() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    # Short graceful timeout so the test is fast; the supervisor must still
    # return (via cancel) rather than block forever on the un-stoppable run().
    await asyncio.gather(
        asyncio.wait_for(
            run_consumer_supervised(consumer, stop_event, graceful_stop_timeout_s=0.1),
            timeout=5.0,
        ),
        _signal_stop(),
    )
