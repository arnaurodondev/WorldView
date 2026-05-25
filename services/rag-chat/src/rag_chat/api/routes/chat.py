"""Chat API routes - POST /api/v1/chat, POST /api/v1/chat/stream, and
POST /api/v1/chat/entity-context (PLAN-0074 Wave F, T-F-02).

R25: Routes import only from application layer (never from infrastructure/).
R27: Write UoW used for chat (persistence writes).
R14: Frontend never calls S8 directly — entity-context endpoint is proxied by S9 (Wave G).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from rag_chat.api.dependencies import AuthContextDep, UoWDep, make_write_uow
from rag_chat.api.schemas import (
    ChatRequestSchema,
    ChatResponse,
    EntityContextChatRequest,
    EntityContextChatResponse,
)
from rag_chat.domain.errors import (
    InsufficientRetrievalError,
    PIIDetectedError,
    PromptInjectionError,
    ProviderUnavailableError,
    RateLimitExceededError,
    ThreadNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

router = APIRouter(prefix="/api/v1", tags=["chat"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _get_orchestrator(request: Request) -> Any:
    """Retrieve ChatOrchestratorUseCase from app state."""
    return request.app.state.chat_orchestrator


def _get_entity_context_uc(request: Request) -> Any:
    """Retrieve EntityContextChatUseCase from app state.

    WHY separate helper: keeps the route handler thin and makes the
    state attribute name explicit — matching _wire_entity_context_uc() in app.py.
    """
    return request.app.state.entity_context_chat_uc


@router.post("/chat", status_code=200)
async def chat(
    request_body: ChatRequestSchema,
    request: Request,
    auth: AuthContextDep,
    uow: UoWDep,
) -> ChatResponse:
    """Synchronous chat endpoint — returns the full response at once."""
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    tenant_id, user_id = auth

    # WHY set_current_jwt here: InternalJWTMiddleware sets the ContextVar when it
    # validates the incoming JWT, but the ContextVar can be empty by the time async
    # tool handlers (e.g. S7Client.get_contradictions) call BaseUpstreamClient._get(),
    # causing outbound X-Internal-JWT to be missing and downstream services to 401.
    # Explicitly setting the ContextVar here mirrors the canonical pattern used by
    # entity_context_chat() and public_briefings (FIX-LIVE-K+L).
    from rag_chat.infrastructure.clients.auth_context import set_current_jwt

    set_current_jwt(request.headers.get("X-Internal-JWT"))

    chat_req = ChatRequest(
        message=request_body.message,
        context=ChatContext(entity_ids=tuple(request_body.entity_ids)),
        tenant_id=tenant_id,
        user_id=user_id,
        thread_id=request_body.thread_id,
    )

    orchestrator = _get_orchestrator(request)

    try:
        result = await orchestrator.execute_sync(chat_req, uow)
        return ChatResponse(
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            contradictions=result.get("contradictions", []),
            thread_id=result.get("thread_id"),
            message_id=result.get("message_id"),
            intent=result.get("intent"),
            provider=result.get("provider"),
            latency_ms=result.get("latency_ms"),
        )
    except RateLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except (PIIDetectedError, PromptInjectionError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ThreadNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InsufficientRetrievalError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/chat/stream")
async def chat_stream(
    request_body: ChatRequestSchema,
    request: Request,
    auth: AuthContextDep,
    # WHY NO UoWDep HERE: FastAPI closes yield dependencies when the route function
    # returns. EventSourceResponse iterates the generator AFTER return — meaning the
    # UoW dependency is already torn down before persistence fires in execute_streaming,
    # causing "RagUnitOfWork not entered" (AssertionError). Fix: create a UoW whose
    # lifetime is scoped to the generator, not the route function. (Bug 2)
) -> Any:
    """SSE streaming chat endpoint.

    Returns Content-Type: text/event-stream with events:
      status, token, citations, contradictions, metadata, error
    """
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    tenant_id, user_id = auth

    # WHY set_current_jwt here: same rationale as POST /api/v1/chat — the JWT
    # ContextVar must be populated before any async tool handler invokes
    # BaseUpstreamClient, otherwise the outbound X-Internal-JWT header is missing
    # and downstream calls (S6/S7) return 401. Mirrors entity_context_chat() and
    # public_briefings (FIX-LIVE-K+L).
    from rag_chat.infrastructure.clients.auth_context import set_current_jwt

    set_current_jwt(request.headers.get("X-Internal-JWT"))

    chat_req = ChatRequest(
        message=request_body.message,
        context=ChatContext(entity_ids=tuple(request_body.entity_ids)),
        tenant_id=tenant_id,
        user_id=user_id,
        thread_id=request_body.thread_id,
    )

    orchestrator = _get_orchestrator(request)

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    emitter = SSEEmitter()

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        # WHY make_write_uow() instead of UoWDep: FastAPI closes yield-based
        # dependencies when the route function returns. EventSourceResponse iterates
        # the generator AFTER return — the UoW would already be torn down before
        # execute_streaming() persists ("RagUnitOfWork not entered", AssertionError).
        # make_write_uow() is a factory from dependencies.py (application layer) that
        # defers the infrastructure import — R25 compliant; no import from infrastructure/
        # at module level or inside this route file.  (DEF-026)
        async with make_write_uow(request) as uow:
            try:
                async for event in orchestrator.execute_streaming(chat_req, uow):
                    yield event
            except RateLimitExceededError as e:
                yield emitter.emit_error("RATE_LIMIT_EXCEEDED", str(e))
            except (PIIDetectedError, PromptInjectionError) as e:
                yield emitter.emit_error("INPUT_REJECTED", str(e))
            except ProviderUnavailableError as e:
                yield emitter.emit_error("PROVIDER_UNAVAILABLE", str(e))
            except Exception as e:
                log.error("stream_internal_error", error=type(e).__name__)  # type: ignore[no-any-return]
                yield emitter.emit_error("INTERNAL_ERROR", "An internal error occurred")

    return EventSourceResponse(event_generator())


@router.post("/chat/entity-context", status_code=200)
async def entity_context_chat(
    request_body: EntityContextChatRequest,
    request: Request,
    auth: AuthContextDep,
    uow: UoWDep,
) -> EntityContextChatResponse:
    """Synchronous entity-context chat endpoint (PLAN-0074 Wave F).

    Loads entity intelligence from S7, prepends a grounding system-prompt prefix,
    and delegates to the standard chat pipeline. Returns the full answer once complete.

    R14: This endpoint is meant to be proxied by S9 (Wave G); the frontend never
    calls S8 directly.

    Error handling mirrors POST /api/v1/chat for consistency:
      429 — rate limit exceeded
      400 — PII detected or injection heuristic fired
      404 — thread not found
      422 — insufficient retrieval context
      503 — all LLM providers unavailable
    """
    tenant_id, user_id = auth

    # WHY X-Internal-JWT from request headers: EntityContextClient forwards this token
    # to S7's InternalJWTMiddleware (PRD-0025). The token was already validated by our
    # own InternalJWTMiddleware before this route executes, so re-reading it from the
    # header is safe. R25 compliance: no infrastructure import in the route file.
    jwt_token: str = request.headers.get("X-Internal-JWT", "")

    use_case = _get_entity_context_uc(request)

    try:
        result = await use_case.execute_sync(
            entity_id=request_body.entity_id,
            question=request_body.question,
            tenant_id=tenant_id,
            user_id=user_id,
            jwt_token=jwt_token,
            thread_id=request_body.conversation_id,
            include_graph_context=request_body.include_graph_context,
            uow=uow,
        )
        return EntityContextChatResponse(
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            contradictions=result.get("contradictions", []),
            thread_id=result.get("thread_id"),
            message_id=result.get("message_id"),
            intent=result.get("intent"),
            provider=result.get("provider"),
            latency_ms=result.get("latency_ms"),
        )
    except RateLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except (PIIDetectedError, PromptInjectionError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ThreadNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InsufficientRetrievalError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/chat/entity-context/stream")
async def entity_context_chat_stream(
    request_body: EntityContextChatRequest,
    request: Request,
    auth: AuthContextDep,
) -> Any:
    """SSE streaming entity-context chat endpoint (PLAN-0074 Wave F).

    Same as /api/v1/chat/entity-context but streams tokens as SSE events.
    SSE event format is identical to POST /api/v1/chat/stream.

    WHY no UoWDep: same reason as /chat/stream — FastAPI closes yield-based deps
    when the route function returns, before the SSE generator iterates.
    Use make_write_uow() inside the generator instead (DEF-026 pattern).
    """
    tenant_id, user_id = auth
    # See entity_context_chat() for why we read X-Internal-JWT from the header.
    jwt_token: str = request.headers.get("X-Internal-JWT", "")

    use_case = _get_entity_context_uc(request)

    from rag_chat.application.pipeline.sse_emitter import SSEEmitter

    emitter = SSEEmitter()

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        # WHY make_write_uow(): see /chat/stream for full explanation (DEF-026).
        async with make_write_uow(request) as uow:
            try:
                async for event in use_case.execute_streaming(
                    entity_id=request_body.entity_id,
                    question=request_body.question,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    jwt_token=jwt_token,
                    thread_id=request_body.conversation_id,
                    include_graph_context=request_body.include_graph_context,
                    uow=uow,
                ):
                    yield event
            except RateLimitExceededError as e:
                yield emitter.emit_error("RATE_LIMIT_EXCEEDED", str(e))
            except (PIIDetectedError, PromptInjectionError) as e:
                yield emitter.emit_error("INPUT_REJECTED", str(e))
            except ProviderUnavailableError as e:
                yield emitter.emit_error("PROVIDER_UNAVAILABLE", str(e))
            except Exception as e:
                log.error("entity_context_stream_internal_error", error=type(e).__name__)  # type: ignore[no-any-return]
                yield emitter.emit_error("INTERNAL_ERROR", "An internal error occurred")

    return EventSourceResponse(event_generator())
