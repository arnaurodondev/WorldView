"""Entry point for the ArticleRelevanceScoringWorker process (PRD-0026 §6.7 Flow B, R22).

Run as a standalone process (never as a background task inside the API):

    python -m nlp_pipeline.workers.article_relevance_scoring_worker

Responsibilities:
  - Configure logging
  - Load Settings from environment
  - Wire nlp_db session factory
  - Install SIGINT / SIGTERM handlers
  - Run ArticleRelevanceScoringWorker.run_forever() until stop event is set
  - Exit with code 0 on clean shutdown, code 1 on startup failure
"""

from __future__ import annotations

import asyncio
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.workers.article_relevance_scoring_worker import (
        ArticleRelevanceScoringWorker,
    )

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-relevance-scoring-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.relevance_scoring_worker_main")  # type: ignore[no-any-return]
    log.info("relevance_scoring_worker_starting")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # ── Wire dependencies ─────────────────────────────────────────────────────
    try:
        nlp_engine, _read_engine, nlp_sf, _read_sf = _build_nlp_factories(settings)
    except Exception as exc:
        log.error("relevance_scoring_worker_startup_failed", error=str(exc))
        sys.exit(1)

    worker = ArticleRelevanceScoringWorker(
        nlp_session_factory=nlp_sf,
        ollama_url=settings.relevance_scoring_ollama_url,
        model=settings.relevance_scoring_model,
        batch_size=settings.relevance_scoring_batch_size,
        timeout_seconds=settings.relevance_scoring_timeout_seconds,
        cycle_seconds=settings.relevance_scoring_cycle_seconds,
    )

    log.info(
        "relevance_scoring_worker_ready",
        ollama_url=settings.relevance_scoring_ollama_url,
        model=settings.relevance_scoring_model,
        cycle_seconds=settings.relevance_scoring_cycle_seconds,
    )
    await worker.run_forever(stop_event)

    await nlp_engine.dispose()
    log.info("relevance_scoring_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
