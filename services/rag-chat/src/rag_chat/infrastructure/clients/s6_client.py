"""S6 NLP Pipeline HTTP client adapter (T-E-3-01).

Endpoints:
  POST /api/v1/entities/resolve  → entity resolution (used for ticker resolution too)
  POST /api/v1/search/chunks     → ANN chunk search
  POST /api/v1/embed             → text → BGE-large embedding (PLAN-0093 E-4)
"""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

import structlog

from rag_chat.application.ports.upstream_clients import ChunkSearchRequest, EnrichedChunkResult
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class S6Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S6 NLP Pipeline."""

    # ── Entity resolution ──────────────────────────────────────────────────────

    async def resolve_entities(self, query_text: str) -> list[ResolvedEntity]:
        """POST /api/v1/entities/resolve → list of resolved entities.

        Returns an empty list on timeout or HTTP error (safe degradation).
        """
        raw = await self._post(
            "/api/v1/entities/resolve",
            {"query_text": query_text},
        )
        entities: list[dict] = raw.get("entities", [])
        results: list[ResolvedEntity] = []
        for item in entities:
            try:
                entity_id: UUID = item["entity_id"]  # type: ignore[assignment]
                results.append(
                    ResolvedEntity(
                        entity_id=entity_id,
                        canonical_name=item.get("canonical_name", ""),
                        entity_type=item.get("entity_type", ""),
                        confidence=float(item.get("confidence", 0.0)),
                        matched_text=item.get("matched_text", ""),
                        ticker=item.get("ticker"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Chunk search ───────────────────────────────────────────────────────────

    async def search_chunks(self, request: ChunkSearchRequest) -> list[EnrichedChunkResult]:
        """POST /api/v1/search/chunks → ranked enriched chunk results.

        Returns an empty list on timeout or HTTP error (safe degradation, R9).
        """
        payload: dict = {
            "top_k": request.top_k,
            "min_score": request.min_score,
            "granularity": request.granularity,
            "include_entities": request.include_entities,
            "source_types": request.source_types,
            # PLAN-0063 W5-3: forward the orchestrator's search_type choice
            # over the wire. S6 validates the literal set; the port stayed
            # loose so older callers (set to "ann") keep working unchanged.
            "search_type": request.search_type,
        }
        if request.query_text is not None:
            payload["query_text"] = request.query_text
        # Truthy check: empty list [] means embed failed → omit field so
        # query_text fallback path is used (prevents 422 from nlp-pipeline
        # ChunkSearchRequest "exactly_one_query" validator). BP-183 fix.
        if request.query_embedding:
            payload["query_embedding"] = request.query_embedding
        if request.date_from is not None:
            payload["date_from"] = request.date_from.date().isoformat()
        if request.date_to is not None:
            payload["date_to"] = request.date_to.date().isoformat()
        # PLAN-0078 Wave D: forward entity filter fields when present.
        if request.entity_ids:
            payload["entity_ids"] = [str(eid) for eid in request.entity_ids]
        if request.entity_types:
            payload["entity_types"] = request.entity_types
        # PLAN-0086 Wave C-1: forward tenant_id to S6 for per-tenant chunk isolation.
        # None is not sent so S6 defaults to public-only (safe default behaviour).
        if request.tenant_id is not None:
            payload["tenant_id"] = request.tenant_id

        raw = await self._post("/api/v1/search/chunks", payload)
        results_raw: list[dict] = raw.get("results", [])
        results: list[EnrichedChunkResult] = []
        for item in results_raw:
            try:
                meta: dict = item.get("source_metadata", {})
                published_at = None
                if meta.get("published_at"):
                    from datetime import datetime

                    published_at = datetime.fromisoformat(meta["published_at"].replace("Z", "+00:00")).replace(
                        tzinfo=UTC
                    )
                results.append(
                    EnrichedChunkResult(
                        chunk_id=item["chunk_id"],
                        doc_id=item["doc_id"],
                        text=item.get("text", ""),
                        score=float(item.get("score", 0.0)),
                        source_type=meta.get("source_type", ""),
                        title=meta.get("title"),
                        url=meta.get("url"),
                        published_at=published_at,
                        source_name=meta.get("source_name"),
                        section_id=item.get("section_id"),
                        granularity=item.get("granularity", "chunk"),
                        section_type=item.get("section_type"),
                        heading_path=item.get("heading_path"),
                        entities=item.get("entities", []),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Embedding (PLAN-0093 Wave E-4) ────────────────────────────────────────

    async def embed_text(self, text: str) -> list[float]:
        """POST /api/v1/embed → BGE-large 1024-dim vector for *text*.

        Used by ``search_entity_relations`` so the ANN search receives a real
        query embedding instead of a 1024-dim zero vector (F-RAG-004). The
        endpoint already exists on the S6 service (used by HyDE adapter).

        On any transport/HTTP error we return a zero vector and log a
        warning — callers that need ANN ranking can detect the empty
        vector and skip the query.
        """
        if not text or not text.strip():
            return [0.0] * 1024
        try:
            raw = await self._post("/api/v1/embed", {"text": text})
            vec = raw.get("embedding")
            if isinstance(vec, list) and vec:
                return [float(x) for x in vec]
        except Exception as exc:
            _log.warning("s6_embed_text_failed", error=str(exc), text_len=len(text))
        return [0.0] * 1024

    # ── Ticker → entity resolution (PLAN-0093 Wave E-4 T-E-4-02) ──────────────

    async def resolve_entity_by_ticker(self, ticker: str) -> UUID | None:
        """Resolve a stock ticker to a financial-instrument entity_id.

        Reuses the existing ``/api/v1/entities/resolve`` endpoint which already
        accepts free-text queries containing ticker symbols (e.g. "AAPL").
        Returns the highest-confidence ResolvedEntity that has a matching
        ticker field, or None if no candidate matches.

        Why a separate method (not just resolve_entities): callers want a
        clean (ticker → UUID-or-None) API without the ResolvedEntity wrapper
        + confidence filtering boilerplate.
        """
        if not ticker or not ticker.strip():
            return None
        try:
            candidates = await self.resolve_entities(ticker.upper())
        except Exception as exc:
            _log.warning("s6_resolve_ticker_failed", error=str(exc), ticker=ticker)
            return None
        # Prefer a candidate whose ``ticker`` field matches the input.
        # BP-661: multiple canonicals can share the SAME ticker when a
        # BP-459-style phantom twin exists ("AAPL Stock" and "Apple Inc."
        # both carry ticker=AAPL). Phantom twins almost always EMBED the
        # ticker in their canonical name ("AAPL Stock", "AAPL.US",
        # "NasdaqGS:AAPL") while the real canonical does not ("Apple Inc."),
        # so among exact-ticker matches we prefer candidates whose name does
        # NOT contain the ticker as a token. Falls back to the first
        # (highest-confidence) exact match when every candidate looks
        # ticker-derived.
        import re as _re

        _ticker_norm = ticker.strip().upper()
        exact = [cand for cand in candidates if (getattr(cand, "ticker", None) or "").upper() == _ticker_norm]
        if exact:
            clean = [
                cand
                for cand in exact
                if _ticker_norm.lower() not in {t for t in _re.split(r"[^a-z0-9]+", cand.canonical_name.lower()) if t}
            ]
            pick = (clean or exact)[0]
            if len(exact) > 1:
                _log.info(
                    "ticker_resolved_twin_disambiguated",
                    ticker=ticker,
                    entity_id=str(pick.entity_id),
                    canonical_name=pick.canonical_name,
                    n_exact_matches=len(exact),
                )
            return UUID(str(pick.entity_id))
        if not candidates:
            _log.warning("ticker_unresolved", ticker=ticker)
            return None
        # Fallback: best-confidence candidate (still log so we know the
        # ticker→entity link is only inferred, not exact).
        best = candidates[0]
        _log.info("ticker_resolved_inexact", ticker=ticker, entity_id=str(best.entity_id))
        return UUID(str(best.entity_id))
