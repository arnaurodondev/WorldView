"""Market-ingestion reclaim worker standalone entry point.

Periodically reclaims data from the primary provider when tasks were
served by a secondary (fallback) provider.  Intended to run as a
separate container/process (R22 — NOT co-located with the task executor).

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.reclaim_worker_main
"""

from __future__ import annotations

import asyncio
import signal

from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
from market_ingestion.config import Settings
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from market_ingestion.infrastructure.workers.reclaim_worker import PrimaryProviderReclaimWorker
from observability.logging import get_logger  # type: ignore[import-untyped]

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
    worker = _create_reclaim_worker(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)

    await worker.run()


def main() -> None:
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.workers.reclaim_worker_main``."""
    asyncio.run(_run_reclaim_worker())


if __name__ == "__main__":
    main()
