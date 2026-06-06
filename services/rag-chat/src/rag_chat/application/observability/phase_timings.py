"""Per-phase wall-clock instrumentation for the chat orchestrator.

PLAN-0099 W1-T03 — per-phase wall-clock instrumentation.

The chat-eval acceptance gate reports end-to-end latency only, leaving the
operator unable to decompose 89s of LLM-dominated latency into individual
phases (classifier / first-LLM / tool-fanout / second-LLM / streaming).
This module provides:

  * ``PhaseTimings`` — a thin wrapper around ``dict[str, float]`` that stores
    elapsed milliseconds per named phase.  Multiple observations under the
    same name accumulate (sum of all measurements) so the per-iteration LLM
    turns inside the agent loop add up cleanly.

  * ``phase()`` — an ``@asynccontextmanager`` that records the wall-clock
    elapsed time of the wrapped block in ``ms`` using ``time.monotonic()``
    (immune to NTP/wall-clock jumps).  The elapsed time is ALWAYS recorded
    even when the wrapped block raises — measuring failed phases is just
    as important as successful ones (a 60s LLM timeout is a phase too).

The chat orchestrator wraps each pipeline phase in ``async with phase(name,
timings):`` and emits the final dict as a ``chat_phase_timings_ms`` structlog
event AND as part of the terminal SSE ``done`` event so the chat-eval
harness can scrape it from artifacts.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import AsyncIterator

import structlog

log = structlog.get_logger(__name__)

# PLAN-0102 W4 T-W4-02: ``record_once`` strict-mode toggle.
#
# In test environments we want a double-record to FAIL LOUDLY (raise an
# AssertionError) so the test suite catches the regression. In production
# we want a WARN log + accumulate, because raising would crash the chat
# stream over a metrics-only bug — the user-facing answer is unaffected.
# The harness sets ``PHASE_TIMINGS_STRICT=1`` in conftest so tests assert
# the invariant; production leaves it unset and gets the warn-and-sum
# behaviour.
_STRICT_ENV_VAR = "PHASE_TIMINGS_STRICT"


class PhaseTimings:
    """Accumulator for per-phase wall-clock observations.

    Calling ``record("foo", 12.3)`` on an empty instance sets the entry to
    12.3 ms; calling it again with 4.5 yields 16.8 ms.  This sum-semantics
    matches the agent-loop reality where the SAME named phase (e.g.
    ``llm_tool_planning``) fires once per loop iteration and the operator
    wants the cumulative time spent in that bucket, not the last
    observation.
    """

    __slots__ = ("_data",)

    def __init__(self) -> None:
        self._data: dict[str, float] = {}

    def record(self, name: str, elapsed_ms: float) -> None:
        """Add ``elapsed_ms`` to the bucket for ``name`` (creating it at 0.0)."""
        self._data[name] = self._data.get(name, 0.0) + float(elapsed_ms)

    def record_once(self, name: str, elapsed_ms: float) -> None:
        """Record ``elapsed_ms`` for ``name``, asserting no prior observation.

        PLAN-0102 W4 T-W4-02 (BP-618 — phase double-record).

        Some phases (notably ``llm_synthesis_streaming``) have two recording
        sites in ``chat_orchestrator.py`` that are mutually exclusive only
        by control-flow accident: one in the streaming-success branch
        (~line 1716) and one in the streaming-failure ``except`` clause
        (~line 1707) that returns immediately after recording. If a future
        refactor breaks that mutual exclusion, ``record()`` would silently
        sum the two readings, double-counting the synthesis wall-clock and
        halving ``tps_streaming``. ``record_once()`` makes the invariant
        explicit:

        * **strict mode** (``PHASE_TIMINGS_STRICT=1`` — set in the test
          conftest): raises ``AssertionError`` on the second call. Tests
          must pin the invariant.
        * **prod mode** (env var unset): WARN-logs the double-record (with
          the prior value, the new value, and the phase name) and falls
          back to ``record`` semantics so a metrics-only bug never crashes
          the user-facing chat stream.
        """
        prior = self._data.get(name)
        if prior is None:
            self._data[name] = float(elapsed_ms)
            return
        # Already recorded — diagnose.
        strict = os.environ.get(_STRICT_ENV_VAR, "").lower() in {"1", "true", "yes"}
        if strict:
            raise AssertionError(
                f"phase_timings.record_once: '{name}' already recorded "
                f"(prior={prior:.3f} ms, new={float(elapsed_ms):.3f} ms)"
            )
        log.warning(  # type: ignore[no-any-return]
            "phase_timings_double_record",
            phase=name,
            prior_ms=round(prior, 3),
            new_ms=round(float(elapsed_ms), 3),
            note="record_once invariant violated; summing as fallback",
        )
        # Fall back to ``record`` semantics in prod so we don't crash the
        # stream. The WARN is the alert; the metric is best-effort.
        self._data[name] = prior + float(elapsed_ms)

    def as_dict(self) -> dict[str, float]:
        """Return a shallow copy of the underlying ``{name: ms}`` mapping.

        A copy (not the live dict) is returned so callers that mutate the
        result — e.g. by attaching extra observed totals before emission —
        cannot corrupt the accumulator's internal state.
        """
        return dict(self._data)

    def __len__(self) -> int:  # convenience for tests
        return len(self._data)

    def __contains__(self, name: object) -> bool:  # convenience for tests
        return name in self._data


@contextlib.asynccontextmanager
async def phase(name: str, timings: PhaseTimings) -> AsyncIterator[None]:
    """Async context manager that records wall-clock time of the block.

    Uses ``time.monotonic()`` so an NTP slew or DST jump during the block
    cannot produce a negative or wildly inflated reading.

    The elapsed measurement is taken in a ``finally`` so an exception inside
    the wrapped block still records the time spent before the failure — the
    operator needs to know that the failed phase consumed N ms before the
    exception propagated.  The exception itself is re-raised unchanged.
    """
    t_start = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - t_start) * 1000.0
        timings.record(name, elapsed_ms)
