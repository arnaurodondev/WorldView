"""Thread CRUD API routes — POST/GET/DELETE /api/v1/threads (T-D-4-02).

R25: routes MUST NOT import from infrastructure/; all reads and writes
go through use case classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from rag_chat.api.dependencies import AuthContextDep, ReadUoWDep, UoWDep
from rag_chat.api.schemas import (
    CreateThreadRequest,
    CreateThreadResponse,
    DeleteThreadResponse,
    MessageResponse,
    PaginatedThreadsResponse,
    ThreadDetailResponse,
    ThreadSummaryResponse,
    UpdateThreadRequest,
)
from rag_chat.application.use_cases.create_thread import CreateThreadUseCase
from rag_chat.application.use_cases.delete_thread import DeleteThreadUseCase
from rag_chat.application.use_cases.get_thread import GetThreadUseCase
from rag_chat.application.use_cases.list_threads import ListThreadsUseCase
from rag_chat.application.use_cases.update_thread import UpdateThreadUseCase
from rag_chat.domain.errors import ThreadNotFoundError

if TYPE_CHECKING:
    from rag_chat.domain.entities.chat import ResolvedEntity
    from rag_chat.domain.entities.conversation import Citation, ContradictionRef, ConversationThread, Message

router = APIRouter(prefix="/api/v1/threads", tags=["threads"])


# ── Conversion helpers ────────────────────────────────────────────────────────


def _citation_to_dict(c: Citation) -> dict[str, Any]:
    return {
        "ref": c.ref,
        "item_type": c.item_type,
        "id": c.id,
        "title": c.title,
        "url": c.url,
        "source_name": c.source_name,
        "entity_name": c.entity_name,
        "confidence": c.confidence,
    }


def _contradiction_to_dict(c: ContradictionRef) -> dict[str, Any]:
    """Serialise a ContradictionRef domain value-object to a plain dict.

    WHY keep this in the route layer: the domain object must not know about
    API serialisation concerns (R25 / domain layer independence).
    """
    return {
        "claim_type": c.claim_type,
        "strength": c.strength,
        "sides": list(c.sides),
    }


def _resolved_entity_to_dict(e: ResolvedEntity) -> dict[str, Any]:
    """Serialise a ResolvedEntity domain value-object to a plain dict."""
    return {
        "entity_id": str(e.entity_id),
        "canonical_name": e.canonical_name,
        "entity_type": e.entity_type,
        "confidence": e.confidence,
        "matched_text": e.matched_text,
        "ticker": e.ticker,
    }


def _msg_to_response(msg: Message) -> MessageResponse:
    """Convert a domain Message to a wire-format MessageResponse.

    Q-9: populates the extended observability fields (provider, model,
    latency_ms, resolved_entities, retrieval_plan, contradictions).
    Legacy rows have these as None — the response fields default to None
    so no breakage occurs (R11 forward-compatibility).
    """
    return MessageResponse(
        message_id=msg.message_id,
        role=msg.role.value,
        content=msg.content,
        intent=msg.intent.value if msg.intent else None,
        citations=[_citation_to_dict(c) for c in msg.citations],
        created_at=msg.created_at,
        # Q-9 extended fields — pass through directly from the domain entity.
        provider=msg.provider,
        model=msg.model,
        latency_ms=msg.latency_ms,
        # Convert domain tuples to list[dict] for JSON serialisation;
        # keep as None (not []) when the tuple is empty to signal "never set".
        resolved_entities=(
            [_resolved_entity_to_dict(e) for e in msg.resolved_entities] if msg.resolved_entities else None
        ),
        # retrieval_plan is stored as raw JSONB; the domain entity carries it
        # as None (no dedicated domain type yet — stored/returned as-is).
        retrieval_plan=None,  # not yet surfaced on the domain Message entity
        contradictions=(
            [_contradiction_to_dict(c) for c in msg.contradiction_refs] if msg.contradiction_refs else None
        ),
    )


def _thread_to_summary(thread: ConversationThread) -> ThreadSummaryResponse:
    last_msg_at = thread.messages[-1].created_at if thread.messages else None
    return ThreadSummaryResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        last_msg_at=last_msg_at,
        message_count=len(thread.messages),
        entity_ids=list(thread.entity_ids),
        created_at=thread.created_at,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=CreateThreadResponse, status_code=status.HTTP_201_CREATED)
async def create_thread(
    body: CreateThreadRequest,
    uow: UoWDep,
    auth: AuthContextDep,
) -> CreateThreadResponse:
    """Create a new conversation thread."""
    tenant_id, user_id = auth
    uc = CreateThreadUseCase()
    thread = await uc.execute(
        uow,
        user_id=user_id,
        tenant_id=tenant_id,
        title=body.title,
        entity_ids=body.entity_ids,
    )
    return CreateThreadResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        created_at=thread.created_at,
    )


@router.get("", response_model=PaginatedThreadsResponse)
async def list_threads(
    uow: ReadUoWDep,
    auth: AuthContextDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedThreadsResponse:
    """List active threads for the authenticated user (archived excluded)."""
    tenant_id, user_id = auth
    uc = ListThreadsUseCase()
    threads, total = await uc.execute(uow, user_id=user_id, tenant_id=tenant_id, limit=limit, offset=offset)
    return PaginatedThreadsResponse(
        threads=[_thread_to_summary(t) for t in threads],
        total=total,
    )


@router.get("/{thread_id}", response_model=ThreadDetailResponse)
async def get_thread(
    thread_id: UUID,
    uow: ReadUoWDep,
    auth: AuthContextDep,
) -> ThreadDetailResponse:
    """Fetch a single thread with its full message history."""
    tenant_id, user_id = auth
    uc = GetThreadUseCase()
    try:
        thread = await uc.execute(uow, thread_id=thread_id, user_id=user_id, tenant_id=tenant_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ThreadDetailResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        created_at=thread.created_at,
        messages=[_msg_to_response(m) for m in thread.messages],
    )


@router.delete("/{thread_id}", response_model=DeleteThreadResponse)
async def delete_thread(
    thread_id: UUID,
    uow: UoWDep,
    auth: AuthContextDep,
) -> DeleteThreadResponse:
    """Soft-delete a thread (sets archived_at; thread is no longer listed)."""
    tenant_id, user_id = auth
    uc = DeleteThreadUseCase()
    try:
        archived_at = await uc.execute(uow, thread_id=thread_id, user_id=user_id, tenant_id=tenant_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeleteThreadResponse(thread_id=thread_id, archived_at=archived_at)


@router.patch("/{thread_id}", response_model=ThreadDetailResponse)
async def update_thread(
    thread_id: UUID,
    body: UpdateThreadRequest,
    uow: UoWDep,
    auth: AuthContextDep,
) -> ThreadDetailResponse:
    """Patch mutable thread fields — currently only ``title``.

    PLAN-0051 Wave E / T-E-5-06: lets the chat UI rename a thread when the
    user double-clicks the sidebar title and edits inline. Returns the full
    ThreadDetailResponse so the frontend can swap the cached entry without
    a follow-up GET.

    Auth: ownership enforced atomically inside ``update_title`` (single
    UPDATE filtered by user_id + tenant_id).
    """
    tenant_id, user_id = auth
    uc = UpdateThreadUseCase()
    try:
        thread = await uc.execute(
            uow,
            thread_id=thread_id,
            user_id=user_id,
            tenant_id=tenant_id,
            title=body.title,
        )
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ThreadDetailResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        created_at=thread.created_at,
        messages=[_msg_to_response(m) for m in thread.messages],
    )
