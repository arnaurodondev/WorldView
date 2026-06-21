"""Standalone intelligence consumer entry point for the Alert service (S10).

Runs as an independent process (R22) with its own session factory, Valkey
dedup client, S1 REST client, and signal handling.

Consumes:
  - ``nlp.signal.detected.v1``
  - ``graph.state.changed.v1``
  - ``intelligence.contradiction.v1``

Run with::

    python -m alert.infrastructure.messaging.consumers.intelligence_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import time

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Fix A, gap A — wall-clock liveness watchdog tuning ────────────────────────
# The audit (2026-06-16) showed the consumer wedged with a ~22k backlog yet kept
# reporting `healthy` for 43h. The connectivity probe in BaseKafkaConsumer could
# not catch it (it only escalates on 3 *consecutive* failures, and the broker
# only flapped) and the lag-stall warning merely LOGGED. This watchdog ACTS: if
# the poll loop stops *cycling* for `_WATCHDOG_STALL_SECONDS` it force-exits the
# process so the orchestrator (Docker `restart: unless-stopped`) restarts a
# fresh, re-joining consumer that drains the backlog.
#
# F-006 (2026-06-21): the watchdog originally gated on time-since-last-MESSAGE
# (`last_progress_monotonic`). That is WRONG for a low-traffic consumer: an idle
# topic processes no messages, so the timer ran out and the container
# crash-looped (RestartCount=10, restarting every ~5 min) even though it was
# connected, assigned, and polling — just IDLE. We now gate on
# `last_poll_monotonic`, which advances on every healthy poll-loop CYCLE (idle
# OR message; the base class's BP-700 progress tick). This distinguishes:
#   • IDLE  → poll keeps returning empty → marker stays fresh → NO restart.
#   • WEDGED → poll stops returning / loop dies → marker goes stale → restart.
# Why poll-cycle (not lag-gated): reading lag requires the broker, which is
# exactly what flaps during the failure mode; gating on it would re-introduce
# the blind spot. The threshold is set well above the slowest realistic poll
# interval so a normal poll timeout never trips it.
# Overridable via env for ops tuning / tests.
_WATCHDOG_STALL_SECONDS: float = float(os.environ.get("ALERT_CONSUMER_WATCHDOG_STALL_SECONDS", "300"))
# How often the watchdog samples the progress timestamp.
_WATCHDOG_POLL_SECONDS: float = float(os.environ.get("ALERT_CONSUMER_WATCHDOG_POLL_SECONDS", "30"))


async def _liveness_watchdog(
    consumer: object,
    stop_event: asyncio.Event,
    log: object,
    *,
    stall_seconds: float = _WATCHDOG_STALL_SECONDS,
    poll_seconds: float = _WATCHDOG_POLL_SECONDS,
) -> None:
    """Force a process restart if the consumer's poll loop stops cycling.

    Polls ``consumer.last_poll_monotonic`` (advanced on every healthy poll-loop
    cycle — idle OR message) every ``poll_seconds``. If it has not advanced for
    ``stall_seconds`` while we are NOT shutting down, the poll loop is presumed
    wedged (the 43h failure mode) and we exit hard so the orchestrator restarts
    a clean consumer.

    F-006: gating on poll-cycle liveness (not last-message) means an IDLE topic
    — where the loop keeps returning empty polls — does NOT trip the watchdog,
    while a genuinely wedged loop (poll stops returning / loop dies) still does.
    Falls back to ``last_progress_monotonic`` for consumers that don't expose
    the poll marker, so the watchdog is safe to reuse on other consumers.

    ``time.monotonic()`` is used throughout so the wall-clock skew the audit saw
    on this host cannot mask a real stall.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            return  # graceful shutdown requested during the wait
        except TimeoutError:
            pass  # interval elapsed — run a check

        # Prefer the poll-cycle marker (alive even when idle); fall back to the
        # message marker, then to "now" so a missing attribute never false-trips.
        last_alive = getattr(
            consumer,
            "last_poll_monotonic",
            getattr(consumer, "last_progress_monotonic", time.monotonic()),
        )
        age = time.monotonic() - last_alive
        if age >= stall_seconds:
            log.critical(  # type: ignore[attr-defined]
                "intelligence_consumer_watchdog_stall",
                stall_seconds=stall_seconds,
                seconds_since_progress=round(age, 1),
                action="exiting_for_restart_poll_loop_presumed_wedged",
            )
            # os._exit bypasses the asyncio Task that would otherwise swallow a
            # SystemExit (the exact gap-B bug). It is the only reliable way to
            # take the whole process down from inside a coroutine.
            os._exit(3)


