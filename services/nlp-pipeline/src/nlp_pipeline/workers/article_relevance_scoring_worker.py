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
        api_key=settings.relevance_scoring_api_key,
        api_base_url=settings.relevance_scoring_api_base_url,
        api_model_id=settings.relevance_scoring_api_model_id,
    )

    _using_external = bool(settings.relevance_scoring_api_key)
    log.info(
        "relevance_scoring_worker_ready",
        provider="deepinfra" if _using_external else "ollama",
        model=settings.relevance_scoring_api_model_id if _using_external else settings.relevance_scoring_model,
        cycle_seconds=settings.relevance_scoring_cycle_seconds,
    )

    # PLAN-0055 C-3: piggyback the document_source_llm_latest materialized-view
    # refresher on this worker process. It shares the same DB session factory and
    # already lives in the LLM-scoring lifecycle, so no separate process is needed.
    # Refresh interval: 300s (matches the 5-min staleness budget).
    async def _refresh_llm_latest_loop() -> None:
        import contextlib as _ctxlib

        from sqlalchemy import text as _text

        refresh_interval_s = 300
        while not stop_event.is_set():
            try:
                async with nlp_sf() as session:
                    await session.execute(_text("REFRESH MATERIALIZED VIEW CONCURRENTLY document_source_llm_latest"))
                    await session.commit()
                log.info("dsl_latest_refreshed")
            except Exception as exc:  # — informational; never crash the worker
                log.warning("dsl_latest_refresh_failed", error=str(exc))
            with _ctxlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=refresh_interval_s)

    refresh_task = asyncio.create_task(_refresh_llm_latest_loop(), name="dsl_latest_refresh")

    try:
        await worker.run_forever(stop_event)
    finally:
        refresh_task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await refresh_task

    await nlp_engine.dispose()
    log.info("relevance_scoring_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
