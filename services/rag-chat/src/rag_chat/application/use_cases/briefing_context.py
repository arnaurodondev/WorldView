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
    MarketOverview,
    NewsArticleSummary,
    PortfolioSnapshot,
    QuoteSummary,
    WatchlistItem,
)
from rag_chat.application.ports.upstream_clients import ChunkSearchRequest, EnrichedChunkResult
from rag_chat.application.use_cases.brief_diagnostics import (
    compute_context_availability_score,
    emit_context_availability,
    timed_upstream_call,
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
        *,
        use_service_endpoint: bool = False,
    ) -> None:
        self._s1 = s1
        self._s3 = s3
        self._s5 = s5
        self._s6 = s6
        self._s7 = s7
        # PLAN-0094 follow-up: when True, the worker path uses S5's
        # /internal/v1/users/{user_id}/alerts/pending endpoint (service-token
        # auth, user_id in URL). When False (default — handler/on-demand path),
        # the existing /api/v1/alerts/pending endpoint is used (JWT sub scoping).
        # The worker holds a single service-account JWT whose sub doesn't map
        # to a real user, so it cannot rely on JWT-sub scoping.
        self._use_service_endpoint = use_service_endpoint

    # ── Morning briefing context ─────────────────────────────────────────────

    # PLAN-0102 W1 T-W1-02: broad-market tape symbols appended to every batch
    # quote call so we surface overnight-tape direction (SPY/QQQ/VIX) — the
    # data is in S3, the brief never asked for it before.
    _TAPE_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "VIX")

    # PLAN-0102 W1 T-W1-04: macro event types fetched in a SECOND S7 call
    # without entity-scope so Fed FOMC / CPI prints / jobless-claims rows
    # (which carry NO subject_entity_id) actually surface.
    _MACRO_EVENT_TYPES: tuple[str, ...] = ("macro", "economic")
    # Portfolio-scoped event types — kept narrow to avoid the S7 portfolio-
    # entity call swallowing the macro rows we now fetch separately.
    _PORTFOLIO_EVENT_TYPES: tuple[str, ...] = ("earnings", "analyst_action", "corporate")

    # PLAN-0102 W1 T-W1-03: overlap multiplier applied to news whose
    # primary_entity_id intersects the user's held entities. Keeps generic
    # AI news from crowding out NVDA-specific items for a holder of NVDA.
    _NEWS_OVERLAP_MULTIPLIER: float = 1.5

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
        # PLAN-0102 W1 T-W1-01/T-W1-02: we track BOTH the bare instrument-id
        # list (for the S3 batch call) AND the ticker↔instrument_id mapping so
        # we can render per-holding quotes by ticker symbol (the user-facing
        # name) without a second lookup on the formatter side. Tape symbols
        # (SPY/QQQ/VIX) ride the same batch call.
        instrument_ids: list[str] = []
        holding_ticker_to_iid: dict[str, str] = {}
        tape_ticker_to_iid: dict[str, str] = {}
        entity_ids: list[str] = []

        try:
            # PLAN-0099 Wave A: time S1 call + classify outcome for SLO dashboards.
            async with timed_upstream_call("s1_portfolio") as s1_outcome:
                raw_portfolio = await self._s1.get_portfolio_context(
                    UUID(user_id),
                    UUID(tenant_id),
                    x_internal_token=internal_jwt or "",
                )
                if raw_portfolio is None:
                    s1_outcome.mark_empty()
            if raw_portfolio is not None:
                portfolio_snapshot = self._map_portfolio(raw_portfolio, user_id)
                # Collect tickers for S3 batch quotes
                tickers = [h.ticker for h in portfolio_snapshot.holdings if h.ticker]
                holding_ticker_to_iid = await self._resolve_ticker_map(tickers)
                # Collect entity_ids from holdings + watchlist
                entity_ids = self._collect_entity_ids(portfolio_snapshot)
        except Exception:
            log.warning("briefing_s1_failed", user_id=user_id)
            portfolio_failed = True

        # PLAN-0102 W1 T-W1-02: resolve the broad-market tape tickers separately
        # so a portfolio with zero holdings still gets a tape in the brief. Any
        # resolution failure on an individual symbol is logged but does not
        # block the rest — graceful degradation in the spirit of R9.
        try:
            tape_ticker_to_iid = await self._resolve_ticker_map(list(self._TAPE_TICKERS))
        except Exception:
            log.warning("briefing_tape_resolve_failed")

        # Combined instrument_id list for the single S3 batch call.
        instrument_ids = list({*holding_ticker_to_iid.values(), *tape_ticker_to_iid.values()})

        # ── 2. Parallel calls to S3, S5, S6, S7 ─────────────────────────────
        # PLAN-0099 Wave A: each call is wrapped with ``timed_upstream_call`` so
        # latency + outcome land in Prometheus + structlog without changing the
        # parallel-gather shape. ``_timed`` returns a coroutine identical to the
        # original; exceptions propagate exactly as before (gather() captures
        # them via return_exceptions=True).
        news_coro = _timed("s6_news", self._fetch_top_news(internal_jwt=internal_jwt))
        # PLAN-0094 follow-up: worker context uses the service-token endpoint
        # (user_id in URL); handler context uses the existing JWT-sub endpoint.
        if self._use_service_endpoint:
            alerts_inner = self._s5.get_pending_alerts_for_user(
                user_id,
                tenant_id,
                min_severity="medium",
                x_internal_jwt=internal_jwt,
            )
        else:
            alerts_inner = self._s5.get_pending_alerts(
                user_id,
                tenant_id,
                min_severity="medium",
                x_internal_jwt=internal_jwt,
            )
        alerts_coro = _timed("s5_alerts", alerts_inner)
        quotes_inner = self._s3.get_batch_quotes(instrument_ids) if instrument_ids else _empty_quotes()
        quotes_coro = _timed("s3_quotes", quotes_inner)
        # PLAN-0102 W1 T-W1-04: TWO S7 calls — (a) entity-scoped earnings/analyst/
        # corporate events for held names, (b) unscoped macro/economic events
        # (Fed/CPI/jobless) which carry no subject_entity_id and were previously
        # invisible. Both are merged in step 3 and tagged with source_tier so
        # the formatter can group them under separate sections.
        events_portfolio_inner = (
            self._fetch_events(entity_ids, event_types=list(self._PORTFOLIO_EVENT_TYPES))
            if entity_ids
            else _empty_events()
        )
        events_portfolio_coro = _timed("s7_events", events_portfolio_inner)
        events_macro_inner = self._fetch_events(
            entity_ids=[],
            event_types=list(self._MACRO_EVENT_TYPES),
            days=2,
        )
        events_macro_coro = _timed("s7_events_macro", events_macro_inner)

        results = await asyncio.gather(
            news_coro,
            alerts_coro,
            quotes_coro,
            events_portfolio_coro,
            events_macro_coro,
            return_exceptions=True,
        )

        (
            news_result,
            alerts_result,
            quotes_result,
            events_portfolio_result,
            events_macro_result,
        ) = results

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

        # PLAN-0102 W1 T-W1-04: merge portfolio-scoped + macro events; tag each
        # row with its source tier ("portfolio" vs "macro") so the formatter can
        # render them under separate "Earnings/Corporate" vs "Macro Today"
        # headings without re-querying upstream.
        events: list[EventSummary] = []
        if isinstance(events_portfolio_result, BaseException):
            log.warning("briefing_s7_events_failed", error=str(events_portfolio_result))
        else:
            portfolio_events: list[EventSummary] = events_portfolio_result  # type: ignore[assignment]
            events.extend(_tag_event_source_tier(portfolio_events, "portfolio"))
        if isinstance(events_macro_result, BaseException):
            log.warning("briefing_s7_events_macro_failed", error=str(events_macro_result))
        else:
            macro_events: list[EventSummary] = events_macro_result  # type: ignore[assignment]
            events.extend(_tag_event_source_tier(macro_events, "macro"))

        # PLAN-0102 W1 T-W1-03: re-rank news so items whose primary_entity_id
        # overlaps the user's held entities float to the top. The multiplier is
        # additive in effect (existing relevance_score is preserved as the base
        # ordering); we never drop non-overlap items so quiet-day briefs still
        # surface broad signals. Stable sort keeps the original recency tiebreak.
        held_entity_ids: set[str] = set()
        if portfolio_snapshot is not None:
            held_entity_ids = {str(h.entity_id) for h in portfolio_snapshot.holdings if h.entity_id}
        news_articles = _score_news_by_overlap(news_articles, held_entity_ids, self._NEWS_OVERLAP_MULTIPLIER)

        # PLAN-0102 W1 T-W1-01: build a MarketOverview that the formatter can
        # actually render. ``indices`` carries SPY/QQQ/VIX (the tape) and
        # ``holdings`` carries per-holding quote snapshots. Both share the
        # single S3 batch call above; the formatter renders them as separate
        # sections so we never silently drop the data we paid to fetch
        # (the BP-614 anti-pattern).
        market_overview = _build_market_overview(
            quotes_by_iid=quotes,
            holding_ticker_to_iid=holding_ticker_to_iid,
            tape_ticker_to_iid=tape_ticker_to_iid,
        )

        # ── 4. Check if ALL sources failed ───────────────────────────────────
        # A source counts as "failed" if it raised OR returned empty data.
        # Trivially-empty coroutines (no instrument_ids → empty quotes, no
        # entity_ids → empty events) are NOT counted as successes.
        has_any_data = bool(news_articles or active_alerts or quotes or events)
        if not has_any_data and portfolio_failed:
            raise ContextGatheringError(
                "All upstream context sources failed during briefing generation",
            )

        # ── 4b. PLAN-0099 Wave A: emit context-availability score ────────────
        # ``sections_populated`` counts each non-empty section so the formatter
        # downstream cannot quietly drop content without the score reflecting it.
        sections_populated = sum(1 for n in (len(news_articles), len(active_alerts), len(quotes), len(events)) if n > 0)
        availability_score = compute_context_availability_score(
            has_portfolio=portfolio_snapshot is not None,
            news_count=len(news_articles),
            events_count=len(events),
            alerts_count=len(active_alerts),
            sections_populated=sections_populated,
        )
        emit_context_availability(
            score=availability_score,
            has_portfolio=portfolio_snapshot is not None,
            news_count=len(news_articles),
            events_count=len(events),
            alerts_count=len(active_alerts),
            sections_populated=sections_populated,
            user_id=user_id,
        )

        # ── 5. Assemble BriefingContext ──────────────────────────────────────
        return BriefingContext.for_morning(
            user_id=UUID(user_id),
            tenant_id=UUID(tenant_id),
            portfolio=portfolio_snapshot,
            news_articles=news_articles,
            active_alerts=active_alerts,
            quotes=quotes,
            market_overview=market_overview,
            recent_events=events,
            gathered_at=datetime.now(tz=UTC),
            context_availability_score=availability_score,
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

        # S6 entity articles (news)
        coros.append(self._fetch_entity_articles(entity_id))

        # S7 events for this entity
        coros.append(self._fetch_events([entity_id], days=30))

        # S6 ANN chunk search — SEC filings, earnings transcripts, analyst reports.
        # Uses entity_graph.canonical_name as the query so the ANN index can
        # surface semantically relevant sections even without a user query.
        # source_types excludes news (those are covered by _fetch_entity_articles).
        coros.append(self._fetch_entity_chunks(entity_id, entity_graph.canonical_name))

        results = await asyncio.gather(*coros, return_exceptions=True)
        quote_result, fundamentals_result, articles_result, events_result, chunks_result = results

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

        # R9 safe degradation: chunk search failure → empty list, no crash.
        relevant_chunks: list[EnrichedChunkResult] = []
        if isinstance(chunks_result, BaseException):
            log.warning("briefing_chunk_search_failed", entity_id=entity_id, error=str(chunks_result))
        else:
            relevant_chunks = chunks_result  # type: ignore[assignment]

        # ── 5. Assemble BriefingContext ──────────────────────────────────────
        return BriefingContext.for_instrument(
            entity_id=entity_id,
            entity_graph=entity_graph,
            fundamentals=fundamentals,
            news_articles=news_articles,
            active_alerts=[],
            quotes=quotes,
            recent_events=events,
            relevant_chunks=relevant_chunks,
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
        """Resolve ticker symbols to instrument UUIDs (best-effort).

        Kept for back-compat with existing callers that only need the bare
        list. New callers should prefer ``_resolve_ticker_map`` so the link
        from ticker → instrument_id is preserved (PLAN-0102 W1).
        """
        mapping = await self._resolve_ticker_map(tickers)
        return list(mapping.values())

    async def _resolve_ticker_map(self, tickers: list[str]) -> dict[str, str]:
        """Resolve ticker symbols to instrument UUIDs as a ``ticker → iid`` dict.

        PLAN-0102 W1 T-W1-01: the formatter must show "AAPL 195.20" not
        "<uuid> 195.20" — so we preserve the ticker→iid link instead of
        throwing it away. Tickers that fail to resolve are silently skipped;
        the caller (the gatherer) tolerates a partial map and still issues a
        batch quote call for whatever resolved.
        """
        mapping: dict[str, str] = {}
        for ticker in tickers:
            try:
                iid = await self._s3.find_instrument_by_ticker(ticker)
                if iid is not None:
                    mapping[ticker] = str(iid)
            except Exception:
                log.warning("briefing_ticker_resolve_failed", ticker=ticker)
        return mapping

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
        """GET /api/v1/news/top from S6 → list of NewsArticleSummary.

        PLAN-0049 T-C-3-04: ``limit`` raised from 10 → 30. Audit F-B-005 reported
        the dashboard portfolio-news widget only displaying 4 articles; the
        upstream brief was the limiting factor. 30 keeps payload bounded while
        giving downstream surfaces enough to fill multi-row widgets.
        """
        headers: dict[str, str] = {}
        if internal_jwt:
            headers["X-Internal-JWT"] = internal_jwt
        raw = await self._s6._get(
            "/api/v1/news/top",
            params={"hours": 24, "limit": 30, "min_display_score": 0.15},
            extra_headers=headers or None,
        )
        return _map_news_articles(raw.get("articles", []))

    async def _fetch_entity_articles(self, entity_id: str) -> list[NewsArticleSummary]:
        """GET /api/v1/entities/{entity_id}/briefing-articles from S6.

        Uses the /briefing-articles path (not /articles) to bypass the watchlist
        ownership guard in the signals router, which returns 404 for entities not
        on the tenant watchlist.  The briefing use case must fetch articles for any
        entity regardless of watchlist membership.

        PLAN-0049 T-C-3-04: ``limit`` raised from 10 → 30 (matches _fetch_top_news).
        """
        raw = await self._s6._get(
            f"/api/v1/entities/{entity_id}/briefing-articles",
            params={"limit": 30},
        )
        return _map_news_articles(raw.get("articles", []))

    async def _fetch_events(
        self,
        entity_ids: list[str],
        days: int = 7,
        event_types: list[str] | None = None,
    ) -> list[EventSummary]:
        """Search events via S7 for the given entity_ids (and optional types).

        PLAN-0102 W1 T-W1-04: ``event_types`` is forwarded so callers can
        narrow the result set to the portfolio-scoped or macro-scoped slice
        in two separate calls.  ``entity_ids=[]`` is a valid input — used for
        the macro call so Fed/CPI/jobless rows (no subject_entity_id) surface.
        """
        date_from = datetime.now(tz=UTC) - timedelta(days=days)
        uuid_ids = [UUID(eid) for eid in entity_ids]
        results = await self._s7.search_events(
            entity_ids=uuid_ids,
            event_types=event_types,
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

    async def _fetch_entity_chunks(
        self,
        entity_id: str,
        entity_name: str,
    ) -> list[EnrichedChunkResult]:
        """ANN chunk search for an entity — two-stage filtered/unfiltered fallback.

        Stage 1 (filtered): search with entity_ids=[entity_id] so only chunks
        that explicitly mention this entity are returned.  This is the preferred
        result because it prevents generic entity names (e.g. "Capital", "General")
        from pulling in unrelated documents.

        Stage 2 (unfiltered fallback): if the filtered search returns fewer than
        3 results the entity embedding may be too sparse for the HNSW index to
        find enough candidates — e.g. Apple chunks are only ~0.6% of the index.
        In that case we fall back to an unfiltered ANN search using the entity
        name as the query text; the high min_score (0.55) ensures relevance.

        No source_type filter in either stage: HNSW only scores top_k candidates
        globally, so sparse source types (sec_edgar ≈ 2%) never appear in those
        candidates when a WHERE clause eliminates all HNSW candidates first.
        """
        fallback_threshold = 3  # minimum results before we prefer filtered

        # Stage 1: entity-filtered search — avoids cross-entity pollution for
        # generic names like "General" (General Motors) or "Capital" (fund names).
        filtered_request = ChunkSearchRequest(
            query_text=entity_name,
            top_k=12,
            min_score=0.55,
            granularity="chunk",
            include_entities=False,
            search_type="ann",
            entity_ids=[UUID(entity_id)],
        )
        filtered_results = await self._s6.search_chunks(filtered_request)

        if len(filtered_results) >= fallback_threshold:
            # Enough entity-specific chunks found — use them without pollution risk.
            return filtered_results

        # Stage 2: fallback to unfiltered search when entity embeddings are sparse.
        # Logs at debug level so it's visible during tuning without alarming on-call.
        log.debug(
            "entity_chunk_search_fallback_unfiltered",
            entity_id=entity_id,
            filtered_count=len(filtered_results),
            threshold=fallback_threshold,
        )
        unfiltered_request = ChunkSearchRequest(
            query_text=entity_name,
            top_k=12,
            min_score=0.55,
            granularity="chunk",
            include_entities=False,
            search_type="ann",
            # No entity_ids — relies on min_score threshold for relevance.
        )
        return await self._s6.search_chunks(unfiltered_request)

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


def _score_news_by_overlap(
    items: list[NewsArticleSummary],
    held_entity_ids: set[str],
    multiplier: float,
) -> list[NewsArticleSummary]:
    """Re-rank news so items overlapping the user's holdings float to the top.

    PLAN-0102 W1 T-W1-03: We have ``NewsArticleSummary.primary_entity_id`` and
    ``PortfolioSnapshot.holdings[*].entity_id`` already; before this fix we
    NEVER intersected them, so an NVDA holder saw the same generic AI news as
    a KO holder.  Items whose primary entity is in the held set get their
    relevance score multiplied by ``multiplier`` for sort purposes only — the
    on-record ``display_relevance_score`` stays unchanged so downstream
    cards still show the true upstream value.  Items without overlap are
    NEVER dropped — they sink to the back so quiet-day briefs still surface.
    """
    if not items or not held_entity_ids or multiplier <= 1.0:
        return items

    def _sort_key(article: NewsArticleSummary) -> float:
        base = float(article.display_relevance_score or 0.0)
        if article.primary_entity_id and str(article.primary_entity_id) in held_entity_ids:
            return -(base * multiplier)
        return -base

    return sorted(items, key=_sort_key)


def _tag_event_source_tier(events: list[EventSummary], tier: str) -> list[EventSummary]:
    """Return a copy of ``events`` with ``source_tier`` set to ``tier``.

    PLAN-0102 W1 T-W1-04: ``EventSummary`` is frozen so we rebuild each row.
    The formatter reads ``source_tier`` to bucket rows under
    "Earnings / corporate" vs "Macro today" without re-querying upstream.
    """
    if not events:
        return []
    return [
        EventSummary(
            event_id=e.event_id,
            event_type=e.event_type,
            event_subtype=e.event_subtype,
            subject_entity_id=e.subject_entity_id,
            event_date=e.event_date,
            event_text=e.event_text,
            extraction_confidence=e.extraction_confidence,
            source_tier=tier,
        )
        for e in events
    ]


def _build_market_overview(
    *,
    quotes_by_iid: dict[str, QuoteSummary],
    holding_ticker_to_iid: dict[str, str],
    tape_ticker_to_iid: dict[str, str],
) -> MarketOverview:
    """Build a fully-populated MarketOverview from the single S3 batch call.

    PLAN-0102 W1 T-W1-01 / T-W1-02 (BP-614): the gatherer used to fetch
    ``quotes_by_iid`` and feed it directly into the context, but the
    formatter only rendered ``market_overview.sector_performance`` — so the
    per-holding quotes were silently dropped.  This helper repackages the
    batch into a ``MarketOverview`` with ``indices`` (SPY/QQQ/VIX tape) and
    ``holdings`` (per-holding snapshots) — both lists carry the TICKER
    SYMBOL in ``QuoteSummary.instrument_id`` so the formatter can render
    "AAPL 195.20" directly with no second lookup.
    """

    def _tag(symbol: str, iid: str) -> QuoteSummary | None:
        raw = quotes_by_iid.get(iid)
        if raw is None:
            return None
        return QuoteSummary(
            instrument_id=symbol,  # carries the ticker (display name) — NOT the iid
            last=raw.last,
            bid=raw.bid,
            ask=raw.ask,
            volume=raw.volume,
            timestamp=raw.timestamp,
        )

    indices: list[QuoteSummary] = []
    for symbol, iid in tape_ticker_to_iid.items():
        tagged = _tag(symbol, iid)
        if tagged is not None:
            indices.append(tagged)

    holdings: list[QuoteSummary] = []
    for symbol, iid in holding_ticker_to_iid.items():
        tagged = _tag(symbol, iid)
        if tagged is not None:
            holdings.append(tagged)

    return MarketOverview(
        sector_performance={},
        top_gainers=[],
        top_losers=[],
        indices=indices,
        holdings=holdings,
    )


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


async def _timed(source: str, coro: Any) -> Any:
    """Await ``coro`` inside a ``timed_upstream_call`` so latency/outcome land
    in Prometheus + structlog.

    Returned value is whatever the coroutine produced.  Empty collections /
    empty dicts mark the outcome as ``empty`` so dashboards distinguish a
    healthy zero-result day from a transient outage.  Exceptions propagate
    unchanged so ``asyncio.gather(return_exceptions=True)`` still captures
    them.
    """
    async with timed_upstream_call(source) as outcome:
        result = await coro
        if not result:
            outcome.mark_empty()
        return result


async def _empty_quotes() -> dict[str, QuoteSummary]:
    """Coroutine that returns an empty quotes dict (for asyncio.gather)."""
    return {}


async def _empty_events() -> list[EventSummary]:
    """Coroutine that returns an empty events list (for asyncio.gather)."""
    return []


async def _empty_dict() -> dict[str, Any]:
    """Coroutine that returns an empty dict (for asyncio.gather)."""
    return {}
