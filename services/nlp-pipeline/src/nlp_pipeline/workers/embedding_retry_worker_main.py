"""Entry point for the EmbeddingRetryWorker process (PLAN-0057 Wave E-4 / F-MAJOR-05, R22).

Run as a standalone process (never as a background task inside the API):

    python -m nlp_pipeline.workers.embedding_retry_worker_main

Responsibilities:
  - Configure logging
  - Load Settings from environment
  - Wire nlp_db session factory + embedding adapter (matches the API process
    so retry-time embeddings land in the same vector space)
  - Surface ``embedding_retry_abandoned_at_startup`` count for ops visibility
  - Install SIGINT / SIGTERM handlers
  - Run EmbeddingRetryWorker.run_forever() until the stop event is set
  - Exit with code 0 on clean shutdown, code 1 on startup failure

The audit (2026-04-29 §F-MAJOR-05) caught that this entry point was missing
even though the worker class itself had been implemented for two months —
``embedding_pending`` simply accumulated rows nobody was draining.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Any

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _build_embedding_client(settings: Any) -> Any:
    """Pick the same embedding adapter the API process uses (mirror of app.py).

    Kept inline here to avoid coupling this entry point to the FastAPI factory;
    settings.embedding_provider drives the choice and the API and worker
    processes must agree on the same vector space.
    """
    provider = settings.embedding_provider.lower()
    if provider == "deepinfra" and settings.embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import (  # type: ignore[import-not-found]
            DeepInfraEmbeddingAdapter,
        )

        return DeepInfraEmbeddingAdapter(
            api_key=settings.embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    if provider == "jina" and settings.jina_api_key:
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]

        return JinaEmbeddingAdapter(api_key=settings.jina_api_key)
    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

    return OllamaEmbeddingAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.embedding_model_id,
        # Single Ollama slot — retry traffic is not bursty and contending with
        # the API process for the local model would slow user-facing queries.
        semaphore=asyncio.Semaphore(1),
    )


async def main() -> None:
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending import (
        EmbeddingPendingRepository,
    )
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.workers.embedding_retry_worker import (
        EmbeddingRetryWorker,
    )

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-embedding-retry-worker",
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("nlp_pipeline.embedding_retry_worker_main")  # type: ignore[no-any-return]
    log.info("embedding_retry_worker_starting")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        nlp_engine, _read_engine, nlp_sf, _read_sf = _build_nlp_factories(settings)
    except Exception as exc:
        log.error("embedding_retry_worker_startup_failed", error=str(exc))
        sys.exit(1)

    # Surface any pre-existing abandoned rows so silent rot is impossible.
    async with nlp_sf() as session:
        repo = EmbeddingPendingRepository(session)
        abandoned = await repo.count_abandoned(max_retries=5)
    if abandoned:
        log.warning(
            "embedding_retry_abandoned_at_startup",
            count=abandoned,
            note="rows with retry_count>=5 are skipped by claim_batch and need manual triage",
        )

    embedding_client = _build_embedding_client(settings)
    worker = EmbeddingRetryWorker(
        nlp_session_factory=nlp_sf,
        embedding_client=embedding_client,
        model_id=settings.embedding_api_model_id
        if settings.embedding_provider.lower() == "deepinfra"
        else settings.embedding_model_id,
        instruction_prefix=settings.embedding_instruction_prefix,
    )

    log.info("embedding_retry_worker_ready", provider=settings.embedding_provider)

    worker_task = asyncio.create_task(worker.run_forever(stop_event), name="embedding_retry_worker")

    await stop_event.wait()
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task

    await nlp_engine.dispose()
    log.info("embedding_retry_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
