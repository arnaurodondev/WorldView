"""Observability helpers (phase timings, structured-log shapes).

Currently exposes ``PhaseTimings`` + ``phase`` (PLAN-0099 W1-T03) so the
chat orchestrator can decompose end-to-end latency into per-phase buckets.
"""

from rag_chat.application.observability.phase_timings import PhaseTimings, phase

__all__ = ["PhaseTimings", "phase"]
