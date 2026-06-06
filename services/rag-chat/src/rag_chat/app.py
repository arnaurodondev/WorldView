"""FastAPI application factory — S8 RAG/Chat service.

Observability wiring follows STANDARDS.md §5 (canonical lifespan pattern):
  1. configure_logging()   — always first
  2. configure_tracing()   — conditional on otlp_endpoint
  3. DB session factory    — R23 dual-URL (write + read)
  4. Valkey client
  5. Provider negative cache (populated by LLM client in later waves)
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
from observability import (  # type: ignore[import-untyped]
    assert_app_env_or_die,
    configure_logging,
    get_logger,
    register_error_handlers,
)
from observability.metrics import (  # type: ignore[import-untyped]
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
from observability.sentry import SentrySettings, init_sentry  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from rag_chat.api import health as health_router
from rag_chat.api.routes import briefings as briefings_router
from rag_chat.api.routes import chat as chat_router
from rag_chat.api.routes import internal as internal_router
from rag_chat.api.routes import internal_ai_brief_flag as internal_ai_brief_flag_router
from rag_chat.api.routes import internal_costs as internal_costs_router
from rag_chat.api.routes import proposal as proposal_router
from rag_chat.api.routes import public_briefings as public_briefings_router
from rag_chat.api.routes import threads as threads_router
from rag_chat.infrastructure.config.settings import RagChatSettings
from rag_chat.infrastructure.middleware.internal_jwt import InternalJWTMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from datetime import datetime

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

    # 1b. Boot-time security guard (PLAN-0093 Wave A-1 / F-LOG-JWT-001).
    # Refuses to start when JWT verification is disabled AND APP_ENV is unset.
    # This belongs BEFORE every other lifespan step so a misconfigured
    # container can never start accepting requests, even on the health endpoint.
    assert_app_env_or_die(
        service_name=settings.service_name,
        internal_jwt_skip_verification=settings.internal_jwt_skip_verification,
    )

    # 2. Tracing — conditional
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 2b. Sentry — fourth observability pillar (default-off: SENTRY_ENABLED=false)
    init_sentry(service_name=settings.service_name, settings=SentrySettings())

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

    # 4b. Deploy-version cache flush (PLAN-0097 W4 T-W4-04).
    # When ``RAG_CACHE_DEPLOY_TOKEN`` changes between deploys, flush the
    # completion cache so a new prompt/version is never served a stale answer.
    # See ``_maybe_flush_completion_cache`` for the full contract.
    await _maybe_flush_completion_cache(valkey_client, settings.cache_deploy_token, log)

    # 5. Provider negative cache
    app.state.provider_cache = {}  # type: ignore[assignment]

    # 6. Build and wire the ChatOrchestratorUseCase
    _wire_orchestrator(app, settings, valkey_client)

    # 6b. D-006: reconcile CB Prometheus gauges with Valkey state on startup.
    # Without this, a restart after a CB trip shows gauge=0 (healthy) while
    # the CB is actually open in Valkey (the state key has a TTL and persists
    # across restarts).  Reconciling here corrects the gauge immediately.
    await _reconcile_cb_gauges(app)

    # 7. Build and wire the GenerateBriefingUseCase
    _wire_briefing_uc(app, settings, valkey_client)

    # 7b. Build and wire EntityContextChatUseCase (PLAN-0074 Wave F)
    _wire_entity_context_uc(app, settings)

    # 8. Citation-accuracy cron (PLAN-0084 A-1 T-A-1-05)
    # Only starts when RAG_CHAT_CITATION_CRON_ENABLED=true (L5: flag-controlled rollout).
    # Uses read_factory (R23: read-only use case → ReadOnlyUnitOfWork equivalent).
    app.state.citation_cron_task = None
    if settings.citation_cron_enabled:
        # MN-1: pass the valkey client so the cron can guard its immediate
        # first run against crashloop replays (skip if last successful run
        # was < 1h ago). Valkey is wired in step 4 above so it's always
        # available here.
        _wire_citation_cron(app, settings, read_factory, log, valkey_client)

    # 9. InternalJWTMiddleware — fetch JWKS from S9 (PRD-0025)
    jwt_mw = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
    )
    await jwt_mw.startup()

    log.info("rag_chat_started", service=settings.service_name)  # type: ignore[no-any-return]
    yield

    # Shutdown — reverse order
    # Citation cron — cancel gracefully before closing DB/Valkey.
    # The gather(return_exceptions=True) prevents CancelledError from propagating.
    if app.state.citation_cron_task is not None:
        _cron_task: asyncio.Task[None] = app.state.citation_cron_task
        _cron_task.cancel()
        await asyncio.gather(_cron_task, return_exceptions=True)

    # If ContextManager is attached to app.state in a future wave, call:
    #   await app.state.context_manager.shutdown()
    # before closing Valkey (M-04: drains in-flight turn-summary background tasks).
    await valkey_client.close()
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
    log.info("rag_chat_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def _wire_orchestrator(app: FastAPI, settings: RagChatSettings, valkey_client: ValkeyClient) -> None:
    """Build and attach the ChatPipeline and ChatOrchestratorUseCase to app.state."""
    # PLAN-0107 / rag-chat-ml-metrics: build (or fetch the cached) MLMetrics
    # singleton for ``rag-chat``.  All ml-clients adapters that accept a
    # ``metrics=`` kwarg are wired against this single instance below so the
    # Grafana dashboard panels (``rag_chat_ml_api_*``) receive real series.
    from rag_chat.application.metrics.ml_clients import build_ml_metrics

    ml_metrics = build_ml_metrics(settings.service_name)

    from rag_chat.application.caching.completion_cache import CompletionCache
    from rag_chat.application.caching.rate_limiter import RateLimiter
    from rag_chat.application.pipeline.circuit_breaker import SourceCircuitBreaker
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
    from rag_chat.application.security.llm_injection_classifier import LLMInjectionClassifier
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase
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
    # DEF-034: extract raw strings from SecretStr before passing to adapters/constructors.
    _deepinfra_api_key = settings.deepinfra_api_key.get_secret_value() if settings.deepinfra_api_key else None
    _openrouter_api_key = settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    _cohere_api_key = settings.cohere_api_key.get_secret_value() if settings.cohere_api_key else None
    _jina_api_key = settings.jina_api_key.get_secret_value() if settings.jina_api_key else None

    # PLAN-0107 Agent-B + fix-up: instantiate the shared CostRecorder once and
    # inject it into every LLM adapter. The recorder is fault-tolerant by
    # construction (record() never raises) so a single instance is safe to
    # share across adapters + the citation judge.
    from rag_chat.infrastructure.llm.cost_recorder import PrometheusAndDbCostRecorder

    # Use app.state.write_factory — set during the DB-init lifespan step above.
    cost_recorder = PrometheusAndDbCostRecorder(write_session_factory=app.state.write_factory)
    app.state.cost_recorder = cost_recorder

    providers: list[Any] = []
    if _deepinfra_api_key:
        from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

        providers.append(
            DeepInfraCompletionAdapter(
                api_key=_deepinfra_api_key,
                model=settings.completion_model,  # RAG_CHAT_COMPLETION_MODEL
                # FIX-LIVE-X (2026-05-25): explicit tool-call budget. Previously
                # bound to the 30s default; Q6's second turn (Qwen3-235B with a
                # 5-tool message stack) timed out before HTTP dispatch and the
                # error surfaced as a blank `llm_first_turn_failed` to the user.
                chat_with_tools_timeout=settings.deepinfra_tool_call_timeout_seconds,
                # PLAN-0104 W43 / BP-NEW: same-provider model fallback on
                # zero-chunk SSE.  Empty string disables (W40 chain failover +
                # W36 degraded-synthesis fallback still apply).
                stream_chat_fallback_model=settings.deepinfra_stream_chat_fallback_model or None,
                # rag-chat-ml-metrics: feed chat_with_tools latency/requests/
                # status into ``rag_chat_ml_api_*`` so the Grafana panels light up.
                metrics=ml_metrics,
                cost_recorder=cost_recorder,  # PLAN-0107: per-call USD cost
            )
        )
    if _openrouter_api_key:
        from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

        providers.append(
            OpenRouterCompletionAdapter(
                api_key=_openrouter_api_key,
                model=settings.openrouter_completion_model,  # RAG_CHAT_OPENROUTER_COMPLETION_MODEL
                metrics=ml_metrics,  # rag-chat-ml-metrics: dashboard wiring
                cost_recorder=cost_recorder,  # PLAN-0107: per-call USD cost
            )
        )
    # Ollama is always the emergency fallback
    providers.append(
        OllamaCompletionAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_completion_model,
            metrics=ml_metrics,  # rag-chat-ml-metrics: dashboard wiring
            cost_recorder=cost_recorder,  # PLAN-0107: per-call USD cost (≈$0 for local)
        )
    )

    # PLAN-0052 QA-R6: wire the session-scoped usage logger so every successful
    # or failed LLM call writes a cost row to rag_chat_db.llm_usage_log.
    # The write_factory was created before _wire_orchestrator() is called (step 3
    # in lifespan), so app.state.write_factory is available here.
    from rag_chat.infrastructure.db.usage_log_factory import SessionScopedRagUsageLogger

    usage_logger = SessionScopedRagUsageLogger(session_factory=app.state.write_factory)
    # FIX-LIVE-EE (2026-05-25): wire iter-0 retry config from settings. Default
    # 2 attempts / 1.0s exponential base yields 1s+2s extra latency in the
    # worst case before falling back to OpenRouter — well within Q4-class SLOs.
    llm_chain = LLMProviderChain(
        providers=providers,
        valkey=valkey_client,
        usage_logger=usage_logger,
        retry_attempts=settings.provider_retry_attempts,
        retry_backoff_base=settings.provider_retry_backoff_base,
    )

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
    if _jina_api_key:
        # Direct Jina embedding — no S6 hop needed.
        # task="retrieval.query" tells Jina to optimise the embedding for ANN search.
        from ml_clients.adapters.jina_embedding import JinaEmbeddingAdapter  # type: ignore[import-not-found]
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

        # metrics=ml_metrics enables rag_chat_ml_api_{requests_total,latency_seconds,
        # tokens_in_total,estimated_cost_usd_total} updates inside the adapter's
        # finally block (jina_embedding.py ~L137).  Without this kwarg the
        # adapter's `if self._metrics:` guard short-circuits silently.
        _jina = JinaEmbeddingAdapter(api_key=_jina_api_key, task="retrieval.query", metrics=ml_metrics)

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
    if _deepinfra_api_key:
        classifier: Any = DeepInfraIntentClassifier(
            api_key=_deepinfra_api_key,
            model=settings.deepinfra_classification_model,
            usage_logger=usage_logger,
        )
    else:
        classifier = OllamaIntentClassifier(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_classification_model,
            usage_logger=usage_logger,
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
    if _deepinfra_api_key:
        reranker: Any = DeepInfraReranker(api_key=_deepinfra_api_key)
    elif _cohere_api_key:
        reranker = CohereReranker(api_key=_cohere_api_key)
    else:
        reranker = BGEReranker(
            ollama_base_url=settings.ollama_base_url,
            model=settings.ollama_reranker_model,
        )

    # PLAN-0063 W5-1-00: extract shared components so RetrieveOnlyUseCase can
    # reuse the same validator/classifier/plan-builder/HyDE/embedder/retrieval
    # graph the chat orchestrator uses. This guarantees the eval harness measures
    # exactly the same retrieval path that production chat uses.
    _validator = InputValidator()

    # E-8: Layer 2 LLM semantic injection classifier.
    # Uses the same DeepInfra API key as the completion model. Model is sourced
    # from settings (RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL, same field used by
    # the intent classifier) so both stay in sync.  When deepinfra_api_key is
    # absent the classifier disables itself (fail-open for Layer 2 check —
    # Layer 1 regex is always active).
    _llm_classifier = LLMInjectionClassifier(
        api_key=_deepinfra_api_key,
        model=settings.deepinfra_classification_model,
    )

    _plan_builder = RetrievalPlanBuilder()
    _hyde = HydeExpander(
        llm_provider=providers[0],
        embedding_client=embedding_client,
        valkey=valkey_client,
    )
    # PLAN-0079 Wave C: build TrustScorer from env-var-tunable weights so operators
    # can adjust the source/corroboration/extraction mix without redeploying code.
    from rag_chat.application.pipeline.trust_scorer import TrustScorer

    _trust_scorer = TrustScorer(
        w_source=settings.trust_w_source,
        w_corroboration=settings.trust_w_corroboration,
        w_extraction=settings.trust_w_extraction,
    )

    _retrieval = ParallelRetrievalOrchestrator(
        s6_client=s6,
        s7_client=s7,
        s3_client=s3,
        s1_client=s1,
        timeout=settings.upstream_timeout_seconds,
        # S-004: s1_internal_token is SecretStr — extract raw value for the
        # downstream orchestrator which expects a plain str.
        s1_internal_token=settings.s1_internal_token.get_secret_value(),
        trust_scorer=_trust_scorer,
        circuit_breakers={
            name: SourceCircuitBreaker(
                valkey_client,
                name,
                failure_threshold=settings.cb_failure_threshold,
                failure_window_seconds=settings.cb_failure_window_seconds,
                cool_down_seconds=settings.cb_cool_down_seconds,
                probe_ttl_seconds=settings.cb_probe_ttl_seconds,
            )
            for name in [
                "chunk",
                "relations",
                "graph",
                "claims",
                "events",
                "contradictions",
                "financial",
                "portfolio",
            ]
        }
        if settings.cb_enabled
        else {},
    )

    from rag_chat.application.pipeline.chat_pipeline import ChatPipeline

    # PLAN-0067 W11-3: classifier/plan_builder/retrieval removed from ChatPipeline.
    # The tool-use path replaces static intent → retrieval dispatch. These collaborators
    # are still used by RetrieveOnlyUseCase (eval harness), wired below.
    pipeline = ChatPipeline(
        validator=_validator,
        rate_limiter=RateLimiter(valkey=valkey_client, limit=settings.rate_limit_per_tenant),
        cache=CompletionCache(valkey=valkey_client),
        get_thread=GetThreadUseCase(),
        s6_client=s6,
        hyde=_hyde,
        embedder=embedding_client,
        reranker=reranker,
        llm_chain=llm_chain,
        persistence=ChatPersistenceUseCase(),
        # E-8: Wire Layer 2 semantic injection classifier. When deepinfra_api_key
        # is absent, the classifier internally disables itself (returns SAFE).
        llm_classifier=_llm_classifier,
    )

    # BUG-1 FIX: Wire ToolExecutorFactory with all upstream ports so the 8 new
    # tool handlers (search_documents, get_entity_graph, traverse_graph, etc.)
    # execute against real S6/S7/S1 adapters instead of returning [] silently.
    # The s6/s7/s3/s1 instances are created above in this function scope.
    from rag_chat.application.pipeline.tool_executor import (
        ToolExecutorFactory,
        build_default_registry,
        validate_registry_parity,
    )
    from rag_chat.infrastructure.clients.brief_archive_read_adapter import BriefArchiveReadAdapter
    from rag_chat.infrastructure.clients.s3_brief_client import S3BriefClient
    from rag_chat.infrastructure.clients.s7_intelligence_client import S7IntelligenceClient
    from rag_chat.infrastructure.clients.s10_client import S10Client

    # S7IntelligenceClient calls S9-proxied intelligence endpoints (R14/R7 compliance).
    # WHY api_gateway_url (not s7_base_url): the intelligence endpoints go through S9
    # which applies auth and rate limiting. S7 direct URLs bypass those controls.
    s7_intel = S7IntelligenceClient(
        base_url=settings.api_gateway_url,
        timeout=settings.upstream_timeout_seconds,
    )

    # S3BriefClient: S9-proxied screener/movers/calendar endpoints (PLAN-0081 Wave A).
    # WHY api_gateway_url: all catalog endpoints go through S9 for auth + rate limiting.
    s3_brief = S3BriefClient(
        base_url=settings.api_gateway_url,
        timeout=settings.upstream_timeout_seconds,
    )

    # BriefArchiveReadAdapter: read-only adapter backed by read session factory (R27).
    # WHY read_factory from app.state: the factory was set up in the DB lifespan step
    # above. This adapter creates per-call read sessions without acquiring a UnitOfWork.
    brief_archive = BriefArchiveReadAdapter(read_factory=app.state.read_factory)

    # S10Client: S9-proxied alert endpoints (PLAN-0082 Wave A).
    # WHY api_gateway_url (not S10 direct): R14/R7 — all service-to-service calls go
    # through S9 for auth and rate limiting; S10 direct URLs bypass those controls.
    s10_client = S10Client(
        base_url=settings.api_gateway_url,
        timeout=settings.upstream_timeout_seconds,
    )

    # Expose s10_client on app.state so the proposal confirmation route can call it directly
    # (POST /v1/chat/proposals/{id}/confirm executes the write action without going through
    # ToolExecutor, which is per-request and not available at proposal-confirm time).
    app.state.s10_client = s10_client  # PLAN-0082 Wave B

    tool_registry = build_default_registry()

    # PLAN-0093 QA P0-1 — startup manifest ↔ handler parity check.
    # Fail-fast: ToolRegistryDriftError is intentionally NOT caught here so a
    # misconfigured deploy cannot serve traffic with a silent dormant tool
    # (this is the GraphEnricher follow-up: a tool listed in the YAML but
    # missing a handler would otherwise only surface mid-conversation when
    # the LLM tried to call it).
    from rag_chat.application.metrics.prometheus import rag_tool_registry_size

    _tool_registry_sizes = validate_registry_parity(tool_registry)
    rag_tool_registry_size.labels(kind="manifest").set(_tool_registry_sizes["manifest"])
    rag_tool_registry_size.labels(kind="handled").set(_tool_registry_sizes["handled"])
    # WHY local logger: _wire_orchestrator does not have the lifespan-scoped
    # ``log`` binding, so we obtain a module logger here.  structlog.get_logger
    # is the project-mandated entry point (R10 — never stdlib logging).
    get_logger("rag_chat.app").info(  # type: ignore[no-any-return]
        "tool_registry_loaded",
        manifest_count=_tool_registry_sizes["manifest"],
        handled_count=_tool_registry_sizes["handled"],
    )

    tool_executor_factory = ToolExecutorFactory(
        registry=tool_registry,
        s3=s3,
        s6=s6,
        s7=s7,
        s7_intel=s7_intel,
        s1=s1,
        s3_brief=s3_brief,
        brief_archive=brief_archive,
        s10=s10_client,
        timeout=settings.upstream_timeout_seconds,
    )
    app.state.tool_executor_factory = tool_executor_factory  # expose for tests / health checks

    # PLAN-0107: AgentBudget sourced from env (Settings) rather than dataclass
    # defaults so ops can tune the ReAct soft budgets per-environment without
    # redeploying. The dataclass defaults (90s / 3 errors) are kept as the
    # last-line fallback when Settings has not been touched. Other fields
    # (max_iterations, max_tokens_*) are still dataclass defaults — they are
    # less sensitive to env tuning and have not been observed limiting prod.
    from rag_chat.application.use_cases.chat_orchestrator import AgentBudget

    _agent_budget = AgentBudget(
        max_tool_latency_s=settings.chat_max_tool_latency_s,
        max_consecutive_errors=settings.chat_max_consecutive_errors,
    )
    orchestrator = ChatOrchestratorUseCase(
        pipeline=pipeline,
        tool_executor_factory=tool_executor_factory,
        budget=_agent_budget,
        # E-12: pass write_factory so ChatAuditLogger can flush to chat_audit_log.
        write_factory=app.state.write_factory,
    )
    app.state.chat_orchestrator = orchestrator
    app.state.chat_pipeline = pipeline  # expose for PLAN-0074 Wave F + PLAN-0067 W11-3
    app.state.llm_chain = llm_chain
    # D-006: expose CBs on app.state so _reconcile_cb_gauges() can sync Prometheus
    # gauges with Valkey CB state on startup (avoids false-healthy gauge after restart).
    app.state.circuit_breakers = _retrieval._cbs

    from rag_chat.application.use_cases.retrieve_only import RetrieveOnlyUseCase

    app.state.retrieve_only_uc = RetrieveOnlyUseCase(
        validator=_validator,
        s6_client=s6,
        classifier=classifier,
        plan_builder=_plan_builder,
        hyde=_hyde,
        embedder=embedding_client,
        retrieval=_retrieval,
    )


def _wire_briefing_uc(app: FastAPI, settings: RagChatSettings, valkey_client: ValkeyClient) -> None:
    """Build and attach GenerateBriefingUseCase (with BriefingContextGatherer) to app.state.

    Creates separate client instances for the BriefingContextGatherer rather than
    re-using the ChatOrchestratorUseCase's clients.  WHY separate: the orchestrator clients
    were created inside _wire_orchestrator() without being stored on app.state, so
    they are not accessible here.  Creating new instances is lightweight (no persistent
    connections — httpx clients open connections lazily per-request).
    """
    from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.infrastructure.clients.brief_archive_write_adapter import BriefArchiveWriteAdapter
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

    # PLAN-0102 W3 follow-up (T-W3-FU-01): wire the new tape + earnings
    # adapters. Both target the same market-data base URL as S3Client
    # (s3_base_url already points at market-data) so we re-use it rather
    # than introducing a new config key for a single host.
    from rag_chat.infrastructure.clients.earnings_calendar_client import EarningsCalendarClient
    from rag_chat.infrastructure.clients.market_tape_client import MarketTapeClient

    market_tape_client = MarketTapeClient(base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds)
    earnings_calendar_client = EarningsCalendarClient(
        base_url=settings.s3_base_url, timeout=settings.upstream_timeout_seconds
    )

    context_gatherer = BriefingContextGatherer(
        s1=s1,
        s3=s3,
        s5=s5,
        s6=s6,
        s7=s7,
        market_tape=market_tape_client,
        earnings_calendar=earnings_calendar_client,
    )

    # D-R4-004 (PLAN-0087, 2026-05-09): brief_archive was previously NOT
    # supplied to GenerateBriefingUseCase, so the use case used a
    # NullBriefArchive — no rows ever written to user_briefs.  Net effect:
    # entire PLAN-0066 brief history / diff / feedback feature dark.
    # Wire the write-adapter now using the existing write_factory so generated
    # briefs persist for history + feedback widgets.
    brief_archive = BriefArchiveWriteAdapter(write_factory=app.state.write_factory)

    app.state.briefing_uc = GenerateBriefingUseCase(
        llm_chain=app.state.llm_chain,  # same chain as ChatOrchestratorUseCase
        valkey=valkey_client,
        context_gatherer=context_gatherer,
        brief_archive=brief_archive,
    )


def _wire_entity_context_uc(app: FastAPI, settings: RagChatSettings) -> None:
    """Build and attach EntityContextChatUseCase to app.state (PLAN-0074 Wave F).

    Creates an EntityContextClient pointed at S7 (kg_internal_base_url) and
    injects it plus the existing chat orchestrator into EntityContextChatUseCase.

    WHY separate function: follows the same pattern as _wire_briefing_uc — keeps
    lifespan() clean and each wiring concern isolated in its own function.

    WHY reuse app.state.chat_orchestrator: EntityContextChatUseCase delegates the
    full tool-use pipeline to the existing orchestrator. Creating a second orchestrator
    would duplicate all LLM provider, reranker, and S6/S7 client instances.
    """
    from rag_chat.application.use_cases.run_entity_context_chat import EntityContextChatUseCase
    from rag_chat.infrastructure.clients.entity_context_client import EntityContextClient

    entity_context_client = EntityContextClient(base_url=settings.kg_internal_base_url)

    app.state.entity_context_chat_uc = EntityContextChatUseCase(
        entity_context_loader=entity_context_client,
        chat_orchestrator=app.state.chat_orchestrator,
    )


def _wire_citation_cron(
    app: FastAPI,
    settings: RagChatSettings,
    read_factory: Any,
    log: Any,
) -> None:
    """Build and start the citation-accuracy cron task (PLAN-0084 A-1 T-A-1-05).

    Only called when ``settings.citation_cron_enabled`` is True.  The task is
    attached to ``app.state.citation_cron_task`` so the lifespan shutdown can
    cancel it cleanly.

    Provider selection (L4):
    - "deepinfra" → ``DeepInfraCompletionAdapter`` (requires deepinfra_api_key)
    - "ollama"    → ``OllamaCompletionAdapter`` (local; good for dev)

    R23: ``SqlAlchemyMessageRepository`` receives the *read_factory* (read replica
    session maker) because ``sample_recent_with_citations`` is read-only.
    """
    # QA-003: The function checks the flag itself so callers don't need to guard.
    # This avoids the trivial test anti-pattern: `if flag: call(); assert_not_called()`.
    if not settings.citation_cron_enabled:
        return

    from rag_chat.application.use_cases.score_citation_accuracy import ScoreCitationAccuracyUseCase
    from rag_chat.infrastructure.db.repositories.message_repository import SqlAlchemyMessageRepository
    from rag_chat.infrastructure.jobs.citation_accuracy_cron import start_citation_accuracy_cron
    from rag_chat.infrastructure.llm.citation_judge_adapter import CitationJudgeAdapter

    # Resolve provider client (L4).
    _deepinfra_api_key = settings.deepinfra_api_key.get_secret_value() if settings.deepinfra_api_key else None

    # rag-chat-ml-metrics: judge runs on the daily cron — wiring the metrics
    # here makes the judge's request rate / failure rate / model latency
    # visible on the same ``rag_chat_ml_api_*`` series the dashboard queries.
    from rag_chat.application.metrics.ml_clients import build_ml_metrics

    _judge_metrics = build_ml_metrics(settings.service_name)

    if settings.citation_judge_provider == "deepinfra" and _deepinfra_api_key:
        from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter

        # A-006: use settings.citation_judge_model (default: Meta-Llama-3.1-8B-Instruct)
        # instead of the heavier completion_model — the judge only needs a single digit
        # response and the 8B model is ~10x cheaper than the 235B completion model.
        provider_client: Any = DeepInfraCompletionAdapter(
            api_key=_deepinfra_api_key,
            model=settings.citation_judge_model,  # RAG_CHAT_CITATION_JUDGE_MODEL
            metrics=_judge_metrics,
        )
    else:
        # Ollama fallback (or explicit citation_judge_provider="ollama").
        from rag_chat.infrastructure.llm.ollama_adapter import OllamaCompletionAdapter

        provider_client = OllamaCompletionAdapter(
            base_url=settings.ollama_base_url,
            model=settings.ollama_completion_model,
            metrics=_judge_metrics,
        )
        if settings.citation_judge_provider == "deepinfra" and not _deepinfra_api_key:
            log.warning(  # type: ignore[no-any-return]
                "citation_cron_deepinfra_key_missing_falling_back_to_ollama",
            )

    # Build adapter + use case.
    judge = CitationJudgeAdapter(
        provider_client,
        timeout_s=settings.citation_call_timeout_s,
        metrics=_judge_metrics,
        # PLAN-0107 follow-up: route judge calls through the shared CostRecorder.
        # call_site label = "citation_judge"; thread_id=None (batch cron job).
        cost_recorder=app.state.cost_recorder,
    )

    # R23: message repository uses read_factory (read-only session).
    # We create a thin subclass that manages the session lifecycle per-call
    # so the repository doesn't hold an open session across cron sleeps.
    class _ReadSessionRepo(SqlAlchemyMessageRepository):
        """Message repo that opens a fresh read-replica session for each call."""

        def __init__(self, session_factory: Any) -> None:
            self._session_factory = session_factory

        async def sample_recent_with_citations(  # type: ignore[override]
            self,
            n: int,
            # MN-7: tightened from `Any` to `datetime | None` to surface
            # callers that forget the kwarg at type-check time. The SQL
            # adapter now raises if `since is None`, so this annotation is
            # informational — runtime enforcement lives in the adapter.
            since: datetime | None = None,
        ) -> list:
            session = self._session_factory()
            try:
                repo = SqlAlchemyMessageRepository(session)
                return await repo.sample_recent_with_citations(n, since=since)
            finally:
                await session.close()

        async def create(self, message: Any) -> None:  # type: ignore[override]
            raise NotImplementedError("_ReadSessionRepo is read-only")

        async def list_by_thread(self, thread_id: Any, limit: int) -> list:  # type: ignore[override]
            raise NotImplementedError("_ReadSessionRepo is read-only")

    message_repo = _ReadSessionRepo(read_factory)

    use_case = ScoreCitationAccuracyUseCase(
        message_repo=message_repo,
        llm_judge=judge,
        min_samples=settings.citation_min_samples,
        run_budget_s=settings.citation_run_budget_s,
    )

    task = start_citation_accuracy_cron(use_case)
    app.state.citation_cron_task = task

    # BP-268 done-callback: surface crashes to the log instead of silently
    # swallowing them (mirror of BaseKafkaConsumer._on_retry_task_done).
    def _on_done(t: asyncio.Task[None]) -> None:
        if t.cancelled():
            # Normal shutdown — cancelled by lifespan teardown.
            return
        exc = t.exception()
        if exc is not None:
            log.critical("citation_cron_task_crashed", exc_info=exc)  # type: ignore[no-any-return]

    task.add_done_callback(_on_done)

    log.info(  # type: ignore[no-any-return]
        "citation_cron_started",
        provider=settings.citation_judge_provider,
        timeout_s=settings.citation_call_timeout_s,
    )


# ─── Deploy-version cache flush (PLAN-0097 W4 T-W4-04) ───────────────────────

# Valkey key remembering the last-seen RAG_CACHE_DEPLOY_TOKEN. Versioned with
# the same ``rag:v1:`` prefix as the rest of the rag-chat keyspace.
_DEPLOY_TOKEN_KEY = "rag:v1:cache:deploy_token"  # noqa: S105 — Valkey key, not a credential

# Pattern matching every completion-cache entry across cache-key versions.
# ``rag:v3:completion:*`` is the current keyspace (completion_cache.py); the
# ``v*`` wildcard also rescues stale keys from any previous major-version bump
# that may still be sitting in Valkey.
_COMPLETION_CACHE_PATTERN = "rag:v*:completion:*"


async def _maybe_flush_completion_cache(
    valkey_client: ValkeyClient,
    deploy_token: str,
    log: Any,
) -> None:
    """Flush stale completion-cache entries when the deploy token changes.

    Contract (PLAN-0097 W4 T-W4-04):
      • ``deploy_token == ""``           → feature disabled, no-op.
      • Stored token == ``deploy_token`` → cache still valid, no-op.
      • Stored token != ``deploy_token`` (or unset) → call
        ``valkey.delete_pattern("rag:v*:completion:*")`` to drop every
        completion-cache entry, then persist the new token.

    All Valkey errors are swallowed and logged at WARNING — a Valkey outage
    must never block service startup. Worst case: stale cache lingers until
    the next successful startup with this hook + a token change.
    """
    if not deploy_token:
        # Disabled — operator has not opted in. Nothing to do.
        return

    try:
        previous = await valkey_client.get(_DEPLOY_TOKEN_KEY)
    except Exception as exc:
        log.warning(  # type: ignore[no-any-return]
            "deploy_token_read_failed",
            error=type(exc).__name__,
            message="skipping cache flush — Valkey GET on deploy-token key failed",
        )
        return

    if previous == deploy_token:
        # Token unchanged — cache is still semantically valid.
        log.debug(  # type: ignore[no-any-return]
            "deploy_token_unchanged",
            token=deploy_token,
        )
        return

    # Token changed (or first observation) — flush + persist.
    try:
        removed = await valkey_client.delete_pattern(_COMPLETION_CACHE_PATTERN)
    except Exception as exc:
        log.warning(  # type: ignore[no-any-return]
            "completion_cache_flush_failed",
            error=type(exc).__name__,
            previous=previous,
            new=deploy_token,
            message="cache flush aborted — Valkey SCAN/DEL failed",
        )
        return

    try:
        await valkey_client.set(_DEPLOY_TOKEN_KEY, deploy_token)
    except Exception as exc:
        log.warning(  # type: ignore[no-any-return]
            "deploy_token_persist_failed",
            error=type(exc).__name__,
            new=deploy_token,
            message=(
                "cache flushed but token not persisted; next startup will flush "
                "again (idempotent but wastes one cache warmup)"
            ),
        )
        return

    log.info(  # type: ignore[no-any-return]
        "completion_cache_flushed_on_deploy",
        previous=previous,
        new=deploy_token,
        removed=removed,
    )


async def _reconcile_cb_gauges(app: FastAPI) -> None:
    """D-006: Sync Prometheus CB gauges with actual Valkey CB state on startup.

    Called once in the lifespan startup after ``_wire_orchestrator`` has
    populated ``app.state.circuit_breakers``.  Without this, a restart after a
    CB trip shows gauge=0 (healthy) while the CB is actually open in Valkey —
    the state key persists with a TTL across restarts.

    Best-effort: if ``circuit_breakers`` is not set (e.g. ``cb_enabled=False``),
    or if any reconcile call fails, errors are swallowed.
    """
    cbs = getattr(app.state, "circuit_breakers", None) or {}
    for cb in cbs.values():
        await cb.reconcile_gauge()


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
    app.include_router(internal_router.router)
    app.include_router(internal_ai_brief_flag_router.router)  # PLAN-0089 Wave L-5a
    app.include_router(proposal_router.router)  # PLAN-0082 Wave B: proposal confirmation

    return app
