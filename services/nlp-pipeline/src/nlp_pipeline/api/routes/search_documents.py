"""Full-text document search endpoint — GET /api/v1/search/documents (PLAN-0064 W6).

Wave 1 stub: validates query params and returns 501 Not Implemented.
Wave 3 wires in the real SearchDocumentsUseCase.

WHY GET (not POST): GET is cache-friendly and bookmark-able — search results should
be shareable via URL. FastAPI parses repeated `entity_id=uuid1&entity_id=uuid2` into
list[UUID] natively, so we don't need a POST body to send multiple entity filters.

WHY 501 and not 200: returning a 501 makes it explicit to callers that the full
implementation is not yet live. Any client that ignores 5xx status codes and tries
to render partial results would show an empty list, which is a safe degradation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["search"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


@router.get("/search/documents")
async def search_documents(
    q: str = Query(..., min_length=1, max_length=500),
    entity_id: list[UUID] | None = Query(None),
    scope: str = Query("all"),
    source_type: str = Query("all"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    date_preset: str | None = Query(None),
    page: int = Query(1, ge=1, le=40),
    page_size: int = Query(25, ge=1, le=100),
) -> Any:
    """FTS document search across articles + EDGAR filings with entity facets.

    Wave 1 stub — returns 501 until Wave 3 wires the use case.

    Query params:
        q           : Required. Parsed via websearch_to_tsquery (Wave 3).
                      Supports quoted phrases and OR / - operators.
        entity_id   : Optional, repeatable UUID filter. Wave 3 treats multiple
                      values as OR-within-document (any mention qualifies).
        scope       : "watchlist" | "portfolio" | "all" (default "all").
                      Wave 3 resolves watchlist/portfolio entity sets server-side.
        source_type : "news" | "sec_edgar" | "all" (default "all").
                      "transcript" is intentionally absent (not yet ingested).
        date_from   : ISO 8601 datetime lower bound on published_at.
        date_to     : ISO 8601 datetime upper bound on published_at.
        date_preset : "since_last_visit" | "7d" | "30d" | "90d".
                      Wave 3 expands to a concrete date_from. Wins over date_from
                      when both are supplied (Wave 3 logs a warning).
        page        : 1-indexed page number (max 40).
        page_size   : Results per page (max 100, default 25).
    """
    # Wave 1: log the incoming request for observability during development
    _log.info(  # type: ignore[no-any-return]
        "search_documents_stub_called",
        q=q,
        entity_ids=[str(e) for e in entity_id] if entity_id else [],
        scope=scope,
        source_type=source_type,
        page=page,
        page_size=page_size,
    )
    # Wave 3 wires in SearchDocumentsUseCase; for now, 501 so clients know it's not ready.
    # BP-064: use 501 + dict body, never None body — FastAPI ≤0.111 raises validation error
    # on status_code=204 with a non-None response_model.
    return JSONResponse(status_code=501, content={"detail": "not yet implemented"})
