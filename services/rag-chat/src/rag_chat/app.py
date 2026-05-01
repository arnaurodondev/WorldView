"""FastAPI application factory — S8 RAG/Chat service.

Observability wiring follows STANDARDS.md §5 (canonical lifespan pattern):
  1. configure_logging()   — always first
  2. configure_tracing()   — conditional on otlp_endpoint
  3. DB session factory    — R23 dual-URL (write + read)
  4. Valkey client
  5. Provider negative cache (populated by LLM client in later waves)
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
from observability import configure_logging, get_logger, register_error_handlers  # type: ignore[import-untyped]
from observability.metrics import (  # type: ignore[import-untyped]
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from rag_chat.api import health as health_router
from rag_chat.api.routes import briefings as briefings_router
from rag_chat.api.routes import chat as chat_router
from rag_chat.api.routes import internal_costs as internal_costs_router
from rag_chat.api.routes import public_briefings as public_briefings_router
from rag_chat.api.routes import threads as threads_router
from rag_chat.infrastructure.config.settings import RagChatSettings
from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids  # type: ignore[import-untyped]

        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _VALID_REQUEST_ID_RE.match(raw_id) else common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: RagChatSettings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("rag_chat.app")  # type: ignore[no-any-return]

    # 2. Tracing — conditional
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. DB session factory — R23 dual-URL
    from rag_chat.infrastructure.db.session import create_rag_session_factory

    engine, read_engine, write_factory, read_factory = create_rag_session_factory(settings)
    app.state.engine = engine
    app.state.read_engine = read_engine
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory

    # 4. Valkey client
    valkey_client = ValkeyClient(url=settings.valkey_url)
    app.state.valkey = valkey_client

    # 5. Provider negative cache
    app.state.provider_cache = {}  # type: ignore[assignment]

    # 6. Build and wire the ChatOrchestrator
    _wire_orchestrator(app, settings, valkey_client)

    # 7. Build and wire the GenerateBriefingUseCase
    _wire_briefing_uc(app, settings, valkey_client)

    # 8. InternalJWTMiddleware — fetch JWKS from S9 (PRD-0025)
    jwt_mw = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
    )
    await jwt_mw.startup()

    log.info("rag_chat_started", service=settings.service_name)  # type: ignore[no-any-return]
    yield

    # Shutdown — reverse order
    # If ContextManager is attached to app.state in a future wave, call:
    #   await app.state.context_manager.shutdown()
    # before closing Valkey (M-04: drains in-flight turn-summary background tasks).
    await valkey_client.close()
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
    log.info("rag_chat_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def _wire_orchestrator(app: FastAPI, settings: RagChatSettings, valkey_client: ValkeyClient) -> None:
    """Build and attach the ChatOrchestrator to app.state."""

    from rag_chat.application.caching.completion_cache import CompletionCache
    from rag_chat.application.caching.rate_limiter import RateLimiter
    from rag_chat.application.pipeline.fusion import FusionPipeline, GraphEnricher
    from rag_chat.application.pipeline.hyde_expander import HydeExpander
    from rag_chat.application.pipeline.intent_classifier import (
        DeepInfraIntentClassifier,
        OllamaIntentClassifier,
    )
    from rag_chat.application.pipeline.reranker import (
        BGEReranker,
        CohereReranker,
        DeepInfraReranker,
    )
    from rag_chat.application.pipeline.retrieval_orchestrator import ParallelRetrievalOrchestrator
    from rag_chat.application.pipeline.retrieval_plan_builder import RetrievalPlanBuilder
    from rag_chat.application.security.input_validator import InputValidator
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestrator
    from rag_chat.application.use_cases.get_thread import GetThreadUseCase
    from rag_chat.application.use_cases.persist_chat import ChatPersistenceUseCase
    from rag_chat.infrastructure.clients.s1_client import S1Client
    from rag_chat.infrastructure.clients.s3_client import S3Client
    from rag_chat.infrastructure.clients.s6_client import S6Client
    from rag_chat.infrastructure.clients.s7_client import S7Client
    from rag_chat.infrastructure.llm.ollama_adapter import OllamaCompletionAdapter
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

    # Upstream service clients
    s6 = S6Client(base_url=settings.s6_base_url, timeout=settings.upstream_timeout_seconds)
    s7 = S7Client(base_url=settings.s7_base_url, timeout=settings.upstream_timeout_seconds)
    s3 = S3Client(base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds)
    s1 = S1Client(
        base_url=settings.s1_base_url,
        valkey=valkey_client,
        timeout=settings.upstream_timeout_seconds,
    )

    # LLM provider chain
    providers: list[Any] = []
    if settings.deepinfra_api_key:
        from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

        providers.append(
            DeepInfraCompletionAdapter(
                api_key=settings.deepinfra_api_key,
                model=settings.completion_model,  # RAG_CHAT_COMPLETION_MODEL
            )
        )
    if settings.openrouter_api_key:
        from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

        providers.append(
            OpenRouterCompletionAdapter(
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_completion_model,  # RAG_CHAT_OPENROUTER_COMPLETION_MODEL
            )
        )
    # Ollama is always the emergency fallback
    providers.append(OllamaCompletionAdapter(base_url=settings.ollama_base_url, model=settings.ollama_completion_model))

    # PLAN-0052 QA-R6: wire the session-scoped usage logger so every successful
    # or failed LLM call writes a cost row to rag_chat_db.llm_usage_log.
    # The write_factory was created before _wire_orchestrator() is called (step 3
    # in lifespan), so app.state.write_factory is available here.
    from rag_chat.infrastructure.db.usage_log_factory import SessionScopedRagUsageLogger

    usage_logger = SessionScopedRagUsageLogger(session_factory=app.state.write_factory)
    llm_chain = LLMProviderChain(providers=providers, valkey=valkey_client, usage_logger=usage_logger)

    # Embedding: provider selection via RAG_CHAT_JINA_API_KEY.
    #   - jina_api_key set  → use JinaEmbeddingAdapter directly (1024-dim, ~100-300ms REST)
    #   - jina_api_key None → use S6 HTTP endpoint (proxies to whatever S6 embedding_provider is set to)
    #
    # WHY Jina direct path: it bypasses the S6 → Ollama hop entirely, giving ~100-300ms
    # query embedding instead of 7-13s on CPU Ollama.  When NLP_PIPELINE_EMBEDDING_PROVIDER
    # is also set to "jina" (same key), ingestion and query embeddings both use the same
    # Jina model and remain in the same vector space.
    #
    # WHY separate timeout on S6 path: Ollama bge-large on CPU takes 10-15s; the shared
    # upstream_timeout_seconds (10s) is insufficient (BP-225 class: embed timeout →
    # empty vector → 0 chunks retrieved).  Fix: 60s dedicated timeout for S6 embed.
    if settings.jina_api_key:
        # Direct Jina embedding — no S6 hop needed.
        # task="retrieval.query" tells Jina to optimise the embedding for ANN search.
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

        _jina = JinaEmbeddingAdapter(api_key=settings.jina_api_key, task="retrieval.query")

        class _JinaEmbeddingAdapter:
            """Thin wrapper around JinaEmbeddingAdapter matching the embed(text) -> list[float] protocol."""

            async def embed(self, text: str) -> list[float]:
                try:
                    outputs = await _jina.embed([EmbeddingInput(text=text, model_id="jina-embeddings-v3")])
                    return outputs[0].embedding if outputs else []
                except Exception as exc:
                    get_logger("rag_chat.embed").warning("jina_embed_error", error=str(exc))  # type: ignore[no-any-return]
                    return []

        embedding_client: Any = _JinaEmbeddingAdapter()
        get_logger("rag_chat.app").info("query_embedding_jina_selected")  # type: ignore[no-any-return]
    else:
        # S6 endpoint — forwards to whatever provider S6 is configured with (Ollama / DeepInfra / Jina).
        class _S6EmbeddingAdapter:
            """Minimal embedding adapter that calls S6 POST /api/v1/embed.

            Uses a dedicated httpx.AsyncClient with a 60-second timeout because
            Ollama bge-large / nomic-embed-text on CPU take 10-15 seconds per call.
            The shared BaseUpstreamClient timeout (10s) is insufficient and causes
            the embed to time out, which cascades into 0 chunks retrieved for every
            chat request (BP-225 class: embed timeout → empty vector → RuntimeError
            in nlp-pipeline chunk search → 500 → retrieval_task_failed).
            """

            def __init__(self, base_url: str) -> None:
                import httpx

                self._client = httpx.AsyncClient(base_url=base_url, timeout=60.0)

            async def embed(self, text: str) -> list[float]:
                import httpx

                from rag_chat.infrastructure.clients.auth_context import get_current_jwt

                headers: dict[str, str] = {}
                jwt = get_current_jwt()
                if jwt:
                    headers["X-Internal-JWT"] = jwt
                try:
                    resp = await self._client.post(
                        "/api/v1/embed",
                        json={"text": text},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    result: list[float] = resp.json().get("embedding", [])
                    return result
                except httpx.TimeoutException:
                    get_logger("rag_chat.embed").warning("s6_embed_timeout", timeout=60.0)  # type: ignore[no-any-return]
                    return []
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    get_logger("rag_chat.embed").warning("s6_embed_error", error=str(exc))  # type: ignore[no-any-return]
                    return []

        embedding_client = _S6EmbeddingAdapter(settings.s6_base_url)

    # ── Intent classifier: DeepInfra GPU (primary) → Ollama (fallback) ─────────
    # DeepInfraIntentClassifier is used when a deepinfra_api_key is configured.
    # It uses a 3B model on DeepInfra GPU (~100-200ms) instead of qwen3:0.6b on
    # CPU Ollama (2-20s, causes 100% fallback to keyword heuristic in practice).
    # Both classifiers fall back to KeywordHeuristicClassifier on any error.
    if settings.deepinfra_api_key:
        classifier: Any = DeepInfraIntentClassifier(
            api_key=settings.deepinfra_api_key,
            model=settings.deepinfra_classification_model,
        )
    else:
        classifier = OllamaIntentClassifier(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_classification_model,
        )

    # ── Reranker selection (PLAN-0052 platform-QA round 5) ──────────────────
    # Priority order:
    #   1. DeepInfra Qwen3-Reranker-0.6B — confirmed available on our account,
    #      sub-second latency at $0.00025/query (24 docs). Replaces the previous
    #      Ollama BGE path that was 100% broken (model not in Ollama registry —
    #      every call 404'd → silent fusion_score fallback for hours).
    #   2. Cohere Rerank v2 — only used when an explicit `cohere_api_key` is
    #      configured. Kept as an alternative for installations that prefer
    #      Cohere + don't have DeepInfra credits.
    #   3. BGE Ollama — last-resort local-only path. Documented as "always
    #      falls back" for the bge-reranker-v2-m3 model name; useful only if
    #      an operator manually `ollama pull`s a working reranker model.
    if settings.deepinfra_api_key:
        reranker: Any = DeepInfraReranker(api_key=settings.deepinfra_api_key)
    elif settings.cohere_api_key:
        reranker = CohereReranker(api_key=settings.cohere_api_key)
    else:
        reranker = BGEReranker(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_reranker_model,
        )

    orchestrator = ChatOrchestrator(
        validator=InputValidator(),
        rate_limiter=RateLimiter(valkey=valkey_client, limit=settings.rate_limit_per_tenant),
        cache=CompletionCache(valkey=valkey_client),
        get_thread_uc=GetThreadUseCase(),
        s6_client=s6,
        classifier=classifier,
        plan_builder=RetrievalPlanBuilder(cypher_enabled=settings.cypher_enabled),
        hyde=HydeExpander(
            llm_provider=providers[0],  # use primary provider (DeepInfra when key set)
            embedding_client=embedding_client,
            valkey=valkey_client,
        ),
        embedding_client=embedding_client,
        retrieval=ParallelRetrievalOrchestrator(
            s6_client=s6,
            s7_client=s7,
            s3_client=s3,
            s1_client=s1,
            timeout=settings.upstream_timeout_seconds,
            s1_internal_token=settings.s1_internal_token,
        ),
        graph_enricher=GraphEnricher(),
        fusion=FusionPipeline(),
        reranker=reranker,
        llm_chain=llm_chain,
        persistence=ChatPersistenceUseCase(),
    )
    app.state.chat_orchestrator = orchestrator
    app.state.llm_chain = llm_chain


def _wire_briefing_uc(app: FastAPI, settings: RagChatSettings, valkey_client: ValkeyClient) -> None:
    """Build and attach GenerateBriefingUseCase (with BriefingContextGatherer) to app.state.

    Creates separate client instances for the BriefingContextGatherer rather than
    re-using the ChatOrchestrator's clients.  WHY separate: the orchestrator clients
    were created inside _wire_orchestrator() without being stored on app.state, so
    they are not accessible here.  Creating new instances is lightweight (no persistent
    connections — httpx clients open connections lazily per-request).
    """
    from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.infrastructure.clients.s1_client import S1Client
    from rag_chat.infrastructure.clients.s3_client import S3Client
    from rag_chat.infrastructure.clients.s5_client import S5Client
    from rag_chat.infrastructure.clients.s6_client import S6Client
    from rag_chat.infrastructure.clients.s7_client import S7Client

    s1 = S1Client(
        base_url=settings.s1_base_url,
        valkey=valkey_client,
        timeout=settings.upstream_timeout_seconds,
    )
    s3 = S3Client(base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds)
    # S5Client accepts an optional internal_jwt at construction for default auth; passing
    # None here means each gather call supplies the per-request JWT via x_internal_jwt kwarg.
    s5 = S5Client(base_url=settings.s5_base_url, timeout=settings.upstream_timeout_seconds)
    s6 = S6Client(base_url=settings.s6_base_url, timeout=settings.upstream_timeout_seconds)
    s7 = S7Client(base_url=settings.s7_base_url, timeout=settings.upstream_timeout_seconds)

    context_gatherer = BriefingContextGatherer(s1=s1, s3=s3, s5=s5, s6=s6, s7=s7)

    app.state.briefing_uc = GenerateBriefingUseCase(
        llm_chain=app.state.llm_chain,  # same chain as ChatOrchestrator
        valkey=valkey_client,
        context_gatherer=context_gatherer,
    )


def create_app(settings: RagChatSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved = settings or RagChatSettings()  # type: ignore[call-arg]

    app = FastAPI(
        title="rag-chat",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # Middleware (must be registered before startup)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{resolved.api_gateway_url}/internal/jwks",
        skip_verification=resolved.internal_jwt_skip_verification,
    )
    metrics: Any = create_metrics(service_name=resolved.service_name)
    ml_metrics = create_ml_metrics(resolved.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    app.state.ml_metrics = ml_metrics

    # Routers
    app.include_router(health_router.router)
    app.include_router(threads_router.router)
    app.include_router(chat_router.router)
    app.include_router(briefings_router.router)
    app.include_router(public_briefings_router.router)
    app.include_router(internal_costs_router.router)

    return app
