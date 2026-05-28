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
import time
from collections.abc import AsyncIterator


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
