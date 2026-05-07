"""Citation-accuracy cron job — PLAN-0063 W5-5 T-W5-5-02.

Runs weekly (Sunday 03:00 UTC) plus an immediate first run on process start
so the gauge has a value within minutes of the first deployment.

Usage (inside lifespan startup):
    from rag_chat.infrastructure.jobs.citation_accuracy_cron import start_citation_accuracy_cron
    app.state.citation_cron_task = start_citation_accuracy_cron(use_case)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from rag_chat.application.use_cases.score_citation_accuracy import ScoreCitationAccuracyUseCase

log = get_logger("rag_chat.citation_cron")  # type: ignore[no-any-return]


def _next_sunday_03_utc(now: datetime | None = None) -> datetime:
    """Return the next Sunday 03:00 UTC after *now* (defaults to current time).

    If today is Sunday but it's before 03:00 UTC, the next run is today at 03:00.
    Otherwise the next run is the coming Sunday.
    """
    ref = now or datetime.now(tz=UTC)
    days_until_sunday = (6 - ref.weekday()) % 7  # 0 if already Sunday
    target = ref + timedelta(days=days_until_sunday)
    target = target.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= ref:
        # We're past this week's Sunday 03:00 — push to next week.
        target += timedelta(days=7)
    return target


async def _run_citation_accuracy_cron(use_case: ScoreCitationAccuracyUseCase) -> None:
    """Background task: first run immediately, then weekly on Sunday 03:00 UTC."""
    # Immediate first run so the gauge is populated from the first deployment.
    try:
        mean = await use_case.execute()
        log.info("citation_accuracy_cron_first_run", mean=round(mean, 4))  # type: ignore[no-any-return]
    except Exception as exc:
        log.warning("citation_accuracy_cron_first_run_failed", error=str(exc))  # type: ignore[no-any-return]

    while True:
        next_run = _next_sunday_03_utc()
        wait_seconds = max(0.0, (next_run - datetime.now(tz=UTC)).total_seconds())
        log.info(  # type: ignore[no-any-return]
            "citation_accuracy_cron_scheduled",
            next_run_utc=next_run.isoformat(),
            wait_seconds=int(wait_seconds),
        )
        await asyncio.sleep(wait_seconds)
        try:
            mean = await use_case.execute()
            log.info("citation_accuracy_cron_run", mean=round(mean, 4))  # type: ignore[no-any-return]
        except Exception as exc:
            log.warning("citation_accuracy_cron_run_failed", error=str(exc))  # type: ignore[no-any-return]


def start_citation_accuracy_cron(use_case: ScoreCitationAccuracyUseCase) -> asyncio.Task:  # type: ignore[type-arg]
    """Schedule the citation-accuracy cron as a background asyncio task.

    Returns the task so the caller can cancel it on shutdown.
    """
    return asyncio.create_task(_run_citation_accuracy_cron(use_case))
