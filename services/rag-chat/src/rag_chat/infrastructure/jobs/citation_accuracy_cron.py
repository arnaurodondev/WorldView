"""Citation-accuracy cron job — PLAN-0063 W5-5 T-W5-5-02, PLAN-0099 W4 daily.

Runs DAILY at 03:00 UTC (was weekly Sunday 03:00 UTC before PLAN-0099 W4)
plus an immediate first run on process start so the gauge has a value within
minutes of the first deployment. The use case enforces a last-24h window on
the sampling query so the gauge tracks recent quality drift rather than a
multi-day rolling average.

PLAN-0099 W4 MN-1 (crashloop guard): the immediate first run is gated behind
a Valkey-backed ``last_run_at`` key. If the previous successful run was less
than 1 hour ago, the first run is skipped — this prevents a crashlooping pod
from re-running an expensive LLM cron on every restart. If Valkey is not
available (e.g. cron task started before lifespan finished wiring it), the
guard degrades open: we log a one-liner and proceed with the first run.

Usage (inside lifespan startup):
    from rag_chat.infrastructure.jobs.citation_accuracy_cron import start_citation_accuracy_cron
    app.state.citation_cron_task = start_citation_accuracy_cron(use_case, valkey=valkey_client)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter

from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

_CITATION_CRON_FAIL_COUNTER: Counter = Counter(
    "rag_citation_cron_first_run_failures_total",
    "Total number of citation accuracy cron first-run failures",
)

# MN-1: counter for the crashloop-guard skip path. Operators alert when this
# is > a small constant per hour — a healthy pod increments this at most once
# per cold start within the 1h window, sustained increments indicate a
# CrashLoopBackOff.
_CITATION_CRON_FIRST_RUN_SKIPPED: Counter = Counter(
    "rag_citation_cron_first_run_skipped_total",
    "First-run skips because last successful run was < 1h ago (crashloop guard)",
)

# Valkey key + TTL for the last-run timestamp. TTL=25h so the key always
# outlives one cron tick (24h) but not two — prevents stale-key pollution if
# the cron is removed.
_LAST_RUN_KEY = "rag_chat:citation_accuracy:last_run_at"
_LAST_RUN_TTL_SECONDS = 25 * 3600
# Skip the first run if the previous run completed within this window.
_FIRST_RUN_SKIP_WINDOW = timedelta(hours=1)

if TYPE_CHECKING:
    from rag_chat.application.use_cases.score_citation_accuracy import ScoreCitationAccuracyUseCase

log = get_logger("rag_chat.citation_cron")  # type: ignore[no-any-return]


def _next_daily_03_utc(now: datetime | None = None) -> datetime:
    """Return the next 03:00 UTC after *now* (defaults to current time).

    If the current time is strictly before 03:00 UTC today, the next run is
    today at 03:00. Otherwise the next run is tomorrow at 03:00. PLAN-0099 W4
    replaces the prior weekly-Sunday cadence with a 24h cadence so the
    citation-accuracy gauge refreshes every day.
    """
    ref = now or datetime.now(tz=UTC)
    target = ref.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= ref:
        # We're past today's 03:00 — push to tomorrow.
        target += timedelta(days=1)
    return target


async def _should_skip_first_run(valkey: Any | None) -> bool:
    """Return True iff the previous successful run was < 1h ago.

    Graceful degradation: if ``valkey`` is None OR the Valkey call raises,
    we return False (do NOT skip) and log a single line. This keeps the cron
    forward-progressing in environments where Valkey isn't wired (tests,
    early-startup paths).
    """
    if valkey is None:
        log.info("citation_cron_first_run_guard_unavailable", reason="no_valkey_client")  # type: ignore[no-any-return]
        return False
    try:
        raw = await valkey.get(_LAST_RUN_KEY)
    except Exception as exc:  # — defensive, must not break cron
        log.info(  # type: ignore[no-any-return]
            "citation_cron_first_run_guard_unavailable",
            reason="valkey_error",
            error=str(exc),
        )
        return False
    if not raw:
        return False
    try:
        last_run = datetime.fromisoformat(raw)
    except ValueError:
        # Corrupt value — ignore and proceed.
        return False
    age = utc_now() - last_run
    return age < _FIRST_RUN_SKIP_WINDOW


async def _record_last_run(valkey: Any | None) -> None:
    """Persist ``last_run_at = utc_now()`` to Valkey with a 25h TTL."""
    if valkey is None:
        return
    try:
        await valkey.set(_LAST_RUN_KEY, utc_now().isoformat(), ex=_LAST_RUN_TTL_SECONDS)
    except Exception as exc:  # — defensive, must not break cron
        log.warning(  # type: ignore[no-any-return]
            "citation_cron_last_run_persist_failed",
            error=str(exc),
        )


async def _run_citation_accuracy_cron(
    use_case: ScoreCitationAccuracyUseCase,
    valkey: Any | None = None,
) -> None:
    """Background task: first run immediately (unless guard skips), then DAILY at 03:00 UTC."""
    # MN-1 crashloop guard: skip first run if previous successful run < 1h ago.
    if await _should_skip_first_run(valkey):
        _CITATION_CRON_FIRST_RUN_SKIPPED.inc()
        log.info("citation_cron_first_run_skipped", reason="recent_run_within_1h")  # type: ignore[no-any-return]
    else:
        # Immediate first run so the gauge is populated from the first deployment.
        try:
            mean = await use_case.execute()
            log.info("citation_accuracy_cron_first_run", mean=round(mean, 4))  # type: ignore[no-any-return]
            await _record_last_run(valkey)
        except asyncio.CancelledError:
            log.info("citation_accuracy_cron_shutdown_gracefully")  # type: ignore[no-any-return]
            raise
        except Exception as exc:
            _CITATION_CRON_FAIL_COUNTER.inc()
            log.error("citation_accuracy_cron_first_run_failed", error=str(exc))  # type: ignore[no-any-return]

    while True:
        next_run = _next_daily_03_utc()
        wait_seconds = max(0.0, (next_run - datetime.now(tz=UTC)).total_seconds())
        log.info(  # type: ignore[no-any-return]
            "citation_accuracy_cron_scheduled",
            next_run_utc=next_run.isoformat(),
            wait_seconds=int(wait_seconds),
            cadence="daily",
        )
        await asyncio.sleep(wait_seconds)
        try:
            mean = await use_case.execute()
            log.info("citation_accuracy_cron_run", mean=round(mean, 4), cadence="daily")  # type: ignore[no-any-return]
            await _record_last_run(valkey)
        except asyncio.CancelledError:
            log.info("citation_accuracy_cron_shutdown_gracefully")  # type: ignore[no-any-return]
            raise
        except Exception as exc:
            log.warning("citation_accuracy_cron_run_failed", error=str(exc))  # type: ignore[no-any-return]


def start_citation_accuracy_cron(
    use_case: ScoreCitationAccuracyUseCase,
    valkey: Any | None = None,
) -> asyncio.Task:  # type: ignore[type-arg]
    """Schedule the citation-accuracy cron as a background asyncio task.

    Returns the task so the caller can cancel it on shutdown. ``valkey`` is
    optional — when omitted the MN-1 crashloop guard degrades open (logs a
    warning, proceeds with the first run).
    """
    return asyncio.create_task(_run_citation_accuracy_cron(use_case, valkey=valkey))
