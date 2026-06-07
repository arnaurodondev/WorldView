"""Standalone entry point for PathInsightWorker (PLAN-0074 Wave E1).

Runs as an independent process (R22).  Starts the claim-and-process loop
that picks jobs from ``path_insight_jobs``, discovers multi-hop paths via
AGE, scores them, and writes results to ``path_insights``.

One instance per container.  To scale horizontally, deploy multiple replicas
— each uses a unique ``KNOWLEDGE_GRAPH_PATH_INSIGHT_WORKER_INSTANCE_ID`` so
SKIP LOCKED ensures disjoint claim sets.  When the env var is empty the
process generates a random UUID at startup.

Run with::

    python -m knowledge_graph.infrastructure.workers.path_insight_worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-path-insight-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.path_insight_worker_main")  # type: ignore[no-any-return]
    log.info("path_insight_worker_starting")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics so the
    # path_insight_* and summary_worker_stuck gauges are scrape-able.
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-path-insight-worker",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    # Determine stable instance UUID (env-overridable for testing).
    raw_instance_id = settings.path_insight_worker_instance_id  # type: ignore[attr-defined]
    instance_uuid: UUID = UUID(raw_instance_id) if raw_instance_id else new_uuid7()
    log.info("path_insight_worker_instance", instance_uuid=str(instance_uuid))

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, read_engine, write_factory, _read_factory = _build_factories(settings)

    # Build PathDiscovery, PathScorer, PathTemplateMatcher.
    from knowledge_graph.application.services.path_scorer import PathScorer
    from knowledge_graph.application.services.path_template_matcher import PathTemplateMatcher
    from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery
    from knowledge_graph.infrastructure.workers.path_insight_worker import PathInsightWorker

    path_discovery = PathDiscovery(write_factory)
    scorer = PathScorer()
    template_matcher = PathTemplateMatcher(write_factory)

    worker = PathInsightWorker(
        session_factory=write_factory,
        path_discovery=path_discovery,
        scorer=scorer,
        template_matcher=template_matcher,
        instance_uuid=instance_uuid,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-path-insight-worker",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "instance_uuid": str(instance_uuid),
        },
    )

    try:
        # Run the worker loop and the stop-event wait concurrently.
        worker_task = asyncio.create_task(worker.run_loop(), name="path_insight_worker_loop")
        stop_task = asyncio.create_task(stop_event.wait(), name="stop_event_wait")

        done, pending = await asyncio.wait(
            {worker_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel whatever is still running.
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Re-raise worker exceptions so the process exits non-zero on crash.
        if worker_task in done and not worker_task.cancelled():
            exc = worker_task.exception()
            if exc is not None:
                log.error("path_insight_worker_fatal_error", error=str(exc))
                sys.exit(1)

    finally:
        with contextlib.suppress(Exception):
            await engine.dispose()
        if read_engine is not engine:
            with contextlib.suppress(Exception):
                await read_engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()

    log.info("path_insight_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
