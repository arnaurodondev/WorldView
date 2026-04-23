"""Parallel retrieval orchestrator - Step 5 of the RAG pipeline (T-F-1-01).

Executes Steps 5A-5I concurrently using asyncio.gather.
Each task is wrapped in asyncio.wait_for(timeout=5.0).
On timeout or error, the task returns an empty list (logged at WARNING - not fatal).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

if TYPE_CHECKING:
    from rag_chat.application.pipeline.circuit_breaker import SourceCircuitBreaker
    from rag_chat.application.ports.upstream_clients import (
        S1Port,
        S3Port,
        S6Port,
        S7Port,
    )
    from rag_chat.domain.entities.chat import ChatRequest, ResolvedQuery, RetrievalPlan

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Source type → trust weight mapping (from PRD §6.7 Step 7)
DEFAULT_TRUST_WEIGHTS: dict[str, float] = {
    "sec_10k": 0.95,
    "sec_10q": 0.95,
    "sec_8k": 0.90,
    "earnings_data": 0.95,
    "corporate_action": 0.90,
    "eodhd_news": 0.70,
    "finnhub_news": 0.65,
    "relation": 0.85,
    "claim": 0.80,
    "financial": 0.90,
    "default": 0.60,
}

_RETRIEVAL_TIMEOUT = 5.0  # seconds per task
_MAX_GRAPH_ENTITIES = 3  # cap for egocentric + contradiction fetches


class ParallelRetrievalOrchestrator:
    """Execute all RAG retrieval steps (5A-5I) concurrently.

    Args:
        s6_client:  S6 NLP Pipeline client (chunk search + entity resolution).
        s7_client:  S7 Knowledge Graph client (relations, graph, claims, events, contradictions).
        s3_client:  S3 Market Data client (fundamentals, earnings, quotes).
        s1_client:  S1 Portfolio client (portfolio context).
        timeout:    Per-task timeout in seconds (default 5.0).
        circuit_breakers: Optional dict of source_name → SourceCircuitBreaker.
                          When provided, sources are checked/recorded via their CB.
                          When absent or empty, all sources run unconditionally.
    """

    def __init__(
        self,
        s6_client: S6Port,
        s7_client: S7Port,
        s3_client: S3Port,
        s1_client: S1Port,
        *,
        timeout: float = _RETRIEVAL_TIMEOUT,
        s1_internal_token: str = "",
        circuit_breakers: dict[str, SourceCircuitBreaker] | None = None,
    ) -> None:
        self._s6 = s6_client
        self._s7 = s7_client
        self._s3 = s3_client
        self._s1 = s1_client
        self._timeout = timeout
        self._s1_internal_token = s1_internal_token
        self._cbs = circuit_breakers or {}

    async def retrieve(
        self,
        plan: RetrievalPlan,
        resolved_query: ResolvedQuery,
        request: ChatRequest,
        query_embedding: list[float] | None = None,
    ) -> list[RetrievedItem]:
        """Run all enabled retrieval steps in parallel.

        Returns a flat list of RetrievedItem from all successful tasks.
        Tasks that time out or raise return empty lists (safe degradation).
        """
        entity_ids: list[UUID] = [e.entity_id for e in resolved_query.resolved_entities]

        tasks: list[Any] = []

        if plan.use_chunks:
            tasks.append(self._with_cb("chunk", self._fetch_chunks(resolved_query, plan, query_embedding)))
        if plan.use_relations and query_embedding:
            tasks.append(self._with_cb("relations", self._fetch_relations(query_embedding, entity_ids)))
        if plan.use_graph:
            for eid in entity_ids[:_MAX_GRAPH_ENTITIES]:
                tasks.append(self._with_cb("graph", self._fetch_graph(eid)))
        if plan.use_claims:
            tasks.append(self._with_cb("claims", self._fetch_claims(entity_ids, plan)))
        if plan.use_events:
            tasks.append(self._with_cb("events", self._fetch_events(entity_ids, plan)))
        if plan.use_contradictions:
            for eid in entity_ids[:_MAX_GRAPH_ENTITIES]:
                tasks.append(self._with_cb("contradictions", self._fetch_contradictions(eid)))
        if plan.use_financial:
            for entity in resolved_query.resolved_entities[:_MAX_GRAPH_ENTITIES]:
                if entity.ticker:
                    tasks.append(self._with_cb("financial", self._fetch_financial(entity.ticker)))
        if plan.use_portfolio:
            tasks.append(self._with_cb("portfolio", self._fetch_portfolio(request)))
        if plan.use_cypher and entity_ids:
            tasks.append(self._with_cb("cypher", self._fetch_cypher(entity_ids[0])))

        if not tasks:
            return []

        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

        items: list[RetrievedItem] = []
        for r in results_nested:
            if isinstance(r, Exception):
                log.warning("retrieval_task_failed", error=str(r))  # type: ignore[no-any-return]
            elif isinstance(r, list):
                items.extend(r)
        return items

    # ── Circuit breaker wrapper ──────────────────────────────────────────────

    async def _with_cb(
        self,
        source_name: str,
        coro: Any,
    ) -> list[RetrievedItem]:
        """Wrap a retrieval coroutine with circuit breaker check/record.

        If the circuit breaker for *source_name* is OPEN, skip the call and
        return an empty list.  On success, record success; on failure, record
        failure.  If no CB is configured for this source, run directly.
        """
        cb = self._cbs.get(source_name)
        if cb is not None and await cb.is_open():
            # Close the unawaited coroutine to suppress RuntimeWarning
            coro.close()
            log.warning("retrieval_source_skipped_circuit_open", source=source_name)
            return []

        try:
            result = await coro
        except Exception as exc:
            if cb is not None:
                await cb.record_failure()
            log.warning("retrieval_source_failed", source=source_name, error=str(exc))
            return []

        if cb is not None:
            await cb.record_success()
        return result  # type: ignore[no-any-return]

    # ── Private fetch methods (may raise — _with_cb catches) ──────────────────

    async def _fetch_chunks(
        self,
        resolved_query: ResolvedQuery,
        plan: RetrievalPlan,
        query_embedding: list[float] | None,
    ) -> list[RetrievedItem]:
        from rag_chat.application.ports.upstream_clients import ChunkSearchRequest

        req = ChunkSearchRequest(
            query_embedding=query_embedding,
            query_text=resolved_query.rephrased_query if not query_embedding else None,
            top_k=20,
            include_entities=True,
            date_from=_date_to_dt(plan.date_filter.start) if plan.date_filter else None,
            date_to=_date_to_dt(plan.date_filter.end) if plan.date_filter else None,
        )
        results = await asyncio.wait_for(self._s6.search_chunks(req), timeout=self._timeout)
        items: list[RetrievedItem] = []
        for r in results:
            trust = DEFAULT_TRUST_WEIGHTS.get(r.source_type, DEFAULT_TRUST_WEIGHTS["default"])
            items.append(
                RetrievedItem.create(
                    item_id=r.chunk_id,
                    item_type=ItemType.chunk,
                    text=r.text,
                    score=r.score,
                    trust_weight=trust,
                    citation_meta=CitationMeta(
                        title=r.title,
                        url=r.url,
                        source_name=r.source_name,
                        published_at=r.published_at,
                        entity_name=None,
                    ),
                    doc_id=_try_uuid(r.doc_id),
                    published_at=r.published_at,
                )
            )
        return items

    async def _fetch_relations(
        self,
        embedding: list[float],
        entity_ids: list[UUID],
    ) -> list[RetrievedItem]:
        results = await asyncio.wait_for(
            self._s7.search_relations(embedding, entity_ids, top_k=15, min_confidence=0.30),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for r in results:
            text = f"{r.subject} {r.relation_type} {r.object}: {r.summary}"
            items.append(
                RetrievedItem.create(
                    item_id=r.relation_id,
                    item_type=ItemType.relation,
                    text=text,
                    score=r.confidence,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["relation"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="Knowledge Graph",
                        published_at=_parse_dt(r.latest_evidence_at),
                        entity_name=r.subject,
                    ),
                    published_at=_parse_dt(r.latest_evidence_at),
                )
            )
        return items

    async def _fetch_graph(self, entity_id: UUID) -> list[RetrievedItem]:
        graph = await asyncio.wait_for(
            self._s7.get_egocentric_graph(entity_id, min_confidence=0.40, limit=30),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for edge in graph.edges:
            text = (
                f"{edge.get('subject', '')} {edge.get('relation_type', '')} "
                f"{edge.get('object', '')}: {edge.get('summary', '')}"
            )
            items.append(
                RetrievedItem.create(
                    item_id=edge.get("relation_id", str(entity_id)),
                    item_type=ItemType.relation,
                    text=text,
                    score=float(edge.get("confidence", 0.5)),
                    trust_weight=DEFAULT_TRUST_WEIGHTS["relation"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="Knowledge Graph",
                        published_at=None,
                        entity_name=edge.get("subject"),
                    ),
                )
            )
        return items

    async def _fetch_claims(
        self,
        entity_ids: list[UUID],
        plan: RetrievalPlan,
    ) -> list[RetrievedItem]:
        date_from: datetime = (
            _date_to_dt(plan.date_filter.start)
            if plan.date_filter and plan.date_filter.start
            else (datetime.now(tz=UTC) - timedelta(days=90))
        )
        date_to: datetime = (
            _date_to_dt(plan.date_filter.end) if plan.date_filter and plan.date_filter.end else datetime.now(tz=UTC)
        )
        results = await asyncio.wait_for(
            self._s7.search_claims(entity_ids, date_from=date_from, date_to=date_to, top_k=15, min_confidence=0.50),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for r in results:
            text = f"{r.claim_type} ({r.polarity}): {r.claim_text}"
            items.append(
                RetrievedItem.create(
                    item_id=r.claim_id,
                    item_type=ItemType.claim,
                    text=text,
                    score=r.extraction_confidence,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["claim"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="NLP Pipeline",
                        published_at=_parse_dt(r.created_at),
                        entity_name=r.subject_entity_id,
                    ),
                    published_at=_parse_dt(r.created_at),
                )
            )
        return items

    async def _fetch_events(
        self,
        entity_ids: list[UUID],
        plan: RetrievalPlan,
    ) -> list[RetrievedItem]:
        date_from_ev: datetime = (
            _date_to_dt(plan.date_filter.start)
            if plan.date_filter and plan.date_filter.start
            else (datetime.now(tz=UTC) - timedelta(days=180))
        )
        date_to_ev: datetime = (
            _date_to_dt(plan.date_filter.end) if plan.date_filter and plan.date_filter.end else datetime.now(tz=UTC)
        )
        results = await asyncio.wait_for(
            self._s7.search_events(entity_ids, date_from=date_from_ev, date_to=date_to_ev, top_k=10),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for r in results:
            text = f"{r.event_type}: {r.event_text}"
            items.append(
                RetrievedItem.create(
                    item_id=r.event_id,
                    item_type=ItemType.event,
                    text=text,
                    score=r.extraction_confidence,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["default"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="Knowledge Graph",
                        published_at=_parse_dt(r.event_date),
                        entity_name=r.subject_entity_id,
                    ),
                    published_at=_parse_dt(r.event_date),
                )
            )
        return items

    async def _fetch_contradictions(self, entity_id: UUID) -> list[RetrievedItem]:
        results = await asyncio.wait_for(
            self._s7.get_contradictions(entity_id, top_k=3),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for r in results:
            sides_text = " vs. ".join(s.get("text", "") for s in r.sides[:2])
            text = f"Contradiction ({r.claim_type}, strength={r.strength:.2f}): {sides_text}"
            items.append(
                RetrievedItem.create(
                    item_id=f"contradiction:{entity_id}:{r.claim_type}",
                    item_type=ItemType.claim,
                    text=text,
                    score=r.strength,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["claim"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="Knowledge Graph",
                        published_at=_parse_dt(r.detected_at),
                        entity_name=str(entity_id),
                    ),
                    published_at=_parse_dt(r.detected_at),
                )
            )
        return items

    async def _fetch_financial(self, ticker: str) -> list[RetrievedItem]:
        instrument_id = await asyncio.wait_for(
            self._s3.find_instrument_by_ticker(ticker),
            timeout=self._timeout,
        )
        if not instrument_id:
            return []
        highlights, _earnings, quote = await asyncio.gather(
            asyncio.wait_for(self._s3.get_fundamentals_highlights(instrument_id), timeout=self._timeout),
            asyncio.wait_for(self._s3.get_earnings(instrument_id), timeout=self._timeout),
            asyncio.wait_for(self._s3.get_quote(instrument_id), timeout=self._timeout),
            return_exceptions=True,
        )

        items: list[RetrievedItem] = []
        if isinstance(highlights, dict) and highlights:
            text = f"Financial highlights for {ticker}: {highlights}"
            items.append(
                RetrievedItem.create(
                    item_id=f"financial:{ticker}:highlights",
                    item_type=ItemType.financial,
                    text=text,
                    score=0.90,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["financial"],
                    citation_meta=CitationMeta(
                        title=f"{ticker} Fundamentals",
                        url=None,
                        source_name="Market Data",
                        published_at=None,
                        entity_name=ticker,
                    ),
                )
            )
        if isinstance(quote, dict) and quote:
            text = f"Latest quote for {ticker}: {quote}"
            items.append(
                RetrievedItem.create(
                    item_id=f"financial:{ticker}:quote",
                    item_type=ItemType.financial,
                    text=text,
                    score=0.85,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["financial"],
                    citation_meta=CitationMeta(
                        title=f"{ticker} Quote",
                        url=None,
                        source_name="Market Data",
                        published_at=None,
                        entity_name=ticker,
                    ),
                )
            )
        return items

    async def _fetch_portfolio(self, request: ChatRequest) -> list[RetrievedItem]:
        ctx = await asyncio.wait_for(
            self._s1.get_portfolio_context(
                request.user_id,
                request.tenant_id,
                self._s1_internal_token,
            ),
            timeout=self._timeout,
        )
        if not ctx:
            return []
        holdings_text = ", ".join(h.get("ticker", "") for h in ctx.holdings[:10])
        watchlist_text = ", ".join(w.get("ticker", "") for w in ctx.watchlist[:10])
        text = f"Portfolio: Holdings: {holdings_text}. Watchlist: {watchlist_text}."
        return [
            RetrievedItem.create(
                item_id=f"portfolio:{request.user_id}",
                item_type=ItemType.financial,
                text=text,
                score=0.80,
                trust_weight=DEFAULT_TRUST_WEIGHTS["financial"],
                citation_meta=CitationMeta(
                    title="My Portfolio",
                    url=None,
                    source_name="Portfolio Service",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _fetch_cypher(self, entity_id: UUID) -> list[RetrievedItem]:
        cypher = "MATCH (e:Entity {id: $id})-[r*1..3]->(n) RETURN n, r, length(r) as hops"
        results = await asyncio.wait_for(
            self._s7.cypher_traverse(cypher, {"id": str(entity_id)}, max_results=30),
            timeout=self._timeout,
        )
        items: list[RetrievedItem] = []
        for i, row in enumerate(results[:10]):
            text = str(row)
            items.append(
                RetrievedItem.create(
                    item_id=f"cypher:{entity_id}:{i}",
                    item_type=ItemType.cypher_path,
                    text=text,
                    score=0.70,
                    trust_weight=DEFAULT_TRUST_WEIGHTS["relation"],
                    citation_meta=CitationMeta(
                        title=None,
                        url=None,
                        source_name="Knowledge Graph (Cypher)",
                        published_at=None,
                        entity_name=str(entity_id),
                    ),
                )
            )
        return items


# ── Helpers ───────────────────────────────────────────────────────────────────


def _try_uuid(value: str | None) -> Any:
    """Parse a UUID string; return None on failure."""
    if not value:
        return None
    try:
        from uuid import UUID

        return UUID(value)
    except (ValueError, AttributeError):
        return None


def _date_to_dt(d: Any) -> datetime:
    """Convert a date to a timezone-aware datetime (midnight UTC)."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string; return None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return None
