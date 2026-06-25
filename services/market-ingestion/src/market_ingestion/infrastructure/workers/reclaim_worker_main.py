"""Market-ingestion reclaim worker standalone entry point.

Periodically reclaims data from the primary provider when tasks were
served by a secondary (fallback) provider.  Intended to run as a
separate container/process (R22 — NOT co-located with the task executor).

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.reclaim_worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
from market_ingestion.config import Settings
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from market_ingestion.infrastructure.workers.reclaim_worker import PrimaryProviderReclaimWorker
from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)


def _create_reclaim_worker(settings: Settings) -> PrimaryProviderReclaimWorker:
    """Build a fully-wired PrimaryProviderReclaimWorker from *settings*.

    The UoW factory creates a fresh ``SqlaUnitOfWork`` per cycle so that
    each reclaim run gets its own DB session (no stale connections).
    The routing cache is loaded once from env-var config at startup.
    """
    write_factory, read_factory = _build_factories(settings)

    def uow_factory() -> SqlaUnitOfWork:
        return SqlaUnitOfWork(write_factory, read_factory)

    # Build and load the provider routing cache from env-var config
    routing_cache = ProviderRoutingCache()
    routing_cache.load_from_config(settings)

    return PrimaryProviderReclaimWorker(
        uow_factory=uow_factory,
        routing_cache=routing_cache,
    )


async def _run_reclaim_worker() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]

    # PLAN-0107 B-4 — full logging lifecycle (worst-6 fix).
    configure_logging(
        service_name="market-ingestion-reclaim-worker",
        level=getattr(settings, "log_level", "INFO"),
        json=getattr(settings, "log_json", True),
    )
    log = get_logger("market_ingestion.reclaim_worker_main")  # type: ignore[no-any-return]
    log.info("market_ingestion_reclaim_worker_starting")

    try:
        worker = _create_reclaim_worker(settings)

        # F-005 / BP-704 — expose Prometheus /metrics + /healthz so the Docker
        # healthcheck on METRICS_PORT (default 9100) can reach /healthz.
        metrics_handle = start_metrics_server(
            service_name="market-ingestion-reclaim-worker",
            port=int(os.environ.get("METRICS_PORT", "9100")),
        )

        log_runtime_banner(
            "market-ingestion-reclaim-worker",
            dependencies={
                "postgres_dsn": str(settings.database_url),
            },
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, worker.stop)

        try:
            await worker.run()
        finally:
            with contextlib.suppress(Exception):
                await metrics_handle.aclose()
    except Exception:
        log.exception("market_ingestion_reclaim_worker_startup_failed")
        raise
    finally:
        log.info("market_ingestion_reclaim_worker_stopped")


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.workers.reclaim_worker_main``."""
    asyncio.run(_run_reclaim_worker())


if __name__ == "__main__":
    main()
