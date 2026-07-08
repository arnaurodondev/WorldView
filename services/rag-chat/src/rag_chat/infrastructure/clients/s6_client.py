"""S6 NLP Pipeline HTTP client adapter (T-E-3-01).

Endpoints:
  POST /api/v1/entities/resolve  → entity resolution (used for ticker resolution too)
  POST /api/v1/search/chunks     → ANN chunk search
  POST /api/v1/embed             → text → BGE-large embedding (PLAN-0093 E-4)
"""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

import httpx
import structlog

from rag_chat.application.ports.upstream_clients import ChunkSearchRequest, EnrichedChunkResult
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.infrastructure.clients.base import BaseUpstreamClient, UpstreamTransportError

_log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# RC-1 (2026-07-05): number of attempts for the pre-loop entity-resolution POST.
# 2 = first try + one retry. The retry exists to survive a STALE pooled
# keep-alive socket: rag-chat holds the S6 connection idle across a long turn
# (~80s of tool calls + synthesis), nlp-pipeline drops the idle connection, and
# the NEXT turn reuses the dead socket → httpx.ConnectError /
# RemoteProtocolError → UpstreamTransportError(reason="upstream_unreachable").
# httpx evicts the dead connection from the pool the instant the send fails, so
# the retry is *guaranteed* to dial a FRESH connection and succeed. We cap at
# ONE retry so a genuinely-down upstream fails fast (tight 5s timeout) instead
# of stacking latency onto the chat path.
_RESOLVE_MAX_ATTEMPTS = 2

# EMBED-RESIL (2026-07-07): attempts for the query-embedding POST (1 try + 1
# retry). Unlike entity-resolve (which only retries the stale-socket class), the
# embed hop ALSO retries a transport *timeout*: DeepInfra bge-large is a slow
# remote model whose first call under concurrent load can blow the read budget
# while the very next call (warm pool / less contention) succeeds. Bounded to
# ONE retry so a genuinely-down S6 fails fast instead of stacking chat latency.
_EMBED_MAX_ATTEMPTS = 2

# Default read timeout for the embed hop when the caller does not pass one.
# Aligned to the 30s upstream default (see config.embed_call_timeout_seconds).
_EMBED_DEFAULT_READ_TIMEOUT_S = 30.0