async def main() -> None:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase
    from alert.config import Settings
    from alert.domain.entities import SeverityThresholds
    from alert.infrastructure.cache.watchlist_cache import WatchlistCache
    from alert.infrastructure.clients.s1_client import S1Client
    from alert.infrastructure.clients.s7_entity_resolver import S7EntityResolver
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.dedup import DedupRepository
    from alert.infrastructure.db.repositories.outbox import OutboxRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
    from alert.infrastructure.db.session import _build_factories
    from alert.infrastructure.messaging.consumers.intelligence_consumer import IntelligenceConsumer
    from alert.infrastructure.metrics.prometheus_metrics_impl import PrometheusAlertMetrics
    from alert.infrastructure.notification.valkey_publisher import ValkeyNotificationPublisher
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="alert-intelligence-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("alert.intelligence_consumer_main")  # type: ignore[no-any-return]
    log.info("intelligence_consumer_starting", service="alert")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a dedicated
    # port so non-HTTP worker processes are scrape-able alongside the FastAPI
    # services.  Defaults to 9100; container compose entry exposes the same port.
    metrics_handle = start_metrics_server(
        service_name="alert-intelligence-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Database — write factory for fan-out (creates alerts, outbox events)
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Valkey — dedup + watchlist cache
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # S1 client — resolve watchers
    s1_client = S1Client(settings)

    # Watchlist cache
    watchlist_cache = WatchlistCache(valkey, s1_client, ttl=settings.watchlist_cache_ttl_seconds)  # type: ignore[arg-type]

    # S7 entity resolver — looks up (canonical_name, ticker) for payload
    # enrichment so the frontend can render readable rows. Cached in Valkey
    # for 15 min by default (BP-263 follow-up; PLAN-0048 Wave B-1).
    entity_resolver = S7EntityResolver(settings, valkey)  # type: ignore[arg-type]

    # Notification publisher — sends to Valkey pub/sub channel per user
    notification_publisher = ValkeyNotificationPublisher(valkey)

    # Build fan-out use case
    def _repo_factory(session):  # type: ignore[no-untyped-def]
        return (
            AlertRepository(session),
            PendingAlertRepository(session),
            DedupRepository(session),
            OutboxRepository(session),
        )

    fanout = AlertFanoutUseCase(
        session_factory=write_factory,
        watchlist_cache=watchlist_cache,
        notification_publisher=notification_publisher,
        repo_factory=_repo_factory,  # type: ignore[arg-type]
        dedup_window_seconds=settings.alert_dedup_window_seconds,
        alert_delivered_topic=settings.kafka_topic_alert_delivered,
        severity_thresholds=SeverityThresholds(
            critical=settings.alert_severity_critical_threshold,
            high=settings.alert_severity_high_threshold,
            medium=settings.alert_severity_medium_threshold,
        ),
        metrics=PrometheusAlertMetrics(),
        entity_resolver=entity_resolver,
    )

    # Consumer config
    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topics=[
            settings.kafka_topic_signal,
            settings.kafka_topic_graph_state,
            settings.kafka_topic_contradiction,
        ],
    )
    consumer = IntelligenceConsumer(
        config=config,
        fanout_use_case=fanout,
        dedup_client=valkey,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "alert-intelligence-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [
                settings.kafka_topic_signal,
                settings.kafka_topic_graph_state,
                settings.kafka_topic_contradiction,
            ],
        },
    )

    try:
        # Fix A, gaps B+C: supervise the consume task instead of blindly
        # blocking on stop_event. Previously `main()` did
        # `create_task(consumer.run()); await stop_event.wait()` with no
        # done-callback — so if `consumer.run()` returned or crashed (e.g. the
        # connectivity probe's swallowed SystemExit, or any loop death) nothing
        # awaited the task and `main()` blocked on stop_event forever. The
        # process stayed up and `healthy` with a dead poll loop (the 43h wedge).
        #
        # We now RACE the consume task against the stop signal, and also run a
        # wall-clock watchdog (gap A) concurrently. Whichever finishes first
        # wins; we then decide between graceful shutdown and fatal restart.
        consumer_task = asyncio.create_task(consumer.run(), name="intelligence_consume")
        stop_task = asyncio.create_task(stop_event.wait(), name="intelligence_stop")
        watchdog_task = asyncio.create_task(
            _liveness_watchdog(consumer, stop_event, log),
            name="intelligence_watchdog",
        )

        done, _pending = await asyncio.wait(
            {consumer_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Always stop the watchdog from here on — we are now in a controlled
        # teardown and do not want it racing a force-exit during cleanup.
        watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task

        if consumer_task in done and not stop_event.is_set():
            # The consume loop ended on its own WITHOUT a shutdown signal — it
            # either returned early or crashed. Either way the process must die
            # so the orchestrator restarts a healthy consumer. Surface the
            # exception (if any) before exiting.
            exc = consumer_task.exception()
            log.critical(
                "intelligence_consumer_run_exited_unexpectedly",
                error=str(exc) if exc is not None else None,
                action="exiting_for_restart",
            )
            # Best-effort resource cleanup before the hard exit.
            with contextlib.suppress(Exception):
                await s1_client.close()
            with contextlib.suppress(Exception):
                await entity_resolver.close()
            with contextlib.suppress(Exception):
                await valkey.close()
            with contextlib.suppress(Exception):
                await _engine.dispose()
            os._exit(1)

        # Graceful path: stop signal won (or both completed with stop set).
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        consumer.stop()
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
    except Exception as exc:
        log.error("intelligence_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("intelligence_consumer_stopped")
    finally:
        await s1_client.close()
        # Close the resolver's httpx client to release sockets.
        await entity_resolver.close()
        await valkey.close()
        await _engine.dispose()
        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
