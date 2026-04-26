"""BriefingContextGatherer — orchestrates parallel HTTP calls to gather briefing context.

Gathers context from S1 (portfolio), S3 (market data), S5 (alerts),
S6 (NLP pipeline / news), and S7 (knowledge graph / events) to assemble
a ``BriefingContext`` value object for prompt rendering.

Follows R9 safe degradation: individual source failures log warnings
and fall back to empty defaults. Only raises if *all* sources fail AND
the portfolio is unavailable (no useful context to generate from).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.application.models.briefing_context import (
    AlertSummary,
    BriefingContext,
    EntityGraphSnapshot,
    EventSummary,
    FundamentalsSummary,
    HoldingItem,
    NewsArticleSummary,
    PortfolioSnapshot,
    QuoteSummary,
    WatchlistItem,
)
from rag_chat.domain.errors import ContextGatheringError, EntityNotFoundError

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import PortfolioContext
    from rag_chat.infrastructure.clients.s1_client import S1Client
    from rag_chat.infrastructure.clients.s3_client import S3Client
    from rag_chat.infrastructure.clients.s5_client import S5Client
    from rag_chat.infrastructure.clients.s6_client import S6Client
    from rag_chat.infrastructure.clients.s7_client import S7Client

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefingContextGatherer:
    """Orchestrate parallel upstream calls to build a ``BriefingContext``.

    Each upstream failure is swallowed (empty default used) so that a partial
    context can still produce a useful briefing.  Raises ``ContextGatheringError``
    only when **every** source fails and no portfolio data is available.
    """

    def __init__(
        self,
        s1: S1Client,
        s3: S3Client,
        s5: S5Client,
        s6: S6Client,
        s7: S7Client,
    ) -> None:
        self._s1 = s1
        self._s3 = s3
        self._s5 = s5
        self._s6 = s6
        self._s7 = s7

    # ── Morning briefing context ─────────────────────────────────────────────

    async def gather_morning_context(
        self,
        user_id: str,
        tenant_id: str,
        internal_jwt: str | None = None,
    ) -> BriefingContext:
        """Gather all context needed for a morning market briefing.

        1. Fetch portfolio from S1 (determines tickers + entity_ids for parallel calls)
        2. Fire parallel calls to S3 (quotes), S5 (alerts), S6 (news), S7 (events)
        3. Map raw responses to typed value objects
        4. Assemble into ``BriefingContext.for_morning()``

        Raises
        ------
            ContextGatheringError: All upstream sources failed and no portfolio data.

        """
        # ── 1. Portfolio from S1 ─────────────────────────────────────────────
        portfolio_snapshot: PortfolioSnapshot | None = None
        portfolio_failed = False
        instrument_ids: list[str] = []
        entity_ids: list[str] = []

        try:
            raw_portfolio = await self._s1.get_portfolio_context(
                UUID(user_id),
                UUID(tenant_id),
                x_internal_token=internal_jwt or "",
            )
            if raw_portfolio is not None:
                portfolio_snapshot = self._map_portfolio(raw_portfolio, user_id)
                # Collect tickers for S3 batch quotes
                tickers = [h.ticker for h in portfolio_snapshot.holdings if h.ticker]
                instrument_ids = await self._resolve_tickers(tickers)
                # Collect entity_ids from holdings + watchlist
                entity_ids = self._collect_entity_ids(portfolio_snapshot)
        except Exception:
            log.warning("briefing_s1_failed", user_id=user_id)
            portfolio_failed = True

        # ── 2. Parallel calls to S3, S5, S6, S7 ─────────────────────────────
        news_coro = self._fetch_top_news(internal_jwt=internal_jwt)
        alerts_coro = self._s5.get_pending_alerts(
            user_id,
            tenant_id,
            min_severity="medium",
            x_internal_jwt=internal_jwt,
        )
        quotes_coro = self._s3.get_batch_quotes(instrument_ids) if instrument_ids else _empty_quotes()
        events_coro = self._fetch_events(entity_ids) if entity_ids else _empty_events()

        results = await asyncio.gather(
            news_coro,
            alerts_coro,
            quotes_coro,
            events_coro,
            return_exceptions=True,
        )

        news_result, alerts_result, quotes_result, events_result = results

        # ── 3. Map results (use empty defaults on exception) ─────────────────
        news_articles: list[NewsArticleSummary] = []
        if isinstance(news_result, BaseException):
            log.warning("briefing_s6_news_failed", error=str(news_result))
        else:
            news_articles = news_result  # type: ignore[assignment]

        active_alerts: list[AlertSummary] = []
        if isinstance(alerts_result, BaseException):
            log.warning("briefing_s5_alerts_failed", error=str(alerts_result))
        else:
            active_alerts = alerts_result  # type: ignore[assignment]

        quotes: dict[str, QuoteSummary] = {}
        if isinstance(quotes_result, BaseException):
            log.warning("briefing_s3_quotes_failed", error=str(quotes_result))
        else:
            quotes = quotes_result  # type: ignore[assignment]

        events: list[EventSummary] = []
        if isinstance(events_result, BaseException):
            log.warning("briefing_s7_events_failed", error=str(events_result))
        else:
            events = events_result  # type: ignore[assignment]

        # ── 4. Check if ALL sources failed ───────────────────────────────────
        # A source counts as "failed" if it raised OR returned empty data.
        # Trivially-empty coroutines (no instrument_ids → empty quotes, no
        # entity_ids → empty events) are NOT counted as successes.
        has_any_data = bool(news_articles or active_alerts or quotes or events)
        if not has_any_data and portfolio_failed:
            raise ContextGatheringError(
                "All upstream context sources failed during briefing generation",
            )

        # ── 5. Assemble BriefingContext ──────────────────────────────────────
        return BriefingContext.for_morning(
            user_id=UUID(user_id),
            tenant_id=UUID(tenant_id),
            portfolio=portfolio_snapshot,
            news_articles=news_articles,
            active_alerts=active_alerts,
            quotes=quotes,
            recent_events=events,
            gathered_at=datetime.now(tz=UTC),
        )

    # ── Instrument briefing context ──────────────────────────────────────────

    async def gather_instrument_context(
        self,
        entity_id: str,
    ) -> BriefingContext:
        """Gather context for an instrument-focused briefing.

        1. Fetch egocentric graph from S7 (provides entity metadata + ticker)
        2. Resolve ticker to instrument_id via S3
        3. Parallel calls: S3 quote, S3 fundamentals, S6 articles, S7 events
        4. Assemble into ``BriefingContext.for_instrument()``

        Raises
        ------
            EntityNotFoundError: Entity graph is empty (entity does not exist).

        """
        # ── 1. Entity graph from S7 ──────────────────────────────────────────
        raw_graph = await self._s7.get_egocentric_graph(
            UUID(entity_id),
            min_confidence=0.3,
            limit=20,
        )
        if not raw_graph.nodes:
            raise EntityNotFoundError(f"Entity {entity_id} not found in knowledge graph")

        entity_graph = self._map_entity_graph(raw_graph, entity_id)

        # ── 2. Resolve ticker ────────────────────────────────────────────────
        ticker = entity_graph.ticker
        instrument_id: UUID | None = None
        if ticker:
            instrument_id = await self._s3.find_instrument_by_ticker(ticker)

        # ── 3. Parallel calls ────────────────────────────────────────────────
        coros: list[Any] = []

        # S3 quote + fundamentals (only if we have an instrument_id)
        if instrument_id:
            coros.append(self._s3.get_quote(instrument_id))
            coros.append(self._s3.get_fundamentals_highlights(instrument_id))
        else:
            coros.append(_empty_dict())
            coros.append(_empty_dict())

        # S6 entity articles
        coros.append(self._fetch_entity_articles(entity_id))

        # S7 events for this entity
        coros.append(self._fetch_events([entity_id], days=30))

        results = await asyncio.gather(*coros, return_exceptions=True)
        quote_result, fundamentals_result, articles_result, events_result = results

        # ── 4. Map results ───────────────────────────────────────────────────
        quote: QuoteSummary | None = None
        quotes: dict[str, QuoteSummary] = {}
        if not isinstance(quote_result, BaseException) and quote_result and instrument_id:
            try:
                quote = QuoteSummary(
                    instrument_id=str(instrument_id),
                    last=quote_result.get("last") or quote_result.get("close"),
                    bid=quote_result.get("bid"),
                    ask=quote_result.get("ask"),
                    volume=int(quote_result["volume"]) if quote_result.get("volume") is not None else None,
                    timestamp=(
                        datetime.fromisoformat(str(quote_result["timestamp"]))
                        if "timestamp" in quote_result
                        else datetime.now(tz=UTC)
                    ),
                )
                quotes[str(instrument_id)] = quote
            except (KeyError, ValueError, TypeError):
                log.warning("briefing_s3_quote_parse_failed", entity_id=entity_id)

        fundamentals: FundamentalsSummary | None = None
        if not isinstance(fundamentals_result, BaseException) and fundamentals_result and instrument_id:
            fundamentals = FundamentalsSummary(
                instrument_id=str(instrument_id),
                data=fundamentals_result,
            )

        news_articles: list[NewsArticleSummary] = []
        if isinstance(articles_result, BaseException):
            log.warning("briefing_s6_articles_failed", entity_id=entity_id, error=str(articles_result))
        else:
            news_articles = articles_result  # type: ignore[assignment]

        events: list[EventSummary] = []
        if isinstance(events_result, BaseException):
            log.warning("briefing_s7_events_failed", entity_id=entity_id, error=str(events_result))
        else:
            events = events_result  # type: ignore[assignment]

        # ── 5. Assemble BriefingContext ──────────────────────────────────────
        return BriefingContext.for_instrument(
            entity_id=entity_id,
            entity_graph=entity_graph,
            fundamentals=fundamentals,
            news_articles=news_articles,
            active_alerts=[],
            quotes=quotes,
            recent_events=events,
            gathered_at=datetime.now(tz=UTC),
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _map_portfolio(self, raw: PortfolioContext, user_id: str) -> PortfolioSnapshot:
        """Map a raw ``PortfolioContext`` NamedTuple to a ``PortfolioSnapshot`` VO."""
        holdings: list[HoldingItem] = []
        for h in raw.holdings:
            holdings.append(
                HoldingItem(
                    ticker=h.get("ticker") or h.get("symbol"),
                    entity_id=_safe_uuid(h.get("entity_id")),
                    canonical_name=h.get("canonical_name") or h.get("name"),
                    quantity=Decimal(str(h.get("quantity", 0))),
                    current_weight=float(h.get("weight", h.get("current_weight", 0))),
                ),
            )

        watchlist: list[WatchlistItem] = []
        for w in raw.watchlist:
            watchlist.append(
                WatchlistItem(
                    ticker=w.get("ticker") or w.get("symbol"),
                    entity_id=_safe_uuid(w.get("entity_id")),
                    canonical_name=w.get("canonical_name") or w.get("name"),
                ),
            )

        return PortfolioSnapshot(
            user_id=UUID(user_id),
            holdings=holdings,
            watchlist=watchlist,
            total_positions=raw.total_positions,
        )

    async def _resolve_tickers(self, tickers: list[str]) -> list[str]:
        """Resolve ticker symbols to instrument UUIDs (best-effort)."""
        instrument_ids: list[str] = []
        for ticker in tickers:
            try:
                iid = await self._s3.find_instrument_by_ticker(ticker)
                if iid is not None:
                    instrument_ids.append(str(iid))
            except Exception:
                log.warning("briefing_ticker_resolve_failed", ticker=ticker)
        return instrument_ids

    def _collect_entity_ids(self, portfolio: PortfolioSnapshot) -> list[str]:
        """Extract all unique entity_ids from holdings and watchlist."""
        ids: set[str] = set()
        for h in portfolio.holdings:
            if h.entity_id:
                ids.add(str(h.entity_id))
        for w in portfolio.watchlist:
            if w.entity_id:
                ids.add(str(w.entity_id))
        return list(ids)

    async def _fetch_top_news(self, *, internal_jwt: str | None = None) -> list[NewsArticleSummary]:
        """GET /api/v1/news/top from S6 → list of NewsArticleSummary."""
        headers: dict[str, str] = {}
        if internal_jwt:
            headers["X-Internal-JWT"] = internal_jwt
        raw = await self._s6._get(
            "/api/v1/news/top",
            params={"hours": 24, "limit": 10, "min_display_score": 0.3},
            extra_headers=headers or None,
        )
        return _map_news_articles(raw.get("articles", []))

    async def _fetch_entity_articles(self, entity_id: str) -> list[NewsArticleSummary]:
        """GET /api/v1/entities/{entity_id}/articles from S6."""
        raw = await self._s6._get(
            f"/api/v1/entities/{entity_id}/articles",
            params={"limit": 10},
        )
        return _map_news_articles(raw.get("articles", []))

    async def _fetch_events(
        self,
        entity_ids: list[str],
        days: int = 7,
    ) -> list[EventSummary]:
        """Search events via S7 for the given entity_ids."""
        date_from = datetime.now(tz=UTC) - timedelta(days=days)
        uuid_ids = [UUID(eid) for eid in entity_ids]
        results = await self._s7.search_events(
            entity_ids=uuid_ids,
            date_from=date_from,
        )
        return [
            EventSummary(
                event_id=UUID(str(e.event_id)),
                event_type=e.event_type,
                event_subtype=e.event_subtype,
                subject_entity_id=UUID(str(e.subject_entity_id)) if e.subject_entity_id else UUID(int=0),
                event_date=(datetime.fromisoformat(str(e.event_date)) if e.event_date else None),
                event_text=e.event_text,
                extraction_confidence=e.extraction_confidence,
            )
            for e in results
        ]

    def _map_entity_graph(
        self,
        raw: Any,
        entity_id: str,
    ) -> EntityGraphSnapshot:
        """Map an ``EgocentricGraph`` to an ``EntityGraphSnapshot`` VO."""
        # Find the center node to extract name, type, ticker
        center_node: dict[str, Any] = {}
        for node in raw.nodes:
            if str(node.get("entity_id", "")) == entity_id:
                center_node = node
                break
        if not center_node and raw.nodes:
            center_node = raw.nodes[0]

        relationships: list[dict[str, Any]] = []
        for edge in raw.edges:
            relationships.append(
                {
                    "relation_type": edge.get("relation_type", ""),
                    "target_entity_id": edge.get("target", edge.get("object", "")),
                    "target_name": edge.get("target_name", edge.get("object_name", "")),
                    "confidence": edge.get("confidence", 0.0),
                },
            )

        return EntityGraphSnapshot(
            entity_id=entity_id,
            canonical_name=center_node.get("canonical_name", "Unknown"),
            entity_type=center_node.get("entity_type", "unknown"),
            ticker=center_node.get("ticker"),
            relationships=relationships,
        )


# ── Module-level helpers ─────────────────────────────────────────────────────


def _safe_uuid(value: Any) -> UUID | None:
    """Parse a UUID from a string/UUID, returning None on failure."""
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _map_news_articles(raw_articles: list[dict[str, Any]] | Any) -> list[NewsArticleSummary]:
    """Map raw API article dicts to NewsArticleSummary VOs (defensive)."""
    if not isinstance(raw_articles, list):
        return []
    articles: list[NewsArticleSummary] = []
    for a in raw_articles:
        try:
            articles.append(
                NewsArticleSummary(
                    article_id=UUID(str(a.get("article_id", a.get("id", a.get("doc_id", UUID(int=0)))))),
                    title=str(a.get("title", "")),
                    url=a.get("url"),
                    published_at=(datetime.fromisoformat(str(a["published_at"])) if a.get("published_at") else None),
                    source_type=a.get("source_type"),
                    display_relevance_score=float(a.get("display_relevance_score", 0.0)),
                    market_impact_score=(
                        float(a["market_impact_score"]) if a.get("market_impact_score") is not None else None
                    ),
                    primary_entity_id=_safe_uuid(a.get("primary_entity_id")),
                    primary_entity_name=a.get("primary_entity_name"),
                ),
            )
        except (KeyError, ValueError, TypeError):
            continue
    return articles


async def _empty_quotes() -> dict[str, QuoteSummary]:
    """Coroutine that returns an empty quotes dict (for asyncio.gather)."""
    return {}


async def _empty_events() -> list[EventSummary]:
    """Coroutine that returns an empty events list (for asyncio.gather)."""
    return []


async def _empty_dict() -> dict[str, Any]:
    """Coroutine that returns an empty dict (for asyncio.gather)."""
    return {}
