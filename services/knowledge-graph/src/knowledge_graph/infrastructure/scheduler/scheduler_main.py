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

    # Phase 1 of worker-metrics rollout replaced the legacy
    # `prometheus_client.start_http_server(9108)` call with the shared ASGI
    # helper (see `metrics_handle = start_metrics_server(...)` below). The
    # historical call has been removed — leaving both produced a double-bind
    # on port 9108 (EADDRINUSE) that crashed the scheduler in a restart loop.

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # PLAN-0028 worker-metrics rollout phase 1: replace the historical
    # ad-hoc ``prometheus_client.start_http_server(9108)`` call with the
    # shared ASGI helper so this scheduler also exposes /healthz and
    # cleanly shuts down with the rest of the asyncio loop.  Port 9108
    # is preserved for backwards compatibility with the existing
    # Prometheus scrape job.
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-scheduler",
        port=9108,
    )

    # DEF-034 (Wave B-5): bind both engines + factories so the read replica is
    # threaded into ``build_workers`` and disposed in the teardown block below.
    engine, read_engine, write_factory, read_factory = _build_factories(settings)

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
    from messaging.valkey.client import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey_client = create_valkey_client_from_url(settings.valkey_url)

    # Build embedding client based on provider (KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER).
    # Wire the embedding adapter so that the 6 KG embedding workers
    # (definition, narrative, fundamentals, summary, provisional, embedding_refresh)
    # are activated. Without llm_client these all become no-op stubs and no entity
    # embeddings or relation evidence gets materialised.
    _embedding_provider = settings.embedding_provider.lower()
    _embedding_api_key = settings.embedding_api_key.get_secret_value()  # DEF-005
    if _embedding_provider == "deepinfra" and _embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client: Any = DeepInfraEmbeddingAdapter(
            api_key=_embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "kg_embedding_deepinfra_adapter_selected",
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    else:
        if _embedding_provider == "deepinfra" and not _embedding_api_key:
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

    # PLAN-0057 A-5 / F-CRIT-03: thread the session-scoped KG usage logger so
    # every embed/extract call from any scheduler-driven worker writes one row
    # to intelligence_db.llm_usage_log.
    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )

    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    # Build DeepInfra extraction adapter when API key is configured (PLAN-0061 T-C-2).
    # When present this becomes slot-0 in the extraction chain (DeepInfra → Ollama → Gemini).
    _deepinfra_api_key = settings.deepinfra_api_key.get_secret_value()  # DEF-005
    deepinfra_ext: Any = None
    if _deepinfra_api_key:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter  # type: ignore[import-not-found]

        deepinfra_ext = DeepSeekExtractionAdapter(
            api_key=_deepinfra_api_key,
            model_id=settings.deepinfra_extraction_model_id,
            base_url=settings.deepinfra_extraction_base_url,
            semaphore=asyncio.Semaphore(settings.deepinfra_extraction_concurrency),
        )
        log.info(
            "kg_extraction_deepinfra_adapter_selected",
            model_id=settings.deepinfra_extraction_model_id,
        )
    else:
        log.info("kg_extraction_deepinfra_key_absent_using_ollama_gemini_chain")

    # Ollama extraction is only wired when DeepInfra is not configured.
    # When deepinfra_api_key is set, GLiNER is the only local model; qwen3:0.6b
    # must NOT load because DeepInfra Qwen3.5-0.8B serves the extraction role.
    ollama_ext: Any = None
    if not _deepinfra_api_key:
        from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter  # type: ignore[import-not-found]

        _ollama_extraction_model = "qwen3:0.6b"
        ollama_ext = OllamaExtractionAdapter(
            base_url=settings.ollama_base_url,
            model_id=_ollama_extraction_model,
            semaphore=asyncio.Semaphore(1),
        )
        log.info("kg_extraction_ollama_fallback_wired", model_id=_ollama_extraction_model)
    else:
        log.info("kg_extraction_ollama_fallback_skipped_deepinfra_key_present")

    llm_client = FallbackChainClient(
        deepinfra_extraction=deepinfra_ext,
        ollama_embedding=embed_client,
        ollama_extraction=ollama_ext,
        # Gemini embedding / extraction adapters are wired only when keys are
        # present; for now the selected embedding adapter is sufficient.
        retry_delays_deepinfra=(5.0, 15.0),
        retry_delays_ollama=(5.0, 30.0),  # shorter delays for scheduler context
        usage_logger=kg_usage_logger,
    )

    # SA-2: wire the Gemini 2.5 Flash Lite extraction adapter as the explicit
    # last-resort fallback for SummaryWorker.  Uses the same KNOWLEDGE_GRAPH_GEMINI_API_KEY
    # that powers the description client.  When the key is absent, the fallback
    # is disabled (gemini_ext=None) and SummaryWorker behaviour is unchanged.
    gemini_ext: Any = None
    _gemini_api_key = settings.gemini_api_key.get_secret_value()
    if _gemini_api_key and settings.summary_fallback_provider.lower() == "gemini":
        from ml_clients.adapters.gemini_extraction import GeminiExtractionAdapter  # type: ignore[import-not-found]

        gemini_ext = GeminiExtractionAdapter(
            api_key=_gemini_api_key,
            model_id=settings.summary_fallback_model_id,
            semaphore=asyncio.Semaphore(2),  # limit to 2 concurrent summary calls
        )
        log.info(
            "kg_summary_gemini_fallback_wired",
            model_id=settings.summary_fallback_model_id,
        )
    else:
        log.info(
            "kg_summary_gemini_fallback_disabled",
            reason="gemini_api_key absent or summary_fallback_provider != gemini",
        )

    workers = build_workers(
        settings,
        write_factory,
        read_factory,
        llm_client=llm_client,
        valkey_client=valkey_client,
        usage_logger=kg_usage_logger,
        gemini_extraction_client=gemini_ext,
    )
    scheduler = KnowledgeGraphScheduler(settings, workers=workers)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-scheduler",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "valkey_url": getattr(settings, "valkey_url", None),
            "embedding_provider": settings.embedding_provider,
            "embedding_model_id": settings.embedding_api_model_id,
        },
    )

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
        # Stop the metrics ASGI server before disposing engines so its
        # background task does not outlive the process loop.  aclose()
        # is best-effort — its failure must not mask the original
        # shutdown reason.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        await engine.dispose()
        # DEF-034 (Wave B-5): dispose the read-replica engine alongside the
        # write engine.  Suppressed because a teardown failure must never
        # mask the original shutdown reason captured above.
        # QA-fix §2.4: skip when read_engine is the same object as the write
        # engine (no DATABASE_URL_READ configured) — calling dispose() twice
        # on one engine is idempotent but logs misleading diagnostics.
        if read_engine is not engine:
            with contextlib.suppress(Exception):
                await read_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
