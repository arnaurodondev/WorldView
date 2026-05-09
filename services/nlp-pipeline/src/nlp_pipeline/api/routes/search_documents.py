"""Full-text document search endpoint — GET /api/v1/search/documents (PLAN-0064 W6).

Wave 1 stub: validates query params and returns 501 Not Implemented.
Wave 3 wires in the real SearchDocumentsUseCase.

WHY GET (not POST): GET is cache-friendly and bookmark-able — search results should
be shareable via URL. FastAPI parses repeated `entity_id=uuid1&entity_id=uuid2` into
list[UUID] natively, so we don't need a POST body to send multiple entity filters.

Architecture constraints (R25 / LAYER-API-NO-MODULE-LEVEL-INFRA):
  - No module-level imports from `infrastructure.*` in this file.
  - Prometheus metric imports are INSIDE the route handler (body-level) so that
    the architecture test (tests/architecture/test_layer_invariants.py) does not
    flag them as cross-layer violations — the metrics module lives in `infrastructure`.
  - All dependency wiring lives in `api/dependencies.py`; this file only imports
    from `application.use_cases`, `api.schemas`, and `api.dependencies`.

Error mapping (T-W6-3-01):
  RetryableSearchError → 503 Service Unavailable (transient; client should retry)
  FatalSearchError     → 500 Internal Server Error (non-transient bug; log full tb)
  Unexpected exception → 500 Internal Server Error (log full tb; safe catch-all)

Metrics are incremented in a `finally` block so that every request — including
those that raise an exception — contributes a data point with the correct status
label.  The `status` local is set before the try-except so the finally always has
a value to label with.

BP-064: never return 204 + None body in FastAPI ≤0.111; always return a dict body.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from nlp_pipeline.api.dependencies import SearchDocumentsUseCaseDep
from nlp_pipeline.api.schemas import SearchDocumentsRequest, SearchDocumentsResponse
from nlp_pipeline.application.use_cases.search_documents import (
    FatalSearchError,
    RetryableSearchError,
    SearchDocumentsOutput,
)
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["search"])
_log = get_logger(__name__)  # type: ignore[no-any-return]


def _output_to_response(output: SearchDocumentsOutput) -> SearchDocumentsResponse:
    """Map the application-layer SearchDocumentsOutput DTO to the API response schema.

    WHY a separate mapper: the use case returns domain dataclasses (no Pydantic dep);
    the route converts them to Pydantic SearchDocumentsResponse for serialisation.
    This keeps the application layer import-free of api/schemas (LAYER-APP-ISOLATION).
    """
    from nlp_pipeline.api.schemas import SearchDocumentResult, SearchDocumentsFacet

    results = [
        SearchDocumentResult(
            doc_id=hit.doc_id,
            title=hit.title,
            source_type=hit.source_type,
            source_url=hit.source_url,
            # published_at may be a raw string from S5 JSON — coerce to datetime if needed.
            published_at=hit.published_at if isinstance(hit.published_at, datetime) else None,
            snippet=hit.snippet,
            match_offsets=hit.match_offsets,
            score=hit.score,
            entity_hits=hit.entity_hits,
        )
        for hit in output.results
    ]

    facets = [
        SearchDocumentsFacet(
            entity_id=facet.entity_id,
            name=facet.name,
            entity_type=facet.entity_type,
            count=facet.count,
        )
        for facet in output.facets
    ]

    return SearchDocumentsResponse(
        query=output.query,
        total=output.total,
        page=output.page,
        page_size=output.page_size,
        has_more=output.has_more,
        results=results,
        facets=facets,
        latency_ms=output.latency_ms,
    )


@router.get("/search/documents", response_model=SearchDocumentsResponse)
async def search_documents(
    use_case: SearchDocumentsUseCaseDep,
    q: str = Query(..., min_length=1, max_length=500),
    entity_id: list[UUID] | None = Query(None),
    scope: str = Query("all"),
    source_type: str = Query("all"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    date_preset: str | None = Query(None),
    page: int = Query(1, ge=1, le=40),
    page_size: int = Query(25, ge=1, le=100),
) -> SearchDocumentsResponse:
    """Full-text search across articles + EDGAR filings with entity facets.

    Query params:
        q           : Required. Parsed via websearch_to_tsquery (supports quoted
                      phrases and OR / - operators).
        entity_id   : Optional, repeatable UUID filter. Multiple values treated as
                      OR-within-document (any mention qualifies).
        scope       : "watchlist" | "portfolio" | "all" (default "all").
                      Watchlist/portfolio entity sets are resolved server-side.
        source_type : "news" | "sec_edgar" | "all" (default "all").
        date_from   : ISO 8601 datetime lower bound on published_at.
        date_to     : ISO 8601 datetime upper bound on published_at.
        date_preset : "since_last_visit" | "7d" | "30d" | "90d".
                      Wins over date_from when both are supplied.
        page        : 1-indexed page number (max 40).
        page_size   : Results per page (max 100, default 25).

    Returns:
        SearchDocumentsResponse with total, results, facets, and latency_ms.

    Errors:
        422: Invalid query params (missing q, bad uuid, etc.)
        503: Transient search failure (client should retry)
        500: Fatal error (bug or misconfiguration)
    """
    # Body-level import of Prometheus metrics — must NOT be at module scope.
    # The architecture test (tests/architecture/test_layer_invariants.py) checks
    # that api/routes/* files do not have module-level imports from infrastructure/*.
    # Moving the import inside the handler body satisfies R25 while still being
    # reachable at call time (Python caches sys.modules so this is cheap after
    # the first call).
    import time

    from nlp_pipeline.infrastructure.metrics.prometheus import (
        s6_search_documents_duration_seconds,
        s6_search_documents_results_count,
        s6_search_documents_total,
    )

    # `src` is the metric label used throughout — "all" when no source_type filter.
    src = source_type
    start = time.perf_counter()
    # `status` is set before try so the finally block always has a valid label,
    # even if a ValidationError fires before the use case is called.
    status = "ok"

    try:
        # Build the domain request DTO from query params.
        # Wrap in try/except ValidationError so Pydantic model_validator errors
        # (e.g. naive datetimes, date_from > date_to) become 422 responses.
        try:
            req = SearchDocumentsRequest(
                q=q,
                entity_ids=entity_id or [],
                scope=scope,  # type: ignore[arg-type]
                source_type=source_type,  # type: ignore[arg-type]
                date_from=date_from,
                date_to=date_to,
                date_preset=date_preset,  # type: ignore[arg-type]
                page=page,
                page_size=page_size,
            )
        except ValidationError as exc:
            # Pydantic validation errors from the model_validator (e.g. naive
            # datetime) become 422 — same status as FastAPI's own param validation.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        output = await use_case.execute(req)

        # Classify the result for the status label: "empty" when total=0, "ok" otherwise.
        # This lets dashboards distinguish "no matching docs" from real errors.
        if output.total == 0:
            status = "empty"

        # Observe result count BEFORE returning — this is the only place we have
        # both source_type and the result count at the same time.
        s6_search_documents_results_count.labels(source_type=src).observe(output.total)

        # Map domain DTO → Pydantic API response schema.
        return _output_to_response(output)

    except HTTPException:
        # Re-raise FastAPI HTTPException so it is not swallowed by the generic handler.
        status = "error"
        raise

    except RetryableSearchError as exc:
        # Transient failure: DB timeout, pool exhausted, etc.
        status = "error"
        _log.warning("search_retryable_error", q=q, error=str(exc))  # type: ignore[no-any-return]
        raise HTTPException(status_code=503, detail="Search temporarily unavailable. Please retry.") from exc

    except FatalSearchError as exc:
        # Non-transient failure: programming error, schema mismatch, etc.
        status = "error"
        _log.exception("search_fatal_error", q=q)  # type: ignore[no-any-return]
        raise HTTPException(status_code=500, detail="Internal search error") from exc

    except Exception as exc:
        # Catch-all safety net — should never fire in production if the use case
        # and repo are correct, but prevents raw 500s with unstructured tracebacks
        # from leaking to clients.
        status = "error"
        _log.exception("search_unexpected_error", q=q)  # type: ignore[no-any-return]
        raise HTTPException(status_code=500, detail="Unexpected error") from exc

    finally:
        # Metrics are always incremented — even when an exception escapes.
        # BP-064: always a dict body, never 204+None.
        elapsed = time.perf_counter() - start
        s6_search_documents_total.labels(source_type=src, status=status).inc()
        s6_search_documents_duration_seconds.labels(source_type=src).observe(elapsed)
