"""Internal-only API routes consumed by the eval harness (PLAN-0063 W5-1-00).

POST /v1/internal/retrieve runs the chat retrieval pipeline up to (and stopping
at) the ranked-candidate stage — no fusion, no reranking, no LLM call. It is
NOT proxied through S9; only services with a valid internal JWT can reach it.

R25: Routes import only from application layer. The use case lives at
rag_chat.application.use_cases.retrieve_only.RetrieveOnlyUseCase.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from rag_chat.api.dependencies import AuthContextDep

router = APIRouter(prefix="/v1/internal", tags=["internal"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class RetrieveRequest(BaseModel):
    """Request body for POST /v1/internal/retrieve.

    Either query_text or query_embedding must be provided. When both are set,
    the embedding takes precedence (skips HyDE + the embedder call) — this is
    the path the CI eval workflow uses with precomputed embeddings (L5).
    """

    query_text: str = Field(..., min_length=1, max_length=2000)
    query_embedding: list[float] | None = Field(default=None, min_length=64, max_length=4096)
    top_k: int = Field(default=20, ge=1, le=100)


class CandidateOut(BaseModel):
    """One ranked retrieval candidate returned by /v1/internal/retrieve."""

    chunk_id: str
    doc_id: str | None
    rank: int
    score: float
    item_type: str
    source_type: str | None
    snippet: str


class RetrieveResponse(BaseModel):
    """Response body for POST /v1/internal/retrieve."""

    query_text: str
    intent: str
    candidates: list[CandidateOut]
    n_candidates: int


def _get_uc(request: Request) -> Any:
    uc = getattr(request.app.state, "retrieve_only_uc", None)
    if uc is None:
        raise HTTPException(status_code=503, detail="retrieve_only use case not wired")
    return uc


@router.post("/retrieve", status_code=200, response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    request: Request,
    auth: AuthContextDep,
) -> RetrieveResponse:
    """Run pre-fusion retrieval and return top-k ranked candidates.

    Auth: requires a valid internal JWT (any tenant + user; system role also
    accepted via InternalJWTMiddleware).
    """
    from rag_chat.domain.entities.chat import ChatContext, ChatRequest

    tenant_id, user_id = auth
    chat_req = ChatRequest(
        message=body.query_text,
        context=ChatContext(),
        tenant_id=tenant_id,
        user_id=user_id,
    )

    uc = _get_uc(request)
    try:
        result = await uc.execute(
            chat_req,
            query_embedding=body.query_embedding,
            top_k=body.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.error("retrieve_only_failed", error=type(exc).__name__, message=str(exc))
        raise HTTPException(status_code=500, detail="retrieval failed") from exc

    candidates: list[CandidateOut] = []
    for rank, item in enumerate(result.candidates, start=1):
        candidates.append(
            CandidateOut(
                chunk_id=str(item.item_id),
                doc_id=str(item.doc_id) if item.doc_id else None,
                rank=rank,
                score=float(item.score),
                item_type=item.item_type.value,
                source_type=(item.citation_meta.source_name if item.citation_meta is not None else None),
                snippet=(item.text[:300] if item.text else ""),
            )
        )

    return RetrieveResponse(
        query_text=body.query_text,
        intent=result.intent,
        candidates=candidates,
        n_candidates=len(candidates),
    )
