"""Content-store HTTP client adapter — resolve ``doc_id`` → source-article metadata.

Backs ``ContentStorePort``. The single endpoint:

    POST /api/v1/documents/batch  → {"documents": [{doc_id, title, url,
                                      published_at, source_name, source_type, ...}]}

Used to backfill knowledge-graph-derived citations (claims, events) with the URL
of the news article they were extracted from. The KG service stores only the
``doc_id`` reference — the article title/url live in content-store (R9) — so we
resolve the linkage over REST instead of a cross-service DB read.

The endpoint is internal (InternalJWTMiddleware, RS256). ``BaseUpstreamClient``
forwards the request-scoped ``X-Internal-JWT`` automatically, so no extra auth
wiring is needed here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rag_chat.application.ports.upstream_clients import DocumentMetadata
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

# content-store caps the batch at 50 doc_ids per request (BatchDocumentsUseCase).
# We mirror the cap here so an over-large claim/event set never trips a 400.
_MAX_BATCH = 50


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string (as serialised by content-store) → datetime.

    Returns None on any parse failure so a malformed timestamp never breaks the
    citation backfill (the citation simply loses its published_at).
    """
    if not value:
        return None
    try:
        # content-store serialises ``datetime`` to ISO-8601; ``fromisoformat``
        # handles the offset-aware form (e.g. "...+00:00") emitted by pydantic.
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class ContentStoreClient(BaseUpstreamClient):
    """Concrete HTTP adapter for content-store document-metadata lookup."""

    async def get_documents_metadata(
        self,
        doc_ids: list[UUID],
    ) -> dict[UUID, DocumentMetadata]:
        """POST /api/v1/documents/batch → ``{doc_id: DocumentMetadata}`` map.

        De-duplicates ``doc_ids`` and caps the request at 50 (content-store's
        own limit). Missing documents are omitted from the returned map.
        Returns ``{}`` on HTTP 4xx, empty input, or no results. Transport
        failures (connect / timeout / 5xx) raise ``UpstreamTransportError`` —
        callers that treat this as a best-effort enrichment should catch it.
        """
        if not doc_ids:
            return {}
        # Preserve order while de-duplicating, then cap to the upstream limit.
        seen: dict[UUID, None] = {}
        for d in doc_ids:
            seen.setdefault(d, None)
        unique = list(seen.keys())[:_MAX_BATCH]

        raw = await self._post(
            "/api/v1/documents/batch",
            {"doc_ids": [str(d) for d in unique]},
        )
        out: dict[UUID, DocumentMetadata] = {}
        for item in raw.get("documents", []):
            try:
                doc_id = UUID(str(item["doc_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            out[doc_id] = DocumentMetadata(
                doc_id=str(doc_id),
                title=item.get("title"),
                url=item.get("url"),
                published_at=_parse_dt(item.get("published_at")),
                source_name=item.get("source_name"),
                source_type=item.get("source_type"),
            )
        return out
