"""Composed endpoints for portfolio-centric pages.

- ``get_portfolio_bundle``   — initial portfolio page composite (PLAN-0070 C-1).
- ``get_watchlist_insights`` — watchlist movers + sectors + news linkage
  (PLAN-0050 Wave B / T-B-2-01).

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from api_gateway.clients.base import (
    DownstreamError,
    ServiceClients,
    _checked_get,
    logger,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx


async def get_portfolio_bundle(
    clients: ServiceClients,
    portfolio_id: str,
    *,
    make_headers: Callable[[], dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    overall_timeout_s: float = 25.0,
) -> dict[str, Any]:
    """Compose portfolio page data in a single round-trip (PLAN-0070 C-1).

    Returns all data needed for the portfolio page initial load:
      - portfolio: portfolio metadata (GET /api/v1/portfolios/{id})
      - holdings: holdings list (GET /api/v1/holdings/{id})
      - transactions: recent 30 transactions (GET /api/v1/portfolios/{id}/transactions)
      - value_history: equity curve data (GET /api/v1/portfolios/{id}/value-history)

    WHY only 4 legs (not 7 as originally specced in PLAN-0070):
      - performance, risk-metrics: S9 composition endpoints that internally fan out to
        S3 (OHLCV) + S1 (holdings). Calling them from inside another composition creates
        recursive HTTP overhead and JTI replay risk. Bundle the raw data instead.
      - allocation: no S1 endpoint exists; computed client-side from holdings + overviews.
    Each downstream call gets a fresh JWT via the make_headers() factory so
    InternalJWTMiddleware's JTI replay detection accepts the parallel fan-out.

    Uses asyncio.gather() so all 4 legs fly concurrently. _safe() wraps each
    call to degrade to None on failure — _meta.partial=True when any leg fails.
    Wrapped in asyncio.wait_for(overall_timeout_s) for hang protection.
    """

    def _h() -> dict[str, str]:
        # WHY factory per call: each downstream request needs a fresh JWT with a
        # unique JTI so InternalJWTMiddleware's replay detection doesn't reject
        # any of the parallel calls (see _auth_headers comment in proxy.py).
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe(path: str, **kwargs: Any) -> dict[str, Any] | None:
        # WHY broad except: degrade to None on any failure (DownstreamError,
        # httpx network errors, parse errors). Partial data is better than a
        # 500 — the frontend renders the available legs and shows "—" for nulls.
        try:
            return await _checked_get(clients.portfolio, "portfolio", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("portfolio_bundle_leg_failed", leg=path, exc_info=True)
            return None

    async def _compose() -> dict[str, Any]:
        # Fan-out: all 4 legs fly concurrently. return_exceptions=False is safe
        # because _safe() already catches all exceptions and returns None.
        (
            portfolio_data,
            holdings_data,
            transactions_data,
            value_history_data,
        ) = await asyncio.gather(
            _safe(f"/api/v1/portfolios/{portfolio_id}"),
            _safe(f"/api/v1/holdings/{portfolio_id}"),
            _safe(f"/api/v1/portfolios/{portfolio_id}/transactions", params={"limit": 30}),
            _safe(f"/api/v1/portfolios/{portfolio_id}/value-history", params={"period": "1Y"}),
        )

        legs_failed = sum(
            1 for leg in [portfolio_data, holdings_data, transactions_data, value_history_data] if leg is None
        )

        return {
            "portfolio_id": portfolio_id,
            "portfolio": portfolio_data,
            "holdings": holdings_data,
            "transactions": transactions_data,
            "value_history": value_history_data,
            # WHY _meta: a leading underscore keeps this field visually distinct
            # from the domain payload fields. Pydantic model uses extra="allow"
            # so it passes through to the response without needing a named field.
            "_meta": {"partial": legs_failed > 0, "legs_failed": legs_failed},
        }

    try:
        return await asyncio.wait_for(_compose(), timeout=overall_timeout_s)
    except TimeoutError:
        # Return a minimal partial bundle rather than a 504 — at least the
        # portfolio_id is present so the frontend can show a skeleton + retry.
        return {
            "portfolio_id": portfolio_id,
            "portfolio": None,
            "holdings": None,
            "transactions": None,
            "value_history": None,
            "_meta": {"partial": True, "legs_failed": 4, "timed_out": True},
        }


async def get_watchlist_insights(
    clients: ServiceClients,
    watchlist_id: str,
    *,
    make_headers: Callable[[], dict[str, str]],
    member_overview_cap: int = 25,
    news_lookback_hours: int = 24,
) -> dict[str, Any]:
    """Composite insights for a single watchlist (PLAN-0050 T-B-2-01).

    Returns one payload that combines members, live quotes, sector breakdown,
    24h news linkage, and pending alerts — replacing the WatchlistMoversWidget's
    prior 4-query fan-out (S1 members, S3 quotes, S3 overviews per member, S6
    news, S10 alerts) with a single round-trip from the frontend's perspective.

    Why a composite (not 5 frontend hooks):
      - Cuts dashboard initial-load round-trips by ~80% for users with a
        non-trivial watchlist (10+ tickers ⇒ 11 requests collapse to 1).
      - Lets the gateway dedupe overview lookups across members that share a
        sector and short-circuit the news/alert filters once we know the
        member set — the browser cannot do either as cheaply.
      - Keeps the frontend free of any cross-service JOIN logic, matching
        ADR-F-XX (frontend talks only to S9; never composes downstream data).

    Why best-effort sub-calls (each downstream wrapped in _safe-style try/except):
      - A flaky news service must not break the dashboard's gainers/losers
        list. Each enrichment degrades gracefully to an empty default so the
        primary information (movers) always renders.

    Response shape (frontend `WatchlistInsightsResponse` type — see
    apps/worldview-web/types/api.ts):
      {
        "watchlist_id": str,
        "members_count": int,
        "movers": [
          {
            "instrument_id", "ticker", "name", "sector", "price",
            "change_pct", "news_count_24h", "has_active_alert",
            "top_news_title": str | None,
            "top_news_url": str | None
          }
        ],
        "weighted_return_1d": float | None,    # equal-weight avg over members with quotes
        "sectors": [ { "sector": str, "weight": float, "count": int } ],
        "biggest_news": { … } | None,          # highest-impact article touching any member
        "alerts_count": int                    # count of pending alerts that match members
      }

    T-A-1-01: The entire composition is wrapped in asyncio.wait_for(15s) so a
    single sluggish downstream (S1 members / S3 quotes / S6 news) cannot hang
    the dashboard widget indefinitely.  A 15s budget is generous for this
    composition; if it trips, the cluster is under serious load and a 504 is
    the correct signal to the frontend.
    """
    from fastapi import HTTPException

    def _h() -> dict[str, str]:
        return make_headers()

    async def _safe_get(
        client: httpx.AsyncClient,
        service: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Best-effort GET — returns {} on any DownstreamError."""
        try:
            return await _checked_get(client, service, path, headers=_h(), **kwargs)
        except DownstreamError:
            return {}

    async def _compose() -> dict[str, Any]:
        # T-A-1-01: entire composition wrapped here so asyncio.wait_for(15s)
        # can cancel the whole fan-out if any leg stalls indefinitely.

        # ── 1. Members + news + alerts in parallel ─────────────────────────────────
        # WHY parallel: members controls the rest of the composition, but news +
        # alerts are watchlist-agnostic until we know the member set, so we can
        # speculatively fetch the global lists in the same window. We filter by
        # member identity once members resolves.
        #
        # F-QA-01 fix: members MUST use _checked_get (not _safe_get). S1 enforces
        # ownership on /watchlists/{id}/members — a 403/404 from S1 means "this is
        # not your watchlist (or it doesn't exist)". The prior _safe_get swallowed
        # those errors and returned an empty 200, which is BOTH a correctness bug
        # (user sees their own watchlist as empty) AND a contract leak (the
        # gateway silently overrides S1's permission decision). Best-effort policy
        # is correct only for ENRICHMENT sub-calls (news/alerts/quotes/overviews).
        async def _members() -> dict[str, Any]:
            return await _checked_get(
                clients.portfolio,
                "portfolio",
                f"/api/v1/watchlists/{watchlist_id}/members",
                headers=_h(),
            )

        members_raw, news_raw, alerts_raw = await asyncio.gather(
            _members(),
            # 30 articles is enough to find a few hits for a typical 5-25-ticker
            # watchlist while staying within the S6 endpoint's healthy range.
            _safe_get(clients.nlp_pipeline, "nlp-pipeline", "/api/v1/news/top", params={"limit": 30}),
            _safe_get(clients.alert, "alert", "/api/v1/alerts/pending", params={"limit": 50}),
        )

        members: list[dict[str, Any]] = members_raw.get("members") or []
        # Filter to members with a resolved instrument_id — matches the widget's
        # client-side filter so we never compute insights against unresolved rows.
        resolved_members = [m for m in members if m.get("instrument_id")]
        members_count = len(resolved_members)
        instrument_ids = [str(m["instrument_id"]) for m in resolved_members]
        entity_ids = {str(m.get("entity_id")) for m in resolved_members if m.get("entity_id")}

        # ── 2. Per-member quote + overview (parallel, capped) ──────────────────────
        # WHY cap at 25: users with a 100-symbol watchlist would otherwise fan out
        # 200 downstream requests. The widget renders only top-5 gainers + losers,
        # so 25 is more than enough to find the extremes without amplifying load.
        capped_ids = instrument_ids[:member_overview_cap]

        async def _quote(iid: str) -> dict[str, Any]:
            # F-Q1-02 fix (PLAN-0050 QA iter-1): switch from the legacy internal
            # QuoteResponse endpoint (/api/v1/quotes/{iid}) to the PriceSnapshot
            # endpoint (/internal/v1/price/{iid}).
            #
            # WHY: the legacy endpoint returns {last, bid, ask, volume, timestamp}
            # which has NO change_pct field.  Every mover was showing change_pct=null
            # because quote.get("change_pct") always returned None.  The PriceSnapshot
            # endpoint is the authoritative price source for S9 (used by the /v1/quotes
            # proxy) and returns {price, price_change, price_change_pct, ...}.
            #
            # WHY not call S9's own /v1/quotes/{iid}: that would add a loopback HTTP
            # hop (gateway → gateway).  Calling S3 directly via the market_data client
            # is cheaper and already the pattern used by the /v1/quotes proxy route.
            #
            # F-Q1-08 closed by this same fix: the stale `last` price from the legacy
            # quote table (e.g. NVDA 199.64 vs 209.53) came from reading the wrong
            # field.  PriceSnapshot's `price` field is resolved via the freshness chain
            # (FRESH_QUOTE → BULK_QUOTE → INTRADAY → DAILY_CLOSE → STALE) — same
            # authoritative source that the instrument detail page uses.
            snap = await _safe_get(clients.market_data, "market-data", f"/internal/v1/price/{iid}")
            if not snap:
                return {}
            # Map PriceSnapshot fields → the shape the composer reads below:
            #   price       ← snap["price"]          (best available price string)
            #   change_pct  ← snap["price_change_pct"] (signed % change string or None)
            price_str = snap.get("price")
            pct_str = snap.get("price_change_pct")
            try:
                price = float(price_str) if price_str is not None else None
            except (ValueError, TypeError):
                price = None
            try:
                change_pct = float(pct_str) if pct_str is not None else None
            except (ValueError, TypeError):
                change_pct = None
            # Return a normalised dict that uses the same field names the loop below
            # reads so we do not have to touch the per-member construction block.
            return {"price": price, "change_pct": change_pct}

        async def _overview(iid: str) -> dict[str, Any]:
            # Just the instrument record gives us GICS sector — the per-member
            # `getCompanyOverview` would also fetch fundamentals + OHLCV which we
            # don't need here. Saves ~3x the per-member load.
            return await _safe_get(
                clients.market_data,
                "market-data",
                f"/api/v1/instruments/lookup?id={iid}&extra_info=true",
            )

        quote_results, overview_results = await asyncio.gather(
            asyncio.gather(*[_quote(iid) for iid in capped_ids]),
            asyncio.gather(*[_overview(iid) for iid in capped_ids]),
        )

        # ── 3. Index news + alerts by entity for O(1) per-member lookup ────────────
        # WHY entity_id (not instrument_id): articles + alerts are tagged with KG
        # entity_id (ADR-F-12). Matching against instrument_id would silently miss
        # everything because instrument_id ≠ entity_id by design.
        news_articles = news_raw.get("articles") or []
        # Cutoff for the "news_count_24h" badge. The frontend cares about
        # "did this name make the news today?" — older articles inflate the count.
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(tz=UTC) - timedelta(hours=news_lookback_hours)
        news_by_entity: dict[str, list[dict[str, Any]]] = {}
        for art in news_articles:
            # F-QA2-01 fix: S6's RankedArticleResponse emits `primary_entity_id`
            # (singular, optional UUID) — NOT a `entity_ids` list. The prior
            # implementation read a non-existent field, so news_by_entity was
            # always empty and every member's news_count_24h was 0 in
            # production. We also accept a fallback `entity_ids` list shape
            # so tests and any future schema change that introduces multiple
            # tagged entities still flow through.
            primary_eid = art.get("primary_entity_id")
            ents: list[str] = []
            if isinstance(primary_eid, str) and primary_eid:
                ents.append(primary_eid)
            legacy = art.get("entity_ids")
            if isinstance(legacy, list):
                ents.extend(str(x) for x in legacy if x)
            if not ents:
                continue
            # Apply the 24h cutoff. published_at is ISO 8601 — best-effort parse.
            published = art.get("published_at")
            in_window = True
            if isinstance(published, str):
                try:
                    # Accept both with/without timezone — assume UTC if naive.
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    in_window = ts >= cutoff
                except ValueError:
                    in_window = True  # malformed date → keep it
            if not in_window:
                continue
            for eid in ents:
                news_by_entity.setdefault(eid, []).append(art)

        # Pending alerts indexed by entity_id (each alert may reference one).
        alerts_by_entity: dict[str, int] = {}
        pending_alerts = alerts_raw.get("alerts") or []
        for alert in pending_alerts:
            eid = alert.get("entity_id")
            if eid:
                alerts_by_entity[str(eid)] = alerts_by_entity.get(str(eid), 0) + 1

        # ── 4. Build per-member rows ───────────────────────────────────────────────
        # We zip the parallel quote + overview results back to the resolved-member
        # list. Anything past member_overview_cap gets a price-only row (no
        # sector / news / alert lookup) — those rows still render but without
        # enrichment, which is the right tradeoff for very large watchlists.
        movers_out: list[dict[str, Any]] = []
        for idx, member in enumerate(resolved_members):
            iid = str(member["instrument_id"])
            ticker = member.get("ticker") or "—"
            name = member.get("name") or ticker
            eid = str(member.get("entity_id") or "")

            if idx < len(quote_results):
                quote = quote_results[idx]
                overview = overview_results[idx]
                # F-Q1-02: _quote() now returns {"price": float|None, "change_pct": float|None}
                # normalised from PriceSnapshot (not the legacy QuoteResponse {last, bid, ask}).
                last = quote.get("price")
                change_pct = quote.get("change_pct")
                sector = (overview or {}).get("gics_sector") or member.get("sector")
            else:
                last = None
                change_pct = None
                sector = member.get("sector")

            # Top news for this member, if any. We pick the highest impact_score.
            member_news = news_by_entity.get(eid, []) if eid else []
            member_news_sorted = sorted(
                member_news,
                key=lambda a: float(a.get("market_impact_score") or a.get("display_relevance_score") or 0.0),
                reverse=True,
            )
            top_news = member_news_sorted[0] if member_news_sorted else None

            movers_out.append(
                {
                    "instrument_id": iid,
                    "entity_id": eid or None,
                    "ticker": ticker,
                    "name": name,
                    "sector": sector,
                    # F-Q1-02: `last` is already a float|None from the PriceSnapshot
                    # normalisation in _quote().  The float() cast remains for the
                    # fallback path (idx >= member_overview_cap) where last is still None.
                    "price": float(last) if last is not None else None,
                    "change_pct": float(change_pct) if change_pct is not None else None,
                    "news_count_24h": len(member_news),
                    # F-QA-06 fix: defensive against an empty-string entity_id
                    # accidentally matching all members without an entity_id. The
                    # alerts_by_entity build already filters falsy keys, but the
                    # explicit `bool(eid)` guard means a future regression that
                    # lets "" through cannot reintroduce the false-positive.
                    "has_active_alert": bool(eid) and eid in alerts_by_entity,
                    "top_news_title": (top_news or {}).get("title"),
                    "top_news_url": (top_news or {}).get("url"),
                },
            )

        # ── 5. Aggregates ─────────────────────────────────────────────────────────
        # Equal-weighted return: average change_pct across members for which we
        # actually got a live quote. Members without a quote do not contribute
        # (treating them as 0 would lie about the watchlist's day).
        contributing = [m["change_pct"] for m in movers_out if m["change_pct"] is not None]
        weighted_return_1d: float | None = sum(contributing) / len(contributing) if contributing else None

        # Sector breakdown — count of members in each GICS bucket. The widget
        # renders this as a stacked horizontal mini-bar so we return both count
        # and weight (count / members_count) for convenience.
        sector_counts: dict[str, int] = {}
        for m in movers_out:
            s = m["sector"] or "Unknown"
            sector_counts[s] = sector_counts.get(s, 0) + 1
        total_with_sector = sum(sector_counts.values()) or 1
        sectors_out: list[dict[str, Any]] = sorted(
            ({"sector": s, "count": c, "weight": c / total_with_sector} for s, c in sector_counts.items()),
            key=lambda x: cast("int", x["count"]),
            reverse=True,
        )

        # Biggest news (T-B-2-06): highest-impact article whose entity touches ANY
        # watchlist member. Falls back to None on a quiet news day.
        member_news_pool: list[dict[str, Any]] = []
        for eid in entity_ids:
            member_news_pool.extend(news_by_entity.get(eid, []))
        # Dedup by article_id (an article can mention multiple watchlist members).
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for art in member_news_pool:
            aid = str(art.get("article_id") or "")
            if aid and aid in seen:
                continue
            if aid:
                seen.add(aid)
            deduped.append(art)
        biggest_news_article = max(
            deduped,
            key=lambda a: float(a.get("market_impact_score") or a.get("display_relevance_score") or 0.0),
            default=None,
        )
        biggest_news_out: dict[str, Any] | None = None
        if biggest_news_article is not None:
            biggest_news_out = {
                "article_id": biggest_news_article.get("article_id"),
                "title": biggest_news_article.get("title"),
                "url": biggest_news_article.get("url"),
                "published_at": biggest_news_article.get("published_at"),
                "ticker": biggest_news_article.get("ticker"),
                "impact_score": (
                    float(biggest_news_article["market_impact_score"])
                    if biggest_news_article.get("market_impact_score") is not None
                    else None
                ),
            }

        # Pending alert count restricted to members.
        alerts_count = sum(alerts_by_entity.get(eid, 0) for eid in entity_ids)

        # F-Q1-13 fix (PLAN-0050 QA iter-1): sort movers by absolute change_pct
        # descending so the WatchlistMoversWidget's gainers/losers split always
        # shows the MOST moved instruments, not whatever order S1 returns members.
        #
        # WHY server-side (not client-side): the frontend renders the top-N from
        # this list without re-sorting; the gateway cap (member_overview_cap=25) means
        # an alphabetically-first watchlist member would monopolise top-5 slots if
        # we returned them unsorted.  Sorting here guarantees the extremes appear
        # first regardless of watchlist member order.
        #
        # WHY abs(): a -5% mover is equally "interesting" as a +5% mover for the
        # purpose of identifying the most volatile names.  Members with null
        # change_pct (no price data) are pushed to the end.
        movers_out.sort(
            key=lambda m: abs(m["change_pct"]) if m["change_pct"] is not None else -1.0,
            reverse=True,
        )

        return {
            "watchlist_id": watchlist_id,
            "members_count": members_count,
            "movers": movers_out,
            "weighted_return_1d": weighted_return_1d,
            "sectors": sectors_out,
            "biggest_news": biggest_news_out,
            "alerts_count": alerts_count,
        }

    # T-A-1-01: outer wait_for budget — 15s covers the full fan-out:
    # S1 members + S6 news + S10 alerts (parallel) → S3 quotes x N + S3 overviews x N
    # (capped at 25 each). If the budget fires the widget gets a 504 rather than
    # hanging until the browser's own timeout (30s+), which is a better UX signal.
    try:
        return await asyncio.wait_for(_compose(), timeout=15.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream timeout")  # noqa: B904


__all__ = ["get_portfolio_bundle", "get_watchlist_insights"]
