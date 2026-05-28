"""Unit tests for PLAN-0099 W1-T03 — per-phase wall-clock instrumentation.

Covers the small ``PhaseTimings`` + ``phase`` helpers in
``rag_chat.application.observability.phase_timings``:

  * ``test_record_accumulates`` — multiple writes under the same key sum.
  * ``test_phase_records_elapsed_ms`` — the async context manager records
    a positive ms reading proportional to ``asyncio.sleep``.
  * ``test_phase_records_on_exception`` — exception inside the block is
    re-raised but the elapsed time IS still recorded (no swallowed bug
    where a failed LLM call silently drops out of the breakdown).
  * ``test_as_dict_returns_copy`` — mutating the returned dict cannot
    corrupt the accumulator.
"""

from __future__ import annotations

import asyncio

import pytest
from rag_chat.application.observability.phase_timings import PhaseTimings, phase

pytestmark = pytest.mark.unit


def test_record_accumulates() -> None:
    """Two record() calls under the same name produce the sum."""
    t = PhaseTimings()
    t.record("alpha", 12.0)
    t.record("alpha", 4.5)
    t.record("beta", 1.0)
    snap = t.as_dict()
    assert snap["alpha"] == pytest.approx(16.5)
    assert snap["beta"] == pytest.approx(1.0)


def test_as_dict_returns_copy() -> None:
    """Mutating the snapshot must not corrupt the accumulator."""
    t = PhaseTimings()
    t.record("x", 1.0)
    snap = t.as_dict()
    snap["x"] = 999.0
    snap["y"] = 100.0
    # Underlying state untouched.
    assert t.as_dict() == {"x": 1.0}


def test_phase_records_elapsed_ms() -> None:
    """The async context manager records a positive ms reading."""

    async def _run() -> PhaseTimings:
        t = PhaseTimings()
        async with phase("sleep_phase", t):
            # 10ms sleep — generous lower bound for CI noise.
            await asyncio.sleep(0.01)
        return t

    t = asyncio.run(_run())
    snap = t.as_dict()
    assert "sleep_phase" in snap
    # 10ms target; allow at least 5ms (loose) and < 5000ms (sanity).
    assert 5.0 < snap["sleep_phase"] < 5000.0


def test_phase_records_on_exception() -> None:
    """Exception inside the block re-raises but the elapsed time is still recorded.

    Regression guard for the silent-drop pattern where a failed LLM call
    consumed N ms but never showed up in the latency breakdown.
    """

    class _Boom(Exception):  # noqa: N818  # local test exception, no Error suffix needed
        pass

    async def _run() -> PhaseTimings:
        t = PhaseTimings()
        with pytest.raises(_Boom):
            async with phase("failing_phase", t):
                await asyncio.sleep(0.005)
                raise _Boom("simulated tool timeout")
        return t

    t = asyncio.run(_run())
    snap = t.as_dict()
    assert "failing_phase" in snap
    # At least the sleep duration was recorded.
    assert snap["failing_phase"] > 2.0
