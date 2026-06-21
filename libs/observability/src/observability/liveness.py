"""Consumer liveness probe for ``/healthz`` (FAILURE MODE 2 — consumer wedge).

Background
----------
The ``ohlcv-consumer`` wedge incident (adjacent to BP-700 "silent consumer
death") had two halves:

1. The librdkafka client hit
   ``GroupCoordinator: Connection setup timed out in state CONNECT`` and the
   consumer's poll loop stopped making progress.
2. The process stayed up with a **green** HTTP healthcheck, because the
   ``/metrics`` server's ``/healthz`` route returned ``200`` unconditionally
   (no ``liveness_probe`` was wired). A wedged consumer therefore looked
   healthy to Docker/k3s and was never restarted.

This module supplies the missing in-process liveness signal. A
:class:`ConsumerLivenessProbe` is bound to a running consumer and consulted by
``start_metrics_server(..., liveness_probe=...)``: ``/healthz`` flips to ``503``
once the consumer's poll loop goes stale (or its ``run()`` task dies), so the
container orchestrator restarts the wedged consumer instead of letting it limp.

Coordination with BP-700 / PLAN-0113
------------------------------------
The consumer poll loop in ``messaging.kafka.consumer.base`` already maintains a
liveness heartbeat (``_record_progress`` / ``seconds_since_progress``) and an
in-loop bounded-backoff reconnect. This probe is the *external observer* of that
heartbeat — it does NOT own the reconnect logic (PLAN-0113 owns
``consumer/base.py``). It only reads ``seconds_since_progress()`` and the bound
run()-task state to decide health, keeping the two layers cleanly separable.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from observability.logging import get_logger

logger = get_logger(__name__)

# Default grace, in seconds, before a just-started consumer that has not yet
# made its first poll-loop progress tick is considered unhealthy. A consumer
# normally records progress within one ``poll_timeout_seconds`` (≈1s) of
# subscribing, but the initial broker connect + group join can take longer
# (especially under the connection-setup-timeout this incident is about), so we
# allow a generous startup window before failing the probe.
_DEFAULT_STARTUP_GRACE_S = 90.0

# Default staleness ceiling, in seconds, after which a bound-and-started
# consumer that has stopped progressing is considered wedged. The poll loop
# heartbeats on every cycle (idle OR message), so any gap materially longer than
# ``max.poll.interval.ms`` (default 600s) means the loop is genuinely stuck, not
# merely busy on one slow message.
_DEFAULT_STALE_AFTER_S = 660.0


@runtime_checkable
class _ProgressReporter(Protocol):
    """Minimal surface a consumer must expose to be liveness-monitored.

    ``BaseKafkaConsumer`` satisfies this via its BP-700 heartbeat
    (``seconds_since_progress``); we depend on the structural protocol rather
    than importing the consumer class so ``libs/observability`` never takes a
    dependency on ``libs/messaging`` (keeps the dependency arrow one-way).
    """

    def seconds_since_progress(self) -> float | None:
        """Seconds since the last poll-loop progress, or ``None`` if no tick yet."""
        ...


class ConsumerLivenessProbe:
    """Callable ``() -> bool`` reporting whether a bound consumer is alive.

    Wire it into the metrics server so ``/healthz`` reflects real poll-loop
    progress::

        liveness = make_liveness_probe()
        start_metrics_server(..., liveness_probe=liveness)
        liveness.bind(consumer)              # after the consumer is constructed
        liveness.attach_task(consumer_task)  # after run() is scheduled

    Health rules (all must hold to return ``True``):

    * If no consumer is bound yet → healthy (process is still wiring up).
    * If a run()-task is attached and it has **finished** → unhealthy. A
      finished ``run()`` means the poll loop exited (crash or clean stop); a
      live consumer's ``run()`` never completes on its own. This catches the
      "``run()`` raised before the first poll" path that ``seconds_since_progress``
      alone cannot (it would still return ``None`` and look like startup).
    * If the consumer has not made its first progress tick
      (``seconds_since_progress() is None``) → healthy only within
      ``startup_grace_s`` of :meth:`bind`, otherwise unhealthy (a consumer that
      never starts polling is wedged on the initial connect).
    * Otherwise healthy iff ``seconds_since_progress() <= stale_after_s``.
    """

    def __init__(
        self,
        *,
        startup_grace_s: float = _DEFAULT_STARTUP_GRACE_S,
        stale_after_s: float = _DEFAULT_STALE_AFTER_S,
    ) -> None:
        self._consumer: _ProgressReporter | None = None
        self._task: asyncio.Task[object] | None = None
        self._startup_grace_s = startup_grace_s
        self._stale_after_s = stale_after_s
        # Wall-clock at bind time, used to bound the "no progress yet" grace.
        self._bound_at: float | None = None

    def bind(self, consumer: _ProgressReporter) -> None:
        """Attach the consumer whose poll-loop progress drives ``/healthz``."""
        self._consumer = consumer
        # Use the event-loop clock if running, else fall back to a monotonic-ish
        # wall clock; only relative deltas matter for the grace window.
        self._bound_at = _now()

    def attach_task(self, task: asyncio.Task[object]) -> None:
        """Attach the ``asyncio`` task running ``consumer.run()``.

        Lets the probe report unhealthy the instant ``run()`` finishes — the
        load-bearing fix for the "dead task, green healthcheck" symptom.
        """
        self._task = task

    def __call__(self) -> bool:
        """Return ``True`` while the bound consumer is making progress."""
        # Not yet bound: the process is still constructing dependencies. Report
        # healthy so a slow startup is not killed before the consumer exists.
        if self._consumer is None or self._bound_at is None:
            return True

        # A finished run() task means the poll loop is gone — wedged or crashed.
        # This is the case ``seconds_since_progress`` cannot see when run()
        # raised before its first progress tick.
        if self._task is not None and self._task.done():
            logger.warning("consumer_liveness_unhealthy_task_done")
            return False

        elapsed_since_progress = self._consumer.seconds_since_progress()
        if elapsed_since_progress is None:
            # No progress tick yet: healthy only inside the startup grace window.
            within_grace = (_now() - self._bound_at) <= self._startup_grace_s
            if not within_grace:
                logger.warning(
                    "consumer_liveness_unhealthy_no_progress",
                    grace_s=self._startup_grace_s,
                )
            return within_grace

        is_fresh = elapsed_since_progress <= self._stale_after_s
        if not is_fresh:
            logger.warning(
                "consumer_liveness_unhealthy_stale",
                seconds_since_progress=elapsed_since_progress,
                stale_after_s=self._stale_after_s,
            )
        return is_fresh


def _now() -> float:
    """Best-effort current time for relative grace/staleness deltas."""
    import time

    return time.time()


def make_liveness_probe(
    *,
    startup_grace_s: float = _DEFAULT_STARTUP_GRACE_S,
    stale_after_s: float = _DEFAULT_STALE_AFTER_S,
) -> ConsumerLivenessProbe:
    """Construct an unbound :class:`ConsumerLivenessProbe`.

    Call :meth:`ConsumerLivenessProbe.bind` once the consumer exists and
    :meth:`ConsumerLivenessProbe.attach_task` once ``run()`` is scheduled.
    """
    return ConsumerLivenessProbe(startup_grace_s=startup_grace_s, stale_after_s=stale_after_s)
