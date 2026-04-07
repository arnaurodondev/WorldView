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
)
from rag_chat.application.use_cases.create_thread import CreateThreadUseCase
from rag_chat.application.use_cases.delete_thread import DeleteThreadUseCase
from rag_chat.application.use_cases.get_thread import GetThreadUseCase
from rag_chat.application.use_cases.list_threads import ListThreadsUseCase
from rag_chat.domain.errors import ThreadNotFoundError

if TYPE_CHECKING:
    from rag_chat.domain.entities.conversation import Citation, ConversationThread, Message

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


def _msg_to_response(msg: Message) -> MessageResponse:
    return MessageResponse(
        message_id=msg.message_id,
        role=msg.role.value,
        content=msg.content,
        intent=msg.intent.value if msg.intent else None,
        citations=[_citation_to_dict(c) for c in msg.citations],
        created_at=msg.created_at,
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
