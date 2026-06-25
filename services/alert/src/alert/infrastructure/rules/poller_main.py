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

from alert.application.rules.registry import EvalContext, get_evaluator, register_default_evaluators
from alert.application.use_cases.fire_rule_alert import FireRuleAlertUseCase
from alert.config import Settings
from alert.domain.enums import RuleType
from alert.infrastructure.clients.s3_client import S3MarketDataClient
from alert.infrastructure.clients.s6_client import S6NewsClient
from alert.infrastructure.db.repositories.alert import AlertRepository
from alert.infrastructure.db.repositories.alert_rule import AlertRuleRepository
from alert.infrastructure.db.repositories.outbox import OutboxRepository
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from alert.infrastructure.db.session import create_session_factory
from alert.infrastructure.metrics.prometheus import (
    s10_rule_evaluations_total,
    s10_rule_fired_total,
    s10_rule_poller_due_rules,
    s10_rule_poller_last_success_timestamp,
    s10_rule_poller_runs_total,
)
from alert.infrastructure.notification.valkey_publisher import ValkeyNotificationPublisher
from common.time import utc_now  # type: ignore[import-untyped]
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.domain.entities import AlertRule, EvalResult

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


async def _persist_no_fire_state(
    session_factory: async_sessionmaker[AsyncSession],
    rule: AlertRule,
    result: EvalResult,
    now: datetime,
) -> None:
    """Advance ``last_state`` (last_checked_at + edge memory) without firing.

    Runs in its own short transaction so a no-fire evaluation still records that
    we observed the world this cycle (so ``is_due`` throttles correctly) and
    updates the edge memory (``was_above`` / ``last_count``) that the NEXT
    evaluation diffs against. ``fired=False`` → ``last_fired_at`` is untouched.
    """
    rule.last_state = rule.next_state(result, now, fired=False)
    async with session_factory() as session:
        repo = AlertRuleRepository(session)
        await repo.update(rule)
        await session.commit()


async def run_poll_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    ctx: EvalContext,
    fire_use_case: FireRuleAlertUseCase,
) -> int:
    """Execute one poller cycle. Returns the number of due rules processed.

    For each enabled poll rule whose per-type cadence makes it due:
      1. resolve its evaluator from the registry,
      2. ``evaluate`` it (skip on None — no state change),
      3. ``should_fire`` → either fire (FireRuleAlertUseCase advances last_state
         + last_fired_at on commit) or persist the no-fire next_state.

    Fail-soft per rule (BP-705): an evaluator/firing exception increments the
    error counter and skips that rule, never aborting the cycle or other rules.
    """
    log = get_logger("alert.rule_poller")  # type: ignore[no-any-return]
    now = utc_now()
    due_count = 0

    # Reads of the enabled-rule sets happen on a short-lived session; firing +
    # state writes each open their own transaction (the fire use case via its
    # own session_factory, no-fire via _persist_no_fire_state).
    async with session_factory() as session:
        repo = AlertRuleRepository(session)
        rules_by_type = {rt: await repo.list_enabled_by_type(rt) for rt in _POLL_RULE_TYPES}

    for rule_type in _POLL_RULE_TYPES:
        cadence = _cadence_for(settings, rule_type)
        evaluator = get_evaluator(rule_type)
        rt_label = rule_type.value
        for rule in rules_by_type[rule_type]:
            if not rule.is_due(now, cadence):
                continue
            due_count += 1
            if evaluator is None:
                # No evaluator registered for this type (e.g. registry not wired).
                s10_rule_evaluations_total.labels(rule_type=rt_label, outcome="skipped").inc()
                continue
            try:
                result = await evaluator.evaluate(rule, ctx)
                if result is None:
                    # No observation (missing price / flaky upstream) — leave state.
                    s10_rule_evaluations_total.labels(rule_type=rt_label, outcome="skipped").inc()
                    continue
                if rule.should_fire(result, now):
                    await fire_use_case.execute(rule, result)
                    s10_rule_evaluations_total.labels(rule_type=rt_label, outcome="fired").inc()
                    s10_rule_fired_total.labels(rule_type=rt_label).inc()
                else:
                    await _persist_no_fire_state(session_factory, rule, result, now)
                    s10_rule_evaluations_total.labels(rule_type=rt_label, outcome="no_fire").inc()
            except Exception:
                # Fail-soft: one bad rule never sinks the cycle (BP-705).
                s10_rule_evaluations_total.labels(rule_type=rt_label, outcome="error").inc()
                log.error("rule_eval_failed", rule_id=str(rule.rule_id), rule_type=rt_label, exc_info=True)  # type: ignore[no-any-return]

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

    # ── Wire the evaluators + their read-only clients (Wave 2) ────────────────
    register_default_evaluators()
    s3_client = S3MarketDataClient(settings)
    s6_client = S6NewsClient(settings)
    eval_ctx = EvalContext(clients={"s3": s3_client, "s6": s6_client})

    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey = create_valkey_client_from_url(settings.valkey_url)
    notification_publisher = ValkeyNotificationPublisher(valkey)

    def _fire_repo_factory(session: AsyncSession) -> tuple[object, object, object, object]:
        return (
            AlertRepository(session),
            PendingAlertRepository(session),
            OutboxRepository(session),
            AlertRuleRepository(session),
        )

    fire_use_case = FireRuleAlertUseCase(
        session_factory=session_factory,
        notification_publisher=notification_publisher,
        repo_factory=_fire_repo_factory,  # type: ignore[arg-type]
        alert_delivered_topic=settings.kafka_topic_alert_delivered,
    )

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
                run_poll_cycle(session_factory, settings, ctx=eval_ctx, fire_use_case=fire_use_case),
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
        await s6_client.close()
        with contextlib.suppress(Exception):
            await valkey.close()
        await engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("rule_poller_stopped")  # type: ignore[no-any-return]


def main() -> None:
    settings = Settings()
    asyncio.run(_run_loop(settings))


if __name__ == "__main__":
    main()
