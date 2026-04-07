"""Email scheduler process entrypoint for the Alert service (S10).

Runs a standalone async process that schedules :class:`EmailScheduler.run`
at the top of every UTC hour via APScheduler.  The scheduler queries
``email_preferences`` for users whose ``send_day_of_week`` and
``send_hour_utc`` match the current day/hour.

Usage::

    python -m alert.infrastructure.email.scheduler_main
"""

from __future__ import annotations

import asyncio

from alert.config import Settings
from alert.infrastructure.clients.s1_client import S1Client
from alert.infrastructure.clients.s3_client import S3MarketDataClient
from alert.infrastructure.clients.s8_client import S8BriefingClient
from alert.infrastructure.db.session import create_session_factory
from alert.infrastructure.email import build_email_provider
from alert.infrastructure.email.scheduler import EmailScheduler
from observability import configure_logging, get_logger  # type: ignore[import-untyped]


async def _run_loop(settings: Settings) -> None:
    """Bootstrap resources and schedule hourly digest runs."""
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("alert.scheduler_main")  # type: ignore[no-any-return]

    engine, session_factory = create_session_factory(settings)
    email_provider = build_email_provider(settings)
    s1_client = S1Client(settings)
    s3_client = S3MarketDataClient(settings)
    s8_client = S8BriefingClient(settings)

    scheduler = EmailScheduler(
        session_factory=session_factory,
        email_provider=email_provider,
        settings=settings,
        s1_client=s1_client,
        s3_client=s3_client,
        s8_client=s8_client,
    )

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
    from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

    ap_scheduler = AsyncIOScheduler()
    # Fire at the top of every hour (minute=0) to check who needs a digest
    ap_scheduler.add_job(scheduler.run, CronTrigger(minute=0), id="email_digest_hourly")
    ap_scheduler.start()
    log.info("email_scheduler_started")  # type: ignore[no-any-return]

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        ap_scheduler.shutdown(wait=False)
        await s1_client.close()
        await s3_client.close()
        await s8_client.close()
        await engine.dispose()
        log.info("email_scheduler_stopped")  # type: ignore[no-any-return]


def main() -> None:
    settings = Settings()
    asyncio.run(_run_loop(settings))


if __name__ == "__main__":
    main()
