"""Chat API routes - POST /api/v1/chat and POST /api/v1/chat/stream (T-F-4-03).

R25: Routes import only from application layer (never from infrastructure/).
R27: Write UoW used for chat (persistence writes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from rag_chat.api.dependencies import AuthContextDep, UoWDep, make_write_uow
from rag_chat.api.schemas import ChatRequestSchema, ChatResponse
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
    """Retrieve ChatOrchestrator from app state."""
    return request.app.state.chat_orchestrator


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
