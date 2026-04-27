"""Standalone scheduler entry point for the Knowledge Graph service (S7).

Runs as an independent process (R22). Starts the APScheduler-based
``KnowledgeGraphScheduler`` with all 8 worker jobs.  Worker slots that
require an LLM client are wired best-effort — jobs fall back to no-op
stubs when the client is unavailable.

Run with::

    python -m knowledge_graph.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Any

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.scheduler.scheduler import (
        KnowledgeGraphScheduler,
        build_workers,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-scheduler",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.scheduler_main")  # type: ignore[no-any-return]
    log.info("scheduler_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
    from messaging.valkey.client import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey_client = create_valkey_client_from_url(settings.valkey_url)

    # Build embedding client based on provider (KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER).
    # Wire the embedding adapter so that the 6 KG embedding workers
    # (definition, narrative, fundamentals, summary, provisional, embedding_refresh)
    # are activated. Without llm_client these all become no-op stubs and no entity
    # embeddings or relation evidence gets materialised.
    _embedding_provider = settings.embedding_provider.lower()
    if _embedding_provider == "deepinfra" and settings.embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client: Any = DeepInfraEmbeddingAdapter(
            api_key=settings.embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "kg_embedding_deepinfra_adapter_selected",
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    else:
        if _embedding_provider == "deepinfra" and not settings.embedding_api_key:
            log.warning(
                "kg_embedding_deepinfra_key_missing_fallback_to_ollama",
                provider=_embedding_provider,
            )
        from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client = OllamaEmbeddingAdapter(
            base_url=settings.ollama_base_url,
            model_id=settings.embedding_model_id,
            semaphore=asyncio.Semaphore(1),  # single Ollama slot for KG scheduler
        )
        log.info("kg_embedding_ollama_adapter_selected", model_id=settings.embedding_model_id)

    llm_client = FallbackChainClient(
        ollama_embedding=embed_client,
        # Gemini embedding / extraction adapters are wired only when keys are
        # present; for now the selected embedding adapter is sufficient.
        retry_delays_ollama=(5.0, 30.0),  # shorter delays for scheduler context
    )
    workers = build_workers(settings, write_factory, llm_client=llm_client, valkey_client=valkey_client)
    scheduler = KnowledgeGraphScheduler(settings, workers=workers)

    # Standalone scheduler: no consumer coroutine — use an async no-op
    async def _noop_consumer() -> None:
        """No-op consumer placeholder — consumers run in separate processes."""
        await stop_event.wait()

    try:
        await scheduler.start(_noop_consumer())
        await stop_event.wait()
    except Exception as exc:
        log.error("scheduler_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("scheduler_stopped")
    finally:
        with contextlib.suppress(Exception):
            await scheduler.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
