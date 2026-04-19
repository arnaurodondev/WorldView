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
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from rag_chat.api import health as health_router
from rag_chat.api.routes import briefings as briefings_router
from rag_chat.api.routes import chat as chat_router
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
    from rag_chat.application.pipeline.intent_classifier import OllamaIntentClassifier
    from rag_chat.application.pipeline.reranker import BGEReranker
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

        providers.append(DeepInfraCompletionAdapter(api_key=settings.deepinfra_api_key))
    if settings.openrouter_api_key:
        from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

        providers.append(OpenRouterCompletionAdapter(api_key=settings.openrouter_api_key))
    # Ollama is always the emergency fallback
    providers.append(OllamaCompletionAdapter(base_url=settings.ollama_base_url, model=settings.ollama_completion_model))
    llm_chain = LLMProviderChain(providers=providers, valkey=valkey_client)

    # Embedding: use S6 embedding endpoint via a simple adapter
    class _S6EmbeddingAdapter:
        """Minimal embedding adapter that calls S6 POST /api/v1/embed."""

        def __init__(self, client: Any) -> None:
            self._client = client

        async def embed(self, text: str) -> list[float]:
            raw = await self._client._post("/api/v1/embed", {"text": text})
            result: list[float] = raw.get("embedding", [])
            return result

    embedding_client = _S6EmbeddingAdapter(s6)

    orchestrator = ChatOrchestrator(
        validator=InputValidator(),
        rate_limiter=RateLimiter(valkey=valkey_client, limit=settings.rate_limit_per_tenant),
        cache=CompletionCache(valkey=valkey_client),
        get_thread_uc=GetThreadUseCase(),
        s6_client=s6,
        classifier=OllamaIntentClassifier(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_classification_model,
        ),
        plan_builder=RetrievalPlanBuilder(cypher_enabled=settings.cypher_enabled),
        hyde=HydeExpander(
            llm_provider=providers[-1],  # use Ollama for HyDE (lightweight)
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
        reranker=BGEReranker(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_reranker_model,
        ),
        llm_chain=llm_chain,
        persistence=ChatPersistenceUseCase(),
    )
    app.state.chat_orchestrator = orchestrator
    app.state.llm_chain = llm_chain


def _wire_briefing_uc(app: FastAPI, settings: RagChatSettings, valkey_client: ValkeyClient) -> None:
    """Build and attach GenerateBriefingUseCase to app.state."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    app.state.briefing_uc = GenerateBriefingUseCase(
        llm_chain=app.state.llm_chain,  # same chain as ChatOrchestrator
        valkey=valkey_client,
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

    # Middleware (must be registered before startup)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{resolved.api_gateway_url}/internal/jwks",
        skip_verification=resolved.internal_jwt_skip_verification,
    )
    metrics: Any = create_metrics(service_name=resolved.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Routers
    app.include_router(health_router.router)
    app.include_router(threads_router.router)
    app.include_router(chat_router.router)
    app.include_router(briefings_router.router)
    app.include_router(public_briefings_router.router)

    return app
