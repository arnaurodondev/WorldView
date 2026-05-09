"""SearchDocumentsUseCase — orchestrator for full-text document search (PLAN-0064 W6).

Responsibilities (AD-W6-3):
  1. Run FTS query via DocumentSearchRepositoryPort (gets raw sentinel-marked snippets).
  2. Post-process snippets: sentinel bytes → plain text + char offsets (_strip_markers).
  3. Optimisation: if the repo returns no hits, skip all downstream calls.
  4. Fetch entity facets from the repo (name field left empty).
  5. In PARALLEL via asyncio.gather: S5 batch document titles + S7 batch entity names.
  6. Merge S5 metadata (title, source_url, published_at) into hits.
  7. Merge S7 entity names into facets.
  8. Return SearchDocumentsOutput — a domain-layer result DTO.

R12 / R25: this module is at the application layer — no infrastructure imports,
no api/ imports (LAYER-APP-ISOLATION).  The API route (Wave 3) maps
SearchDocumentsOutput → SearchDocumentsResponse (Pydantic schema).
BP-235: both _S5BatchClient and _S7BatchClient use httpx.Timeout(2.0) to avoid
the httpx 5-second default firing before asyncio.wait_for would (BP-235).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx

from nlp_pipeline.application.use_cases._snippet import _strip_markers
from observability import get_logger  # type: ignore[import-untyped]

# ── Domain-layer error types (PLAN-0064 W6 T-W6-3-01) ─────────────────────────
# These are raised by the use case and caught by the API route to produce the
# correct HTTP status codes (R25: route must not import from infrastructure).
#
# RetryableSearchError: transient DB/network failure (asyncpg QueryCanceledError,
#   statement_timeout, connection pool exhausted). The route maps it to 503 so
#   the client knows to retry. The error is NOT logged at exception level here —
#   the calling code logs it as a warning to avoid log noise on transient blips.
#
# FatalSearchError: non-transient DB failure (programming error, schema mismatch,
#   unexpected exception). The route maps it to 500 and logs the full traceback.


class RetryableSearchError(Exception):
    """Raised when the FTS query fails transiently (timeout, pool exhausted).

    The API route maps this to HTTP 503 and the client should back off + retry.
    Typical causes: asyncpg ``QueryCanceledError``, statement_timeout exceeded,
    or a momentary loss of the Postgres connection pool.
    """


class FatalSearchError(Exception):
    """Raised when the FTS query fails non-transiently (programming error, schema mismatch).

    The API route maps this to HTTP 500.  These errors indicate a bug or
    misconfiguration and should be investigated; retrying will not help.
    """


if TYPE_CHECKING:
    # TYPE_CHECKING-only: makes type hints work without runtime api/ import.
    # from __future__ import annotations turns all annotations into strings,
    # so these are never evaluated at runtime.
    from nlp_pipeline.api.schemas import (
        SearchDocumentResult,
        SearchDocumentsFacet,
        SearchDocumentsRequest,
    )
    from nlp_pipeline.application.ports.document_search import DocumentSearchRepositoryPort

_log = get_logger(__name__)  # type: ignore[no-any-return]


# ── Domain-layer result DTOs ──────────────────────────────────────────────────
# These dataclasses live in the application layer so use cases don't need to
# construct Pydantic API schemas directly (LAYER-APP-ISOLATION).
# The Wave 3 route maps them to SearchDocumentsResponse.


@dataclass(frozen=True)
class SearchDocumentsHit:
    """One document hit in the search result (application-layer DTO)."""

    doc_id: UUID
    title: str | None
    source_type: str
    source_url: str | None
    published_at: Any | None  # datetime | str | None — avoids runtime type dep
    snippet: str | None
    match_offsets: list[tuple[int, int]]
    score: float
    entity_hits: list[UUID]


@dataclass(frozen=True)
class SearchDocumentsFacetResult:
    """One entity facet in the search result (application-layer DTO)."""

    entity_id: UUID
    name: str
    entity_type: str
    count: int


@dataclass(frozen=True)
class SearchDocumentsOutput:
    """Application-layer result DTO for the document search use case.

    Returned by SearchDocumentsUseCase.execute(). The API route (Wave 3)
    maps this to SearchDocumentsResponse (Pydantic) before returning it
    to the client.
    """

    query: str
    total: int
    page: int
    page_size: int
    has_more: bool
    results: list[SearchDocumentsHit]
    facets: list[SearchDocumentsFacetResult]
    latency_ms: int


# ── S5 content-store batch client ─────────────────────────────────────────────


class _S5BatchClient:
    """Thin HTTP client for ``POST /api/v1/documents/batch`` on S5 content-store.

    Returns a mapping of doc_id → document metadata dict on success.
    On any non-200 response (including network errors) returns {} so that
    the use case can gracefully fall back to title=None rather than crashing.

    BP-235: httpx.Timeout(2.0) used explicitly to avoid the default 5-second
    timeout silently shadowing an asyncio.wait_for wrapper.

    jwt: the X-Internal-JWT value forwarded from the incoming request so that
    S5's InternalJWTMiddleware accepts the call.  When None (tests, no auth
    configured) the header is omitted and S5 must have auth disabled.
    """

    def __init__(self, base_url: str, timeout: float = 2.0, jwt: str | None = None) -> None:
        self._base_url = base_url
        # BP-235: always specify httpx.Timeout(N) — never rely on the default.
        self._timeout = httpx.Timeout(timeout)
        self._jwt = jwt

    async def batch_documents(self, doc_ids: list[UUID]) -> dict[UUID, dict]:
        """POST /api/v1/documents/batch → {doc_id: {title, source_url, published_at, ...}}"""
        if not doc_ids:
            return {}
        headers: dict[str, str] = {}
        if self._jwt:
            headers["X-Internal-JWT"] = self._jwt
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/v1/documents/batch",
                    json={"doc_ids": [str(d) for d in doc_ids]},
                    headers=headers,
                )
                if resp.status_code != 200:
                    _log.warning(  # type: ignore[no-any-return]
                        "s5_batch_non_200",
                        status_code=resp.status_code,
                        url=f"{self._base_url}/api/v1/documents/batch",
                    )
                    return {}
                data = resp.json()
                return {UUID(item["doc_id"]): item for item in data.get("documents", [])}
        except Exception as exc:
            _log.warning("s5_batch_error", error=str(exc))  # type: ignore[no-any-return]
            return {}


# ── S7 knowledge-graph batch client ───────────────────────────────────────────


class _S7BatchClient:
    """Thin HTTP client for ``POST /api/v1/entities/batch`` on S7 knowledge-graph.

    Returns a mapping of entity_id → entity metadata dict on success.
    On any non-200 response (including network errors) returns {} so that
    the use case can gracefully fall back to name=str(entity_id).

    BP-235: httpx.Timeout(2.0) used explicitly.

    jwt: the X-Internal-JWT value forwarded from the incoming request so that
    S7's InternalJWTMiddleware accepts the call.
    """

    def __init__(self, base_url: str, timeout: float = 2.0, jwt: str | None = None) -> None:
        self._base_url = base_url
        # BP-235: always specify httpx.Timeout(N) — never rely on the default.
        self._timeout = httpx.Timeout(timeout)
        self._jwt = jwt

    async def batch_get_entities(self, entity_ids: list[UUID]) -> dict[UUID, dict]:
        """POST /api/v1/entities/batch → {entity_id: {canonical_name, entity_type, ...}}"""
        if not entity_ids:
            return {}
        headers: dict[str, str] = {}
        if self._jwt:
            headers["X-Internal-JWT"] = self._jwt
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/v1/entities/batch",
                    json={"entity_ids": [str(e) for e in entity_ids]},
                    headers=headers,
                )
                if resp.status_code != 200:
                    _log.warning(  # type: ignore[no-any-return]
                        "s7_batch_non_200",
                        status_code=resp.status_code,
                        url=f"{self._base_url}/api/v1/entities/batch",
                    )
                    return {}
                data = resp.json()
                return {UUID(item["entity_id"]): item for item in data.get("entities", [])}
        except Exception as exc:
            _log.warning("s7_batch_error", error=str(exc))  # type: ignore[no-any-return]
            return {}


# ── Use case ───────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    """Default clock — returns current UTC datetime.

    Defined as a module-level function so that tests can inject a fake clock
    via the constructor without importing from common (keeps the use case free
    of library dependencies that aren't already present).
    """
    return datetime.now(tz=UTC)


def _hit_from_repo_result(
    repo_result: SearchDocumentResult,
    s5_meta: dict,
) -> SearchDocumentsHit:
    """Convert a repo SearchDocumentResult + S5 metadata dict into a domain hit.

    Strips sentinel markers from the snippet and applies S5 metadata.
    """
    snippet = repo_result.snippet
    offsets: list[tuple[int, int]] = []
    if snippet:
        snippet, offsets = _strip_markers(snippet)

    return SearchDocumentsHit(
        doc_id=repo_result.doc_id,
        title=s5_meta.get("title"),
        source_type=repo_result.source_type,
        source_url=s5_meta.get("source_url") or s5_meta.get("url"),
        published_at=s5_meta.get("published_at"),
        snippet=snippet,
        match_offsets=offsets,
        score=repo_result.score,
        entity_hits=list(repo_result.entity_hits),
    )


def _facet_from_repo_result(
    repo_facet: SearchDocumentsFacet,
    s7_entities: dict[UUID, dict],
) -> SearchDocumentsFacetResult:
    """Convert a repo SearchDocumentsFacet + S7 entity dict into a domain facet."""
    entity_meta = s7_entities.get(repo_facet.entity_id, {})
    name = entity_meta.get("canonical_name") or entity_meta.get("name") or str(repo_facet.entity_id)
    return SearchDocumentsFacetResult(
        entity_id=repo_facet.entity_id,
        name=name,
        entity_type=repo_facet.entity_type,
        count=repo_facet.count,
    )


class SearchDocumentsUseCase:
    """Orchestrate full-text document search (PLAN-0064 W6 T-W6-2-03).

    Dependency injection (R25):
      - repo: DocumentSearchRepositoryPort — the FTS query engine (Wave 2 asyncpg impl)
      - s5_client: _S5BatchClient — fetches document titles from S5 content-store
      - s7_client: _S7BatchClient — fetches entity names from S7 knowledge-graph
      - clock: callable returning current datetime (injectable for tests)

    Returns SearchDocumentsOutput (domain DTO). The Wave 3 API route maps it
    to SearchDocumentsResponse (Pydantic) before serialising to the client.

    The use case is the only module that calls both the repo and the HTTP clients.
    The repo knows nothing about HTTP; the clients know nothing about SQL.
    """

    def __init__(
        self,
        repo: DocumentSearchRepositoryPort,
        s5_client: _S5BatchClient,
        s7_client: _S7BatchClient,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.repo = repo
        self.s5_client = s5_client
        self.s7_client = s7_client
        self._clock = clock

    async def execute(self, request: SearchDocumentsRequest) -> SearchDocumentsOutput:
        """Execute the full search pipeline and return a SearchDocumentsOutput.

        Pipeline:
          1. FTS query via repo.search() — returns raw sentinel-marked snippets.
          2. Empty result fast-path: skip all downstream calls (saves 3 RTTs).
          3. Post-process snippets: _strip_markers() → plain text + offsets.
          4. Entity facets via repo.facets().
          5. asyncio.gather(S5 batch titles, S7 batch entity names) in parallel.
          6. Merge S5 metadata into hits.
          7. Merge S7 names into facets.
          8. Return SearchDocumentsOutput with latency_ms.
        """
        start = time.perf_counter()

        # ── Step 1: FTS query ─────────────────────────────────────────────────
        raw_hits, total = await self.repo.search(request)

        # ── Step 2: Empty result fast-path ────────────────────────────────────
        # Skip facets + S5 + S7 to save 3 network round-trips on cache misses.
        if not raw_hits:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return SearchDocumentsOutput(
                query=request.q,
                total=0,
                page=request.page,
                page_size=request.page_size,
                has_more=False,
                results=[],
                facets=[],
                latency_ms=latency_ms,
            )

        # ── Step 3: Facets query ──────────────────────────────────────────────
        hit_doc_ids = [h.doc_id for h in raw_hits]
        facet_rows = await self.repo.facets(request, hit_doc_ids)

        # ── Step 4: Parallel S5 + S7 batch calls ─────────────────────────────
        # asyncio.gather runs both HTTP calls concurrently; return_exceptions=True
        # prevents one failure from cancelling the other.
        facet_entity_ids = [f.entity_id for f in facet_rows]
        s5_task = self.s5_client.batch_documents(hit_doc_ids)
        s7_task = self.s7_client.batch_get_entities(facet_entity_ids)

        gather_results = await asyncio.gather(
            s5_task,
            s7_task,
            return_exceptions=True,
        )
        raw_s5, raw_s7 = gather_results[0], gather_results[1]

        # Degrade gracefully: if either batch call raises, log and use empty dict.
        # asyncio.gather with return_exceptions=True returns BaseException | T,
        # so we check explicitly and assign to typed local vars.
        s5_data: dict[UUID, dict]
        s7_data: dict[UUID, dict]

        if isinstance(raw_s5, BaseException):
            _log.warning("s5_batch_failed", error=str(raw_s5))  # type: ignore[no-any-return]
            s5_data = {}
        else:
            s5_data = raw_s5  # type: ignore[assignment]

        if isinstance(raw_s7, BaseException):
            _log.warning("s7_batch_failed", error=str(raw_s7))  # type: ignore[no-any-return]
            s7_data = {}
        else:
            s7_data = raw_s7  # type: ignore[assignment]

        # ── Step 5: Build final hits ──────────────────────────────────────────
        # _hit_from_repo_result strips sentinel bytes and merges S5 metadata.
        final_hits: list[SearchDocumentsHit] = []
        for hit in raw_hits:
            s5_meta = s5_data.get(hit.doc_id, {})
            if not s5_meta:
                _log.warning("s5_missing_doc", doc_id=str(hit.doc_id))  # type: ignore[no-any-return]
            final_hits.append(_hit_from_repo_result(hit, s5_meta))

        # ── Step 6: Build final facets ────────────────────────────────────────
        # _facet_from_repo_result merges S7 entity names.
        # I-001: skip facets where S7 returned no metadata — these represent
        # orphaned entity_mentions (resolved_entity_id exists in NLP DB but
        # the entity was deleted from canonical_entities in S7's KG DB).
        # Showing a raw UUID string in the facet sidebar is worse than omitting
        # the facet entirely: it confuses users and is unclickable as a filter.
        final_facets: list[SearchDocumentsFacetResult] = []
        for facet in facet_rows:
            if not s7_data.get(facet.entity_id):
                _log.warning(  # type: ignore[no-any-return]
                    "s7_missing_entity_skipped",
                    entity_id=str(facet.entity_id),
                )
                continue  # omit unresolvable facets — UUID string is worse than no facet
            final_facets.append(_facet_from_repo_result(facet, s7_data))

        # ── Step 7: Build output ──────────────────────────────────────────────
        latency_ms = int((time.perf_counter() - start) * 1000)
        # has_more: true when there are more pages beyond the current page.
        # Example: total=30, page=1, page_size=25 → page 1 returns 25 items;
        #          page 2 would return 5 more → has_more=True on page 1.
        has_more = total > request.page * request.page_size

        return SearchDocumentsOutput(
            query=request.q,
            total=total,
            page=request.page,
            page_size=request.page_size,
            has_more=has_more,
            results=final_hits,
            facets=final_facets,
            latency_ms=latency_ms,
        )