class S6Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S6 NLP Pipeline."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        *,
        embed_timeout_seconds: float | None = None,
    ) -> None:
        """Construct the S6 adapter.

        ``embed_timeout_seconds`` (EMBED-RESIL): read timeout for the
        ``/api/v1/embed`` hop only. Defaults to ``max(timeout, 30)`` so the slow
        remote-model call is never killed at the (deployment-tightened ~10s)
        shared upstream timeout while other S6 hops keep the tighter default.
        """
        super().__init__(base_url=base_url, timeout=timeout)
        self._embed_timeout_seconds: float = (
            embed_timeout_seconds if embed_timeout_seconds is not None else max(timeout, _EMBED_DEFAULT_READ_TIMEOUT_S)
        )

    # ── Entity resolution ──────────────────────────────────────────────────────

    async def resolve_entities(self, query_text: str) -> list[ResolvedEntity]:
        """POST /api/v1/entities/resolve → list of resolved entities.

        Connection resilience (RC-1): a single transport-level failure of the
        ``upstream_unreachable`` class (stale pooled keep-alive socket →
        ConnectError / RemoteProtocolError) triggers exactly one retry on a
        fresh connection before giving up. Read-timeouts and 5xx are NOT
        retried here — those mean the upstream is reachable but unhealthy, and a
        retry would only burn the chat latency budget; they propagate as
        ``UpstreamTransportError`` for the caller to degrade on.

        If ALL attempts fail, this re-raises ``UpstreamTransportError``. The
        orchestrator's ``ChatPipeline.resolve_entities`` catches it and degrades
        to an empty entity list so the chat turn still runs (RC-1 graceful
        degradation) — the resolve step must NEVER hard-fail the whole turn.
        """
        raw = await self._resolve_with_stale_socket_retry(query_text)
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

    async def _resolve_with_stale_socket_retry(self, query_text: str) -> dict:
        """POST /entities/resolve with one retry on a stale-socket transport error.

        Only ``upstream_unreachable`` (ConnectError / RemoteProtocolError — the
        dead pooled keep-alive socket class) is retried. On the first such
        failure httpx has already evicted the dead connection from its pool, so
        simply re-issuing the request opens a FRESH connection — that is the
        "force a fresh connection" mechanism, no manual pool poking required
        (poking the shared client's pool would be unsafe for sibling turns
        using the same S6Client instance concurrently).

        ``upstream_timeout`` / ``upstream_5xx`` are re-raised on the first hit
        (no retry) — retrying an up-but-unhealthy upstream just spends the chat
        latency budget. After the last attempt any transport error propagates to
        the caller for graceful degradation.
        """
        for attempt in range(_RESOLVE_MAX_ATTEMPTS):
            try:
                return await self._post(
                    "/api/v1/entities/resolve",
                    {"query_text": query_text},
                )
            except UpstreamTransportError as exc:
                is_last = attempt == _RESOLVE_MAX_ATTEMPTS - 1
                # Only the stale-socket class is worth a fresh-connection retry.
                if exc.reason != "upstream_unreachable" or is_last:
                    raise
                _log.warning(  # type: ignore[no-any-return]
                    "s6_resolve_stale_socket_retry",
                    reason=exc.reason,
                    path=exc.path,
                    attempt=attempt,
                    elapsed_ms=exc.elapsed_ms,
                )
        # Unreachable: the loop either returns or raises on every iteration.
        return {}  # pragma: no cover

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

        Resilience (EMBED-RESIL 2026-07-07): the embed POST gets its OWN,
        generous read timeout (``httpx.Timeout`` — BP-235: connect stays tight
        at 5s while read is aligned to the 30s upstream default) so a
        slow-but-successful bge-large embedding is not killed at the deployment's
        tight ~10s shared upstream ReadTimeout. On a transport *timeout* /
        *unreachable* we retry ONCE on a fresh call before giving up. If the
        retry also fails, the ``UpstreamTransportError`` (a ``BaseException``,
        NOT caught by ``except Exception`` below) propagates to the caller so the
        tool surfaces "cannot reach upstream" rather than silently degrading to a
        zero vector (BP-623). A non-transport error still degrades to a zero
        vector so callers can detect the empty vector and skip ANN ranking.
        """
        if not text or not text.strip():
            return [0.0] * 1024
        embed_timeout = httpx.Timeout(
            connect=5.0,
            read=self._embed_timeout_seconds,
            write=5.0,
            pool=5.0,
        )
        for attempt in range(_EMBED_MAX_ATTEMPTS):
            try:
                raw = await self._post("/api/v1/embed", {"text": text}, timeout=embed_timeout)
                vec = raw.get("embedding")
                if isinstance(vec, list) and vec:
                    return [float(x) for x in vec]
                return [0.0] * 1024
            except UpstreamTransportError as exc:
                is_last = attempt == _EMBED_MAX_ATTEMPTS - 1
                # Retry a transient slow/unreachable upstream exactly once; a
                # 5xx (up-but-broken) is not worth a retry and propagates.
                if exc.reason not in ("upstream_timeout", "upstream_unreachable") or is_last:
                    raise
                _log.warning(  # type: ignore[no-any-return]
                    "s6_embed_transport_retry",
                    reason=exc.reason,
                    path=exc.path,
                    attempt=attempt,
                    elapsed_ms=exc.elapsed_ms,
                )
            except Exception as exc:
                _log.warning("s6_embed_text_failed", error=str(exc), text_len=len(text))
                return [0.0] * 1024
        return [0.0] * 1024  # pragma: no cover — loop returns or raises every iteration

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
