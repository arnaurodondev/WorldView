"""Entry point for the UnresolvedResolutionWorker process (PLAN-0033, R22).

Run as a standalone process (never as a background task inside the API):

    python -m nlp_pipeline.workers.unresolved_resolution_worker_main

Responsibilities:
  - Configure logging
  - Load Settings from environment
  - Wire nlp_db + intelligence_db session factories
  - Call recover_stale_escalated() once on startup
  - Install SIGINT / SIGTERM handlers
  - Run UnresolvedResolutionWorker.run_loop() until cancelled
  - Exit with code 0 on clean shutdown, code 1 on startup failure
"""

from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.intelligence_db.session import _build_intelligence_factories
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.nlp_db.usage_log_factory import SessionScopedNlpUsageLogger
    from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
        UnresolvedResolutionWorker,
    )

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-unresolved-resolution-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.unresolved_resolution_worker_main")  # type: ignore[no-any-return]
    log.info("unresolved_resolution_worker_starting")

    # ── Wire dependencies ─────────────────────────────────────────────────────
    try:
        nlp_engine, _nlp_read_engine, nlp_sf, _nlp_read_sf = _build_nlp_factories(settings)
        intel_engine, _intel_read_engine, intel_sf, _intel_read_sf = _build_intelligence_factories(settings)
    except Exception as exc:
        log.error("unresolved_resolution_worker_startup_failed", error=str(exc))
        sys.exit(1)

    # PLAN-0057 A-5 / F-CRIT-03: thread a session-scoped usage logger so every
    # Phase-2 Ollama / DeepInfra classification call writes a row to
    # nlp_db.llm_usage_log.  Until this fix the table was permanently empty.
    worker = UnresolvedResolutionWorker(
        nlp_session_factory=nlp_sf,
        settings=settings,
        intel_session_factory=intel_sf,
        usage_logger=SessionScopedNlpUsageLogger(nlp_sf),
    )

    # Reset any stuck-escalated mentions from a previous crash (one-time startup call).
    await worker.recover_stale_escalated()

    log.info(
        "unresolved_resolution_worker_ready",
        interval_s=settings.unresolved_resolution_interval_s,
        batch_size=settings.unresolved_resolution_batch_size,
    )

    # ── Run loop with graceful shutdown ───────────────────────────────────────
    worker_task = asyncio.create_task(worker.run_loop())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker_task.cancel)

    with suppress(asyncio.CancelledError):
        await worker_task

    await nlp_engine.dispose()
    await intel_engine.dispose()
    log.info("unresolved_resolution_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
