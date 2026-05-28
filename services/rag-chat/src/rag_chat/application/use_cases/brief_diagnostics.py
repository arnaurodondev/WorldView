"""Diagnostics helpers for morning-brief context gathering (PLAN-0099 Wave A).

Pure-function helpers so that ``briefing_context.py`` (the orchestrator) can
delegate observability concerns without growing further.  Three concerns live
here:

1. ``compute_context_availability_score`` — weighted [0.0, 1.0] score over the
   five context sources (portfolio + news + events + alerts + populated
   sections).  Operators trend this score to decide when context-pipeline
   regressions ship (BP-599 silent partial context loss).

2. ``timed_upstream_call`` — async context manager that wraps an upstream
   coroutine, captures latency, classifies the outcome (ok | timeout | error
   | empty), and emits the matching Prometheus metric + structlog event.

3. ``record_cache_outcome`` — single-call helper so Valkey/in-memory cache
   sites emit a uniform ``brief_cache_outcome`` counter without sprinkling
   metric imports across the codebase.

All weights are intentionally explicit so the audit trail is one grep away
("why did today's score read 0.6?").
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

import structlog

from rag_chat.application.metrics import prometheus as _m

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# ── Score weights ────────────────────────────────────────────────────────────
#
# Portfolio is weighted 2x the other sources because brief quality without
# portfolio context degrades to generic financial-news commentary.  The
# audit (§3 Failure Mode 1) flags portfolio gaps as the primary contributor
# to the user's "feels generic" complaints.
#
# News + events + alerts are equal weight: each can independently rescue a
# brief on a low-portfolio day (e.g. macro events on a cash-heavy account).
#
# ``sections_populated`` is an aggregate quality signal — it captures whether
# the formatter actually produced text for any section (catches the case
# where portfolio is present but yields zero formatted output because every
# holding was filtered out by another guard).

_WEIGHT_PORTFOLIO = 2.0
_WEIGHT_NEWS = 1.0
_WEIGHT_EVENTS = 1.0
_WEIGHT_ALERTS = 1.0
_WEIGHT_SECTIONS = 1.0
_TOTAL_WEIGHT = _WEIGHT_PORTFOLIO + _WEIGHT_NEWS + _WEIGHT_EVENTS + _WEIGHT_ALERTS + _WEIGHT_SECTIONS


def compute_context_availability_score(
    *,
    has_portfolio: bool,
    news_count: int,
    events_count: int,
    alerts_count: int,
    sections_populated: int,
) -> float:
    """Return a weighted [0.0, 1.0] score for brief context completeness.

    Each component contributes its full weight when present (non-zero count
    for the counts; True for portfolio; ≥1 populated section for sections).
    Empty sources contribute 0.  The total is divided by the constant
    ``_TOTAL_WEIGHT`` so the result is always in [0, 1].
    """
    score = 0.0
    if has_portfolio:
        score += _WEIGHT_PORTFOLIO
    if news_count > 0:
        score += _WEIGHT_NEWS
    if events_count > 0:
        score += _WEIGHT_EVENTS
    if alerts_count > 0:
        score += _WEIGHT_ALERTS
    if sections_populated > 0:
        score += _WEIGHT_SECTIONS
    return round(score / _TOTAL_WEIGHT, 4)


def emit_context_availability(
    *,
    score: float,
    has_portfolio: bool,
    news_count: int,
    events_count: int,
    alerts_count: int,
    sections_populated: int,
    user_id: str | None = None,
) -> None:
    """Emit the histogram + structlog event for the computed score.

    Split from ``compute_context_availability_score`` so unit tests can
    assert the maths in isolation without touching the global Prometheus
    registry.
    """
    _m.brief_context_availability_score.observe(score)
    log.info(  # type: ignore[no-any-return]
        "brief_context_availability_score",
        score=score,
        has_portfolio=has_portfolio,
        news_count=news_count,
        events_count=events_count,
        alerts_count=alerts_count,
        sections_populated=sections_populated,
        user_id=user_id,
    )


# ── Upstream-call timing ─────────────────────────────────────────────────────


class _Outcome:
    """Mutable holder so the caller can classify the result post-call.

    The context manager only knows whether an exception was raised; the
    caller often needs to mark a successful-but-empty response as ``empty``
    so SLO dashboards can distinguish a healthy zero-result day from a
    transient outage.
    """

    __slots__ = ("outcome",)

    def __init__(self) -> None:
        # Default to "ok" — caller overrides to "empty" if needed.
        self.outcome: str = "ok"

    def mark_empty(self) -> None:
        self.outcome = "empty"


@asynccontextmanager
async def timed_upstream_call(source: str) -> Any:
    """Async ctx manager that times an upstream call + emits status/latency.

    Usage::

        async with timed_upstream_call("s1_portfolio") as outcome:
            result = await s1.get_portfolio_context(...)
            if not result:
                outcome.mark_empty()

    On exception, the outcome is classified as ``timeout`` for
    ``asyncio.TimeoutError`` / ``TimeoutError`` and ``error`` otherwise; the
    exception is re-raised so the caller's existing try/except logic still
    applies.  Latency is recorded in milliseconds.
    """
    start = time.monotonic()
    outcome = _Outcome()
    try:
        yield outcome
    except TimeoutError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        _m.brief_upstream_latency_ms.labels(source=source).observe(elapsed_ms)
        _m.brief_upstream_status.labels(source=source, outcome="timeout").inc()
        log.warning(  # type: ignore[no-any-return]
            "brief_upstream_latency_ms",
            source=source,
            outcome="timeout",
            elapsed_ms=round(elapsed_ms, 2),
            error=str(exc),
        )
        raise
    except Exception as exc:  # pragma: no cover — re-raised
        elapsed_ms = (time.monotonic() - start) * 1000.0
        _m.brief_upstream_latency_ms.labels(source=source).observe(elapsed_ms)
        _m.brief_upstream_status.labels(source=source, outcome="error").inc()
        log.warning(  # type: ignore[no-any-return]
            "brief_upstream_latency_ms",
            source=source,
            outcome="error",
            elapsed_ms=round(elapsed_ms, 2),
            error=str(exc),
        )
        raise
    else:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        _m.brief_upstream_latency_ms.labels(source=source).observe(elapsed_ms)
        _m.brief_upstream_status.labels(source=source, outcome=outcome.outcome).inc()
        log.info(  # type: ignore[no-any-return]
            "brief_upstream_latency_ms",
            source=source,
            outcome=outcome.outcome,
            elapsed_ms=round(elapsed_ms, 2),
        )


def record_cache_outcome(cache_name: str, outcome: str) -> None:
    """Emit ``brief_cache_outcome{cache_name,outcome}`` and a structlog event.

    ``outcome`` is constrained by convention to ``hit | miss | error`` so the
    label cardinality stays bounded.  Callers in the brief path (Valkey
    fresh/lastgood keys, in-memory completion cache) should call this on
    every cache lookup so operators can compute hit ratios per cache.
    """
    _m.brief_cache_outcome.labels(cache_name=cache_name, outcome=outcome).inc()
    log.info(  # type: ignore[no-any-return]
        "brief_cache_outcome",
        cache_name=cache_name,
        outcome=outcome,
    )
