"""Alert-rule poller process entrypoint (PLAN-0113 — 5th S10 process, R22).

Runs a standalone APScheduler loop (base tick = ``ALERT_RULE_POLL_TICK_SECONDS``)
that, each cycle:
  1. Loads every *enabled poll-type* rule (price / fundamental / news-count /
     news-momentum) from ``alert_rules``.
  2. Filters to the rules whose per-type cadence makes them due now
     (``AlertRule.is_due``).
  3. Resolves each due rule's evaluator from ``EVALUATOR_REGISTRY`` and runs it.

Wave 1 ships the loop + observability seam with the registry EMPTY — so the
cycle finds due rules but every evaluator lookup is a no-op (no evaluation,
no firing). Wave 2/3 register the evaluators; this loop then drives them.

Observability (BP-705): every cycle is wrapped in ``asyncio.wait_for`` (no
silent stall), increments ``s10_rule_poller_runs_total{outcome}``, and on
success sets the ``s10_rule_poller_last_success_timestamp_seconds`` liveness
gauge. A staleness alert (now - gauge > 2x tick) detects a wedged loop.

Usage::

    python -m alert.infrastructure.rules.poller_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import TYPE_CHECKING

from alert.application.rules.registry import get_evaluator
from alert.config import Settings
from alert.domain.enums import RuleType
from alert.infrastructure.clients.s3_client import S3MarketDataClient
from alert.infrastructure.db.repositories.alert_rule import AlertRuleRepository
from alert.infrastructure.db.session import create_session_factory
from alert.infrastructure.metrics.prometheus import (
    s10_rule_poller_due_rules,
    s10_rule_poller_last_success_timestamp,
    s10_rule_poller_runs_total,
)
from common.time import utc_now  # type: ignore[import-untyped]
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Poll-type rule types (KG_CONNECTION is event-driven — handled by the consumer).
_POLL_RULE_TYPES: tuple[RuleType, ...] = (
    RuleType.PRICE_CROSS,
    RuleType.FUNDAMENTAL_CROSS,
    RuleType.NEWS_COUNT,
    RuleType.NEWS_MOMENTUM,
)


def _cadence_for(settings: Settings, rule_type: RuleType) -> int:
    """Resolve the per-type poll cadence (seconds) from settings."""
    return {
        RuleType.PRICE_CROSS: settings.alert_rule_cadence_price_seconds,
        RuleType.FUNDAMENTAL_CROSS: settings.alert_rule_cadence_fundamental_seconds,
        RuleType.NEWS_COUNT: settings.alert_rule_cadence_news_count_seconds,
        RuleType.NEWS_MOMENTUM: settings.alert_rule_cadence_news_momentum_seconds,
    }[rule_type]


async def run_poll_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> int:
    """Execute one poller cycle. Returns the number of due rules processed.

    Wave 1: with no evaluators registered, this loads + counts due rules and
    no-ops (the evaluator lookup returns None). Wave 2 fills in evaluation.
    """
    log = get_logger("alert.rule_poller")  # type: ignore[no-any-return]
    now = utc_now()
    due_count = 0

    async with session_factory() as session:
        repo = AlertRuleRepository(session)
        for rule_type in _POLL_RULE_TYPES:
            cadence = _cadence_for(settings, rule_type)
            rules = await repo.list_enabled_by_type(rule_type)
            evaluator = get_evaluator(rule_type)
            for rule in rules:
                if not rule.is_due(now, cadence):
                    continue
                due_count += 1
                if evaluator is None:
                    # Wave 1 seam — no evaluator wired yet for this type.
                    continue
                # Wave 2/3 wire evaluation + firing here.

    s10_rule_poller_due_rules.set(due_count)
    log.debug("rule_poll_cycle_complete", due_rules=due_count)  # type: ignore[no-any-return]
    return due_count


async def _run_loop(settings: Settings) -> None:
    """Bootstrap resources and schedule the poller cycle on the base tick."""
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("alert.rule_poller_main")  # type: ignore[no-any-return]

    metrics_handle = start_metrics_server(
        service_name="alert-rule-poller",
        port=int(os.environ.get("METRICS_PORT", "9101")),
    )

    engine, session_factory = create_session_factory(settings)
    # Constructed for Wave 2 evaluator wiring; unused in Wave 1 but proves the
    # client + config plumbing boots healthy.
    s3_client = S3MarketDataClient(settings)

    if not settings.alert_rule_poller_enabled:
        log.warning("rule_poller_disabled")  # type: ignore[no-any-return]

    async def _tick() -> None:
        """One scheduled tick — wrapped per BP-705 (timeout + outcome counter)."""
        if not settings.alert_rule_poller_enabled:
            return
        try:
            # Watchdog: a cycle that overruns the watchdog window is killed so a
            # wedged DB/HTTP call cannot hang the loop forever (BP-705).
            await asyncio.wait_for(
                run_poll_cycle(session_factory, settings),
                timeout=settings.alert_rule_poller_watchdog_seconds,
            )
            s10_rule_poller_runs_total.labels(outcome="success").inc()
            s10_rule_poller_last_success_timestamp.set(time.time())
        except TimeoutError:
            s10_rule_poller_runs_total.labels(outcome="timeout").inc()
            log.error("rule_poll_cycle_timeout")  # type: ignore[no-any-return]
        except Exception:
            s10_rule_poller_runs_total.labels(outcome="error").inc()
            log.error("rule_poll_cycle_failed", exc_info=True)  # type: ignore[no-any-return]

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
    from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

    ap_scheduler = AsyncIOScheduler()
    ap_scheduler.add_job(
        _tick,
        IntervalTrigger(seconds=settings.alert_rule_poll_tick_seconds),
        id="alert_rule_poll",
        max_instances=1,  # never overlap cycles
        coalesce=True,  # collapse missed ticks after a pause
    )
    ap_scheduler.start()
    log.info("rule_poller_started", tick_seconds=settings.alert_rule_poll_tick_seconds)  # type: ignore[no-any-return]

    log_runtime_banner(
        "alert-rule-poller",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "s3_market_data_base_url": settings.s3_market_data_base_url,
        },
    )

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        ap_scheduler.shutdown(wait=False)
        await s3_client.close()
        await engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("rule_poller_stopped")  # type: ignore[no-any-return]


def main() -> None:
    settings = Settings()
    asyncio.run(_run_loop(settings))


if __name__ == "__main__":
    main()
