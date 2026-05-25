"""Market data tool handlers — price history, fundamentals, screener, movers, calendars.

Covers tools backed by S3Port and S3BriefPort:
  - get_price_history       (S3Port)
  - get_fundamentals_history (S3Port)
  - compare_entities        (S3Port — fundamentals highlights + quote)
  - screen_universe         (S3BriefPort)
  - get_market_movers       (S3BriefPort)
  - get_economic_calendar   (S3BriefPort)
  - get_earnings_calendar   (S3BriefPort)
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import TYPE_CHECKING, Any

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import S3BriefPort, S3Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
# WHY: OHLCV data for 252 trading days at ~50 chars/row ≈ 12,600 chars — well
# beyond most context windows. Cap at 4000 to stay within budget.
_TOOL_RESULT_MAX_CHARS = 4000


class MarketHandler(ToolHandler):
    """Handles price, fundamentals, screener, movers, and calendar tools.

    All tools in this handler call either S3Port (market-data service) or
    S3BriefPort (brief/screener endpoint proxied through S9).
    """

    _HANDLED_TOOLS = frozenset(
        {
            "get_price_history",
            "get_fundamentals_history",
            "compare_entities",
            "screen_universe",
            "get_market_movers",
            "get_economic_calendar",
            "get_earnings_calendar",
        }
    )

    def __init__(
        self,
        s3: S3Port,
        s3_brief: S3BriefPort | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s3 = s3
        self._s3_brief = s3_brief
        self._timeout = timeout

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        if tool_name == "get_price_history":
            return await self._handle_get_price_history(**args)
        if tool_name == "get_fundamentals_history":
            return await self._handle_get_fundamentals_history(**args)
        if tool_name == "compare_entities":
            return await self._handle_compare_entities(**args)
        if tool_name == "screen_universe":
            return await self._handle_screen_universe(**args)
        if tool_name == "get_market_movers":
            return await self._handle_get_market_movers(**args)
        if tool_name == "get_economic_calendar":
            return await self._handle_get_economic_calendar(**args)
        if tool_name == "get_earnings_calendar":
            return await self._handle_get_earnings_calendar(**args)
        # Unreachable if can_handle() is checked first; guard for safety.
        raise ValueError(f"MarketHandler cannot handle tool: {tool_name}")

    async def _handle_get_price_history(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        interval: str = "week",
    ) -> RetrievedItem | None:
        """Fetch OHLCV bars and format as a markdown table RetrievedItem."""
        # Parse and validate date strings before hitting S3
        try:
            _from = date.fromisoformat(from_date)
            _to = date.fromisoformat(to_date)
        except ValueError:
            log.warning(
                "tool_invalid_dates",
                tool="get_price_history",
                from_date=from_date,
                to_date=to_date,
            )
            return None

        # BP-025: wrap S3 call with timeout to prevent long tail latency
        bars = await asyncio.wait_for(
            self._s3.get_ohlcv_range(
                ticker=ticker,
                from_date=_from,
                to_date=_to,
                interval=interval,
            ),
            timeout=self._timeout,
        )
        if not bars:
            log.warning("tool_no_data", tool="get_price_history", ticker=ticker)
            return None

        table = self._format_price_table(ticker, from_date, to_date, interval, bars)
        # CRITICAL: field is `text` NOT `content` (N-7); use .create() factory
        # (never direct construction — fusion_score invariant enforced in __post_init__)
        return RetrievedItem.create(
            item_id=f"tool:price_history:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
        )

    async def _handle_get_fundamentals_history(
        self,
        ticker: str,
        periods: int = 8,
    ) -> RetrievedItem | None:
        """Fetch quarterly fundamentals and format as a markdown table RetrievedItem."""
        data = await asyncio.wait_for(
            self._s3.get_fundamentals_history(ticker=ticker, periods=periods),
            timeout=self._timeout,
        )
        if not data:
            log.warning("tool_no_data", tool="get_fundamentals_history", ticker=ticker)
            return None

        table = self._format_fundamentals_table(ticker, data)
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
        )

    async def _handle_compare_entities(
        self,
        entity_tickers: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Side-by-side fundamentals + price comparison for 2-4 entities (PLAN-0081 Wave A).

        Fetches fundamentals highlights and latest quote in parallel for each ticker.
        R9: returns [] on missing port, invalid input, or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3 is None:
            log.warning("tool_handler_missing_port", tool="compare_entities", port="s3")
            return []

        tickers = entity_tickers or []
        if len(tickers) < 2 or len(tickers) > 4:
            log.warning(
                "tool_invalid_param",
                tool="compare_entities",
                reason="entity_tickers must be 2-4 items",
                count=len(tickers),
            )
            return []

        t0 = time.monotonic()

        async def _fetch_one(ticker: str) -> dict:
            """Fetch fundamentals + quote for a single ticker in parallel."""
            instrument_id = await self._s3.find_instrument_by_ticker(ticker)
            if instrument_id is None:
                return {"ticker": ticker, "error": "not_found"}
            # Fetch fundamentals highlights and quote concurrently — independent reads
            gather_results: list[dict | BaseException] = list(
                await asyncio.gather(
                    self._s3.get_fundamentals_highlights(instrument_id),
                    self._s3.get_quote(instrument_id),
                    return_exceptions=True,
                )
            )
            funda_raw, quote_raw = gather_results[0], gather_results[1]
            return {
                "ticker": ticker,
                "fundamentals": funda_raw if not isinstance(funda_raw, BaseException) else {},
                "quote": quote_raw if not isinstance(quote_raw, BaseException) else {},
            }

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch_one(t) for t in tickers], return_exceptions=True),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="compare_entities", error=str(e))
            return []

        lines = [f"## Entity Comparison: {', '.join(tickers)}\n"]
        for item in results:
            # M-3: BaseException is the correct check — asyncio.gather(return_exceptions=True)
            # can return KeyboardInterrupt, SystemExit, etc. which are BaseException but not Exception.
            if isinstance(item, BaseException) or item.get("error"):  # type: ignore[union-attr]
                ticker_label = item.get("ticker", "?") if not isinstance(item, BaseException) else "?"  # type: ignore[union-attr]
                lines.append(f"### {ticker_label} — data unavailable\n")
                continue
            ticker = item["ticker"]  # type: ignore[index]
            funda = item.get("fundamentals") or {}  # type: ignore[union-attr]
            quote = item.get("quote") or {}  # type: ignore[union-attr]
            lines.append(f"### {ticker}")
            if quote:
                price = quote.get("price") or quote.get("close") or quote.get("last_price")
                if price:
                    lines.append(f"  Price: {price}")
            if funda:
                for key in ("market_cap", "pe_ratio", "revenue", "gross_profit", "eps"):
                    val = funda.get(key)
                    if val is not None:
                        lines.append(f"  {key.replace('_', ' ').title()}: {val}")
            lines.append("")

        text = "\n".join(lines)
        log.info(
            "tool_executed",
            tool="compare_entities",
            latency_ms=round((time.monotonic() - t0) * 1000),
            ticker_count=len(tickers),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:compare:{'-'.join(tickers)}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title=f"Comparison: {', '.join(tickers)}",
                    url=None,
                    source_name="fundamentals",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_screen_universe(
        self,
        market_cap_min: float | None = None,
        market_cap_max: float | None = None,
        pe_ratio_max: float | None = None,
        sector: str | None = None,
        industry: str | None = None,
        region: str | None = None,
        limit: int = 20,
    ) -> list[RetrievedItem]:
        """Quantitative screener via S9 POST /v1/fundamentals/screen (PLAN-0081 Wave A).

        Builds a filter dict from LLM-supplied params and forwards to S3BriefPort.
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="screen_universe", port="s3_brief")
            return []

        filters: dict = {}
        if market_cap_min is not None:
            filters["market_cap_min"] = market_cap_min
        if market_cap_max is not None:
            filters["market_cap_max"] = market_cap_max
        if pe_ratio_max is not None:
            filters["pe_ratio_max"] = pe_ratio_max
        if sector:
            filters["sector"] = sector
        # FIX-LIVE-M (2026-05-24): GICS industry filter — more selective than sector.
        if industry:
            filters["industry"] = industry
        if region:
            filters["region"] = region
        # WHY clamp limit: prevent the LLM from requesting huge result sets that
        # would overflow the context window budget.
        filters["limit"] = max(1, min(int(limit), 100))

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.screen_instruments(filters),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="screen_universe", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="screen_universe")
            return []

        instruments = raw.get("instruments") or raw.get("results") or raw.get("data") or []
        if not instruments:
            text = "No instruments matched the screening criteria."
        else:
            lines = [f"## Screener Results ({len(instruments)} instruments)\n"]
            for inst in instruments[:50]:
                ticker = inst.get("ticker") or inst.get("symbol") or "?"
                name = inst.get("name") or ""
                mc = inst.get("market_cap")
                pe = inst.get("pe_ratio")
                row = f"  {ticker}"
                if name:
                    row += f" — {name}"
                if mc:
                    row += f" | MCap: {mc}"
                if pe:
                    row += f" | P/E: {pe}"
                lines.append(row)
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="screen_universe",
            latency_ms=round((time.monotonic() - t0) * 1000),
            result_count=len(instruments) if isinstance(instruments, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id="tool:screener:results",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.82,
                trust_weight=0.80,
                citation_meta=CitationMeta(
                    title="Screener results",
                    url=None,
                    source_name="screener",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_market_movers(
        self,
        mover_type: str = "gainers",
        limit: int = 10,
        period: str = "1D",
    ) -> list[RetrievedItem]:
        """Top gainers/losers via S9 GET /v1/market/top-movers (PLAN-0081 Wave A).

        C-2: period default changed to "1D" (uppercase) to match S9 contract.
        C-3: "most_active" removed — S9 only accepts "gainers" and "losers".
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_market_movers", port="s3_brief")
            return []

        # C-3: "most_active" is NOT a valid S9 mover_type — only "gainers" and "losers" are accepted.
        # WHY removed: sending "most_active" to S9 causes a 422 validation error downstream.
        valid_types = {"gainers", "losers"}
        safe_mover_type = mover_type if mover_type in valid_types else "gainers"
        limit_clamped = max(1, min(int(limit), 50))

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.get_top_movers(
                    mover_type=safe_mover_type,
                    limit=limit_clamped,
                    period=period,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_market_movers", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="get_market_movers")
            return []

        movers = raw.get("movers") or raw.get("data") or raw.get("results") or []
        if not movers:
            text = f"No {safe_mover_type} data available for period {period}."
        else:
            lines = [f"## Market Movers — {safe_mover_type.replace('_', ' ').title()} ({period})\n"]
            for m in movers[:limit_clamped]:
                ticker = m.get("ticker") or m.get("symbol") or "?"
                change_pct = m.get("change_percent") or m.get("change_pct") or m.get("changePercent")
                price = m.get("price") or m.get("close")
                row = f"  {ticker}"
                if change_pct is not None:
                    row += f" {change_pct:+.2f}%" if isinstance(change_pct, float) else f" {change_pct}"
                if price:
                    row += f" @ {price}"
                lines.append(row)
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_market_movers",
            latency_ms=round((time.monotonic() - t0) * 1000),
            mover_type=safe_mover_type,
            count=len(movers) if isinstance(movers, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:movers:{safe_mover_type}:{period}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.85,
                trust_weight=0.82,
                citation_meta=CitationMeta(
                    title=f"Market movers: {safe_mover_type} ({period})",
                    url=None,
                    source_name="market_data",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_economic_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        region: str | None = None,
    ) -> list[RetrievedItem]:
        """Upcoming macro events (CPI, FOMC, GDP) via S9 GET /v1/fundamentals/economic-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_economic_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            events = await asyncio.wait_for(
                self._s3_brief.get_economic_calendar(
                    from_date=from_date,
                    to_date=to_date,
                    region=region,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_economic_calendar", error=str(e))
            return []

        if not events:
            log.info("tool_no_data", tool="get_economic_calendar")
            return []

        lines = ["## Economic Calendar\n"]
        for evt in events[:30]:
            date_str = evt.get("date") or evt.get("event_date") or ""
            name = evt.get("name") or evt.get("event") or evt.get("title") or "?"
            actual = evt.get("actual")
            forecast = evt.get("forecast") or evt.get("estimate")
            prev = evt.get("previous") or evt.get("prior")
            row = f"  {date_str}  {name}"
            if actual is not None:
                row += f" | Actual: {actual}"
            if forecast is not None:
                row += f" | Forecast: {forecast}"
            if prev is not None:
                row += f" | Prior: {prev}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_economic_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            event_count=len(events),
        )
        return [
            RetrievedItem.create(
                item_id="tool:economic_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Economic calendar",
                    url=None,
                    source_name="economic_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_earnings_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[RetrievedItem]:
        """Earnings release dates via S9 GET /v1/fundamentals/earnings-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_earnings_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            earnings = await asyncio.wait_for(
                self._s3_brief.get_earnings_calendar(
                    from_date=from_date,
                    to_date=to_date,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_earnings_calendar", error=str(e))
            return []

        if not earnings:
            log.info("tool_no_data", tool="get_earnings_calendar")
            return []

        lines = ["## Earnings Calendar\n"]
        for entry in earnings[:30]:
            date_str = entry.get("date") or entry.get("report_date") or ""
            ticker = entry.get("ticker") or entry.get("symbol") or "?"
            name = entry.get("name") or entry.get("company") or ""
            eps_est = entry.get("eps_estimate") or entry.get("eps_forecast")
            eps_act = entry.get("eps_actual")
            row = f"  {date_str}  {ticker}"
            if name:
                row += f" ({name})"
            if eps_est is not None:
                row += f" | EPS Est: {eps_est}"
            if eps_act is not None:
                row += f" | EPS Actual: {eps_act}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_earnings_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            entry_count=len(earnings),
        )
        return [
            RetrievedItem.create(
                item_id="tool:earnings_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Earnings calendar",
                    url=None,
                    source_name="earnings_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    def _format_price_table(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        interval: str,
        bars: list[dict[str, Any]],
    ) -> str:
        """Format OHLCV bars as a markdown table with a header line."""
        header = f"{ticker} price history ({interval}, {from_date} → {to_date})\n"
        header += "| Date       | Close  | Volume |\n|------------|--------|--------|\n"
        rows = []
        for b in bars:
            close = b.get("close", 0) or 0
            volume = b.get("volume", 0) or 0
            rows.append(f"| {b.get('date', '?')} | ${float(close):.2f} | {int(volume):,} |")
        return header + "\n".join(rows)

    def _format_fundamentals_table(
        self,
        ticker: str,
        periods: list[dict[str, Any]],
    ) -> str:
        """Format quarterly fundamentals as a markdown table."""
        header = f"{ticker} quarterly fundamentals\n"
        header += "| Period | Revenue | Net Income | EPS | P/E |\n"
        header += "|--------|---------|------------|-----|-----|\n"
        rows = []
        for p in periods:
            rev_val = p.get("revenue") or p.get("totalRevenue")
            rev = f"${float(rev_val) / 1e9:.1f}B" if rev_val else "—"
            ni_val = p.get("net_income") or p.get("netIncome")
            ni = f"${float(ni_val) / 1e9:.1f}B" if ni_val else "—"
            eps_val = p.get("eps") or p.get("epsActual")
            eps = f"${float(eps_val):.2f}" if eps_val else "—"
            pe_val = p.get("pe_ratio") or p.get("pe")
            pe = f"{float(pe_val):.1f}x" if pe_val else "—"
            period_label = p.get("period") or p.get("date") or "?"
            rows.append(f"| {period_label} | {rev} | {ni} | {eps} | {pe} |")
        return header + "\n".join(rows)
