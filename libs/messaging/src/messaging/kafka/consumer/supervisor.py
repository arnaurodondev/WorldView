"""Run()-task supervision for standalone consumer entry points.

FAILURE MODE 2 — consumer wedge / crash
---------------------------------------
Every standalone consumer ``_main.py`` historically used this shape::

    consumer_task = asyncio.create_task(consumer.run())
    await stop_event.wait()          # (A)
    consumer.stop()
    await asyncio.wait_for(consumer_task, timeout=30.0)

The bug: if ``consumer.run()`` *raises* (e.g. the initial ``_init_kafka()``
connect hits ``GroupCoordinator: Connection setup timed out``, or the BP-700
bounded-backoff reconnect budget is exhausted), the ``consumer_task`` becomes a
**failed Future that nobody awaits**, while ``main()`` is parked forever on the
``await stop_event.wait()`` at (A) — ``stop_event`` is only ever set by a signal
handler, which a dead run() task does not trigger. The result is the exact
reported symptom:

* ``Task exception was never retrieved ... <Consumer>.run() done`` — the
  exception is never retrieved because nothing awaits the dead task; and
* the process stays up with a green HTTP healthcheck making zero progress.

:func:`run_consumer_supervised` replaces that shape. It **races** the run()
task against the stop event, so a crashed run() unblocks ``main()`` immediately,
the exception is retrieved and logged loudly, and the function raises
:class:`ConsumerExited` so the entry point can ``sys.exit(non-zero)`` and let
Docker/k3s restart the container cleanly — never a silently-dead task behind a
green healthcheck.

Scope boundary (R42 / PLAN-0113)
--------------------------------
This module supervises run() **from the entry point** (the layer that owns the
asyncio task and the process exit code). It deliberately does NOT touch the
in-loop reconnect logic inside ``messaging.kafka.consumer.base`` — that is
PLAN-0113's surface. The two compose: base.py keeps the loop alive across
*transient* blips; this supervisor ensures a *terminal* run() exit fails loudly
instead of wedging the process.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Protocol

from observability.logging import get_logger

logger = get_logger(__name__)

# How long to wait for a graceful stop (run() to return after ``stop()``) before
# cancelling the task. Mirrors the historical ``wait_for(..., timeout=30.0)``.
_DEFAULT_GRACEFUL_STOP_TIMEOUT_S = 30.0


class ConsumerExited(RuntimeError):  # noqa: N818 — intentional non-Error name; signals a process-exit condition, not a defect
    """Raised when a supervised consumer's ``run()`` terminated unexpectedly.

    Carries the original exception (if any) as ``__cause__`` so the entry point
    can log it and exit non-zero. A clean stop-event-driven shutdown does NOT
    raise this — it returns normally.
    """


class _SupervisableConsumer(Protocol):
    """Structural type for a consumer this supervisor can drive."""

    async def run(self) -> None:
        """Run the poll loop until :meth:`stop` is signalled or an error occurs."""
        ...

    def stop(self) -> None:
        """Signal the poll loop to exit at the next opportunity."""
        ...


async def run_consumer_supervised(
    consumer: _SupervisableConsumer,
    stop_event: asyncio.Event,
    *,
    graceful_stop_timeout_s: float = _DEFAULT_GRACEFUL_STOP_TIMEOUT_S,
    liveness_probe: object | None = None,
) -> None:
    """Run ``consumer.run()`` under supervision until stop OR a run() exit.

    Behaviour:

    * On **stop signal** (``stop_event`` set by a SIGTERM/SIGINT handler):
      calls ``consumer.stop()``, awaits the task up to
      ``graceful_stop_timeout_s``, cancels it if it overruns, and returns
      normally (clean shutdown, exit 0).
    * On **run() raising** (connection error, exhausted reconnect budget, any
      unexpected exception): logs ``consumer_run_task_crashed`` at ``critical``
      and raises :class:`ConsumerExited` (with the original exception as
      ``__cause__``) so the caller exits non-zero and Docker restarts it.
    * On **run() returning on its own** without a stop signal (should never
      happen for a healthy consumer — the loop only exits when stopped): treats
      it as an unexpected exit and raises :class:`ConsumerExited`.

    Args:
        consumer: object with async ``run()`` and sync ``stop()``.
        stop_event: set by the entry point's signal handler on SIGTERM/SIGINT.
        graceful_stop_timeout_s: seconds to await graceful drain after stop().
        liveness_probe: optional probe exposing ``attach_task(task)``; if given,
            the run() task is attached so ``/healthz`` flips to 503 the moment
            run() finishes (covers a crash before the first poll-loop tick).

    Raises:
        ConsumerExited: when run() terminated for any reason other than a
            stop-event-driven graceful shutdown.
    """
    run_task: asyncio.Task[None] = asyncio.create_task(consumer.run())

    # Wire the run() task into the liveness probe (if supplied) so a dead task
    # is observable at /healthz even before the first heartbeat. Duck-typed to
    # avoid a hard import dependency on observability's probe class.
    attach = getattr(liveness_probe, "attach_task", None)
    if callable(attach):
        attach(run_task)

    stop_wait: asyncio.Task[bool] = asyncio.create_task(stop_event.wait())

    try:
        # Race: whichever of (run() exits) / (stop requested) happens first wins.
        done, _pending = await asyncio.wait(
            {run_task, stop_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        # The stop-wait helper is bookkeeping only; never leak it.
        if not stop_wait.done():
            stop_wait.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_wait

    if run_task in done:
        # run() finished WITHOUT a stop signal → crash or unexpected clean exit.
        exc = run_task.exception()  # retrieves the exception (no "never retrieved")
        if exc is not None:
            logger.critical(
                "consumer_run_task_crashed",
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise ConsumerExited("consumer run() crashed") from exc
        logger.critical("consumer_run_task_exited_unexpectedly")
        raise ConsumerExited("consumer run() exited without a stop signal")

    # Normal path: stop requested. Drain the poll loop gracefully.
    logger.info("consumer_stop_requested_draining")
    consumer.stop()
    try:
        await asyncio.wait_for(run_task, timeout=graceful_stop_timeout_s)
    except TimeoutError:
        logger.warning(
            "consumer_graceful_stop_timeout_cancelling",
            timeout_s=graceful_stop_timeout_s,
        )
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
    except Exception as exc:  # run() raised *during* the drain — surface it.
        logger.critical(
            "consumer_run_task_crashed_during_drain",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise ConsumerExited("consumer run() crashed during shutdown drain") from exc
