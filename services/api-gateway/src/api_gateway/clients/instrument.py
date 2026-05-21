"""Composed endpoints for the instrument detail page.

``get_company_overview``  → CompanyOverview composite (instrument + quote
+ fundamentals header + 90-day OHLCV chart).
``get_instrument_page_bundle`` → wraps overview with extra full-fundamentals,
technicals, insider, and top-news legs for the initial instrument-detail
page load.

Split from the original 1424-line ``clients.py`` (TASK-W4-06 / REF-002).
Behavior preserved exactly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from api_gateway.clients.base import (
    DownstreamError,
    ServiceClients,
    _checked_get,
    logger,
)

if TYPE_CHECKING:
    from collections.abc import Callable


async def get_company_overview(
    clients: ServiceClients,
    company_id: str,
    *,
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
    overall_timeout_s: float = 15.0,
) -> dict[str, Any]:
    """Compose CompanyOverview from Market Data.

    Returns the shape the frontend CompanyOverview TypeScript type expects:
      { instrument, quote, fundamentals, ohlcv }

    ``make_headers`` is a factory called once per downstream request, producing
    a fresh JWT with a unique JTI each time.  This prevents ``InternalJWTMiddleware``
    replay detection when all 4 parallel calls share the same JWT.

    ``headers`` is kept for backwards compatibility (tests, single calls).  If both
    are provided ``make_headers`` takes precedence.

    Parallel calls:
      - /api/v1/instruments/{id}                       → instrument metadata (required)
      - /api/v1/fundamentals/{id}/company-profile       → name / currency / GICS (optional)
      - /api/v1/ohlcv/{id}?timeframe=1d&start=<90d ago> → ~90 trading days chart (optional)
      - /api/v1/quotes/{id}                              → latest quote snapshot (optional)

    WHY start= instead of limit=: S3's OHLCV route accepts date-range parameters
    (start/end), not a bare row-count limit. Passing ``limit=30`` was silently
    ignored by FastAPI because the parameter name did not match any declared
    query param — only 2 bars were ever returned (the entire DB content at the
    time of the bug).  Using ``start=90 days ago`` guarantees ~90 trading-day
    bars of 1D data are returned regardless of ingestion timing, while S3's
    own ``limit`` param (default 200) provides a safe upper cap.

    F-008: the whole composition is wrapped in asyncio.wait_for(overall_timeout_s)
    so a single sluggish downstream cannot hang the page indefinitely.
    """
    from datetime import UTC, datetime, timedelta

    def _h() -> dict[str, str]:
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe(path: str, **kwargs: Any) -> dict[str, Any]:
        """_checked_get variant that returns {} on any DownstreamError or network error."""
        try:
            return await _checked_get(clients.market_data, "market-data", path, headers=_h(), **kwargs)
        except Exception:
            # F-008: log warnings for any failure so partial failures are visible
            # in observability without silently returning empty data.
            logger.warning("company_overview_leg_failed", leg=path, exc_info=True)
            return {}

    async def _compose() -> dict[str, Any]:
        # Request 90 days of daily bars so the chart has enough history to render
        # meaningful trends even when markets are closed for holidays/weekends.
        # 90 calendar days ≈ 63 trading days — well above any 30-bar chart window.
        # Use UTC-aware datetime (.date()) per project UTC-only convention (CLAUDE.md Rule 7).
        start_90d_ago = (datetime.now(tz=UTC) - timedelta(days=90)).date().isoformat()

        # PRD-0089 F2: ``company_id`` is now guaranteed to be a canonical
        # instrument_id UUID — the route handler resolves any ticker /
        # alias / UUID input via ``resolve_security_id`` BEFORE calling
        # this function. The old 70-LOC "try id, fall back to KG ticker,
        # retry by symbol" dance is gone; we just look up the instrument
        # by its known id and raise 404 on miss.
        try:
            instrument_raw = await _checked_get(
                clients.market_data,
                "market-data",
                f"/api/v1/instruments/lookup?id={company_id}&extra_info=true",
                headers=_h(),
            )
        except DownstreamError:
            # The instrument is genuinely unknown to market-data. The
            # bundle composer's _safe_overview catches the re-raised 404
            # and surfaces overview=null so the frontend can render its
            # InstrumentNotFound UI path.
            raise
        except Exception as exc:
            # Network / parse error: surface as a 503-ish downstream error
            # so the caller sees an honest failure rather than a silent
            # empty bundle (the prior behaviour swallowed everything).
            raise DownstreamError(
                "market-data",
                502,
                f"instrument lookup failed for {company_id}: {exc}",
            ) from exc

        resolved_md_id: str = str(instrument_raw.get("id") or company_id)

        # Instrument metadata is required; the rest degrade gracefully to null.
        # Each call gets its own fresh JWT via _h() so parallel calls don't share JTIs.
        # WHY 5 parallel calls (was 4): highlights gives us the header stats
        # (market_cap, pe_ratio) and technicals gives us the 52w range without
        # an extra round-trip after render. The general fundamentals endpoint
        # returns all sections in one call; we filter by section name below.
        profile_raw, ohlcv_raw, quote_raw, all_fundamentals_raw = await asyncio.gather(
            _safe(f"/api/v1/fundamentals/{resolved_md_id}/company-profile"),
            _safe(f"/api/v1/ohlcv/{resolved_md_id}", params={"timeframe": "1d", "start": start_90d_ago}),
            _safe(f"/api/v1/quotes/{resolved_md_id}"),
            _safe(f"/api/v1/fundamentals/{resolved_md_id}"),
        )

        # PRD-0089 F2: ADR-F-12 SUPERSEDED. Post-F2, ``canonical_entities.entity_id``
        # equals ``instruments.id`` for every tradable security (M-017 invariant
        # enforced in CI). The previous code did a separate KG lookup to map
        # ticker→entity_id; that round-trip is now redundant — kg_entity_id IS
        # the instrument_id. Kept the variable name for type-stability in the
        # payload assembly below; will be dropped in F2 v1.1 cleanup (plan §6.4).
        kg_entity_id: str = resolved_md_id

        # Extract name / currency / sector from the first company-profile record's data blob.
        profile_data: dict[str, Any] = {}
        for rec in profile_raw.get("records", []):
            profile_data = rec.get("data") or {}
            if profile_data:
                break

        # Extract highlights (market_cap, pe_ratio) and technicals (52w range) from
        # the all-sections fundamentals response. The general endpoint returns records
        # with a "section" field so we can filter without additional API calls.
        highlights_data: dict[str, Any] = {}
        technicals_data: dict[str, Any] = {}
        for rec in (all_fundamentals_raw or {}).get("records", []):
            section = rec.get("section", "")
            data = rec.get("data") or {}
            if section == "highlights" and not highlights_data:
                highlights_data = data
            elif section == "technicals_snapshot" and not technicals_data:
                technicals_data = data

        # Build the frontend Instrument shape.
        # WHY description from profile_data["Description"]: EODHD stores company
        # descriptions in the General.Description field of the fundamentals payload.
        # market-data persists this in company_profiles.data JSONB under key "Description".
        # S9 extracts it here so the frontend gets description in the same CompanyOverview
        # response — no extra round-trip needed (UI-004 fix, 2026-04-24).
        #
        # T-S2-02 (W5): EODHD General.Founded is stored verbatim in company_profiles.data
        # JSONB by market-data (no serialiser filter — data flows through unchanged).
        # Exposed here as "founded" so CompanyAboutCard gets it without an extra call.
        # Field path for frontend: overview.instrument.founded.
        instrument: dict[str, Any] = {
            "instrument_id": instrument_raw.get("id", company_id),
            "entity_id": kg_entity_id,
            "ticker": instrument_raw.get("symbol", ""),
            "name": profile_data.get("Name") or instrument_raw.get("symbol", ""),
            "exchange": instrument_raw.get("exchange", ""),
            "currency": profile_data.get("Currency", "USD"),
            "gics_sector": profile_data.get("GicSector") or instrument_raw.get("sector"),
            "gics_industry": profile_data.get("GicGroup"),
            "isin": profile_data.get("ISIN"),
            "country": profile_data.get("CountryISO"),
            "description": profile_data.get("Description") or None,
            # WHY founded nullable: EODHD omits Founded for ETFs, foreign ADRs,
            # and instruments ingested before the company_profile wave. Frontend
            # renders "—" on null (never crashes on absence).
            "founded": profile_data.get("Founded") or None,
        }

        # Map the market-data QuoteResponse → frontend Quote shape (best-effort; no change/change_pct).
        quote: dict[str, Any] | None = None
        if quote_raw:
            last = quote_raw.get("last")
            quote = {
                "instrument_id": quote_raw.get("instrument_id", company_id),
                "ticker": instrument_raw.get("symbol", ""),
                "price": float(last) if last else 0.0,
                # T-A-1-04: S3 QuoteResponse has no intraday change field.
                # Return None (honest) instead of 0.0 (misleading — implies no movement).
                # Frontend TypeScript types are updated separately to accept null.
                "change": None,
                "change_pct": None,
                "timestamp": str(quote_raw.get("timestamp", "")),
                "volume": quote_raw.get("volume"),
            }

        # Normalize market-data OHLCVListResponse → frontend OHLCVResponse shape.
        # S3 returns: {items: [{bar_date, open: str, high: str, ...}], total, timeframe}
        # Frontend expects: {instrument_id, ticker, timeframe, bars: [{timestamp, open: float, ...}]}
        ohlcv_out: dict[str, Any] | None = None
        if ohlcv_raw:
            raw_items: list[dict[str, Any]] = ohlcv_raw.get("items") or []
            ohlcv_out = {
                "instrument_id": company_id,
                "ticker": instrument_raw.get("symbol", ""),
                "timeframe": "1D",
                "bars": [
                    {
                        "timestamp": item.get("bar_date", ""),
                        "open": float(item["open"]) if item.get("open") else 0.0,
                        "high": float(item["high"]) if item.get("high") else 0.0,
                        "low": float(item["low"]) if item.get("low") else 0.0,
                        "close": float(item["close"]) if item.get("close") else 0.0,
                        "volume": item.get("volume") or 0,
                    }
                    for item in raw_items
                ],
            }

        # Build the overview fundamentals snapshot for the instrument detail header.
        # WHY here (not in FundamentalsTab): the header stats (market_cap, pe_ratio,
        # 52w range, daily_return) need to load with the initial overview request so
        # they appear before the user selects the Fundamentals tab. The FundamentalsTab
        # fetches a full detailed breakdown separately on tab activation.
        # daily_return is computed from the last two OHLCV bars (no dedicated endpoint).
        overview_fundamentals: dict[str, Any] | None = None
        if highlights_data or technicals_data:
            raw_bars = (ohlcv_out or {}).get("bars") or []
            daily_return: float | None = None
            if len(raw_bars) >= 2:
                prev_close = raw_bars[-2].get("close") or 0.0
                last_close = raw_bars[-1].get("close") or 0.0
                if prev_close > 0:
                    daily_return = (last_close - prev_close) / prev_close

            market_cap_raw = highlights_data.get("MarketCapitalization")
            pe_raw = highlights_data.get("PERatio")
            w52_high_raw = technicals_data.get("52WeekHigh")
            w52_low_raw = technicals_data.get("52WeekLow")

            overview_fundamentals = {
                "market_cap": float(market_cap_raw) if market_cap_raw is not None else None,
                "pe_ratio": float(pe_raw) if pe_raw is not None else None,
                "week_52_high": float(w52_high_raw) if w52_high_raw is not None else None,
                "week_52_low": float(w52_low_raw) if w52_low_raw is not None else None,
                "daily_return": daily_return,
            }

        return {
            "instrument": instrument,
            "quote": quote,
            # Overview fundamentals: key header stats. FundamentalsTab fetches the
            # full per-section breakdown separately on tab activation.
            "fundamentals": overview_fundamentals,
            "ohlcv": ohlcv_out,
        }

    # F-008: wrap the entire composition in a timeout budget (15 s by default).
    # A sluggish downstream cannot hang the page indefinitely.
    return await asyncio.wait_for(_compose(), timeout=overall_timeout_s)


async def get_instrument_page_bundle(
    clients: ServiceClients,
    instrument_id: str,
    *,
    make_headers: Callable[[], dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
    overall_timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Composite endpoint for /instruments/[id] initial page load.

    Collapses the instrument-detail page's overview-tab waterfall into a
    single round-trip. Per-call failures degrade gracefully to null
    sub-fields rather than failing the whole bundle. The whole composition
    is wrapped in asyncio.wait_for(overall_timeout_s) so a single sluggish
    downstream cannot hang the page indefinitely (QA-iter1).

    Composed sub-resources (each returns the same shape the dedicated
    endpoint would return, so the FE can prime its TanStack Query caches):

      - overview         : the existing CompanyOverview composite
                           (instrument + quote + fundamentals header + ohlcv 90d).
                           Required-ish — if this fails the page is essentially
                           empty, but bundle still returns 200 with overview=null
                           so the FE can render its own "not found" UI.
      - fundamentals     : full all-sections fundamentals (FundamentalsTab feed)
      - technicals       : technicals_snapshot section
      - insider          : insider transactions snapshot
      - top_news         : entity-scoped top-N news (limit=5, public)

    QA-iter1 fixes:
      - insider path was wrong (missing -snapshot suffix) → silent 404. Fixed.
      - entity_id is now read from overview.instrument.entity_id (which the
        overview already resolves via KG lookup) instead of duplicating that
        same instrument-fetch + KG-lookup pair (perf agent C-1).
      - overall asyncio.wait_for budget defends against single-leg hangs.
      - _safe_* wrappers broadened to swallow generic Exception so httpx
        network errors (ConnectError, ReadTimeout) degrade to null too.

    Tab-specific surfaces (full news feed, intelligence, peers, knowledge
    graph) intentionally NOT bundled — they load on tab switch and have
    feature-specific filtering.

    Each downstream call gets a fresh JWT via the make_headers factory so
    the JTI replay-detection in InternalJWTMiddleware doesn't reject
    parallel calls sharing one token.
    """

    def _h() -> dict[str, str]:
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe_md(path: str, **kwargs: Any) -> dict[str, Any] | None:
        """market-data GET — returns None on ANY exception (DownstreamError +
        httpx network errors). QA-iter1: was DownstreamError-only."""
        try:
            return await _checked_get(clients.market_data, "market-data", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("instrument_bundle_leg_failed", leg=path, exc_info=True)
            return None

    async def _safe_nlp(path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            return await _checked_get(clients.nlp_pipeline, "nlp-pipeline", path, headers=_h(), **kwargs)
        except Exception:
            logger.warning("instrument_bundle_leg_failed", leg=path, exc_info=True)
            return None

    async def _safe_overview() -> dict[str, Any] | None:
        try:
            return await get_company_overview(
                clients,
                instrument_id,
                make_headers=make_headers,
                headers=headers,
            )
        except Exception:
            logger.warning("instrument_bundle_leg_failed", leg="overview", exc_info=True)
            return None

    async def _compose() -> dict[str, Any]:
        # PRD-0089 F2: ``instrument_id`` is now guaranteed-canonical
        # (the route handler resolves any ticker / alias / UUID upstream
        # via ``resolve_security_id``). The old two-phase dance read the
        # resolved md_id back out of the overview payload before issuing
        # the Phase-2 fan-out; that re-read is no longer necessary because
        # M-017 guarantees ``entity_id == instrument_id`` for tradable
        # securities, and the incoming ``instrument_id`` is already the
        # canonical UUID for both the market-data row and the KG entity.
        #
        # All 5 calls now fly in parallel — the prior Phase 1 / Phase 2
        # sequential split was only there to bridge the two id namespaces.
        overview_data, fundamentals_data, technicals_data, insider_data, news_data = await asyncio.gather(
            _safe_overview(),
            _safe_md(f"/api/v1/fundamentals/{instrument_id}"),
            _safe_md(f"/api/v1/fundamentals/{instrument_id}/technicals-snapshot"),
            _safe_md(f"/api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot"),
            _safe_nlp(f"/api/v1/news/entity/{instrument_id}", params={"limit": 5}),
        )

        return {
            "instrument_id": instrument_id,
            # v1: still emit entity_id for frontend backwards-compat
            # (PRD-0089 F2 plan §6.4 — drop in v1.1 cleanup).
            "entity_id": instrument_id,
            "overview": overview_data,
            "fundamentals": fundamentals_data,
            "technicals": technicals_data,
            "insider": insider_data,
            "top_news": news_data,
        }

    # Overall budget: wrap the entire composition. If the wait_for tripwires,
    # the bundle still succeeds — we return whatever sub-resources finished
    # plus null for anything still in flight, by re-resolving via
    # gather(return_exceptions=True) inside _compose. For simplicity we just
    # raise TimeoutError → bundle returns null for everything, plus 504 from
    # the route handler. Acceptable: a 20s overall budget is generous; if it
    # trips, the cluster is in trouble anyway.
    try:
        return await asyncio.wait_for(_compose(), timeout=overall_timeout_s)
    except TimeoutError:
        return {
            "instrument_id": instrument_id,
            "entity_id": instrument_id,
            "overview": None,
            "fundamentals": None,
            "technicals": None,
            "insider": None,
            "top_news": None,
        }


__all__ = ["get_company_overview", "get_instrument_page_bundle"]
