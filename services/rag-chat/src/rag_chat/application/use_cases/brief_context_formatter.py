"""BriefContextFormatter — builds context strings injected into brief prompts.

Extracted from generate_briefing.py (PLAN-0089 C-3) so that all prompt-context
assembly logic lives in one dedicated class rather than being scattered as module-
level helpers. The class wraps the same helper functions that were previously
defined at module level; their behaviour is unchanged (pure refactor).

Functions / methods moved here:
  - _format_portfolio_morning → BriefContextFormatter.format_portfolio_morning
  - _format_news              → BriefContextFormatter.format_news
  - _format_alerts            → BriefContextFormatter.format_alerts
  - _format_market_overview   → BriefContextFormatter.format_market_overview
  - _format_events            → BriefContextFormatter.format_events
  - _format_entity_context    → BriefContextFormatter.format_entity_context
  - _fmt_usd_billions         → BriefContextFormatter._fmt_usd_billions (static)
  - _fmt_percent              → BriefContextFormatter._fmt_percent (static)
  - _format_fundamentals      → BriefContextFormatter.format_fundamentals
  - _format_relationships     → BriefContextFormatter.format_relationships
  - _build_morning_risk_summary → BriefContextFormatter.build_morning_risk_summary
  - _build_citations          → BriefContextFormatter.build_citations
  - _extract_entity_mentions  → BriefContextFormatter.extract_entity_mentions
"""

from __future__ import annotations

from typing import Any


class BriefContextFormatter:
    """Builds the context strings injected into the brief generation prompts.

    All methods are pure functions (no internal state), grouped here so that
    generate_briefing.py can delegate all context-formatting concerns to a
    single object and tests can exercise formatting logic in isolation.
    """

    # ── Portfolio / morning brief ──────────────────────────────────────────────

    def format_portfolio_morning(self, ctx: Any) -> str:
        """Format portfolio holdings + watchlist for the morning brief prompt."""
        if ctx is None or ctx.portfolio is None:
            return ""
        p = ctx.portfolio
        lines: list[str] = []
        if p.holdings:
            lines.append(f"Holdings ({p.total_positions} positions):")
            for h in p.holdings:
                name = h.canonical_name or h.ticker or "Unknown"
                weight = f"{h.current_weight:.1%}" if h.current_weight else "N/A"
                lines.append(f"  - {name}: {h.quantity} units, weight {weight}")
        if p.watchlist:
            lines.append("Watchlist:")
            for w in p.watchlist:
                name = w.canonical_name or w.ticker or "Unknown"
                lines.append(f"  - {name}")
        return "\n".join(lines)

    # ── News / events / alerts ─────────────────────────────────────────────────

    def format_news(self, ctx: Any, citation_offset: int = 0) -> str:
        """Format news articles from context into a readable list with [cN] prefixes.

        WHY [cN] prefixes: the v3.0 prompt requires stable citation indices so the LLM
        can embed [c1], [c2], … markers in its bullets. The offset parameter allows the
        caller to continue numbering from where a previous section left off (news is
        always first so offset=0).

        NOTE: citation_offset is unused here (news is always first), but the parameter
        is included for symmetry with format_events and format_alerts so callers can
        use the same pattern.
        """
        if ctx is None or not ctx.news_articles:
            return ""
        lines: list[str] = []
        for i, a in enumerate(ctx.news_articles[:8]):
            cn = f"[c{citation_offset + i + 1}]"
            date_str = a.published_at.strftime("%Y-%m-%d") if a.published_at else "unknown date"
            score = f" (relevance: {a.display_relevance_score:.0%})" if a.display_relevance_score else ""
            lines.append(f"{cn} [{date_str}] {a.title}{score}")
            if a.url:
                lines.append(f"  Source: {a.url}")
        return "\n".join(lines)

    def format_alerts(self, ctx: Any, citation_offset: int = 0) -> str:
        """Format active alerts from context with [cN] prefixes.

        WHY citation_offset: alerts come after news + events in the citation index.
        The caller computes offset = len(news) + len(events) so alert items get
        contiguous [cN] indices.
        """
        if ctx is None or not ctx.active_alerts:
            return ""
        lines: list[str] = []
        for i, alert in enumerate(ctx.active_alerts[:5]):
            cn = f"[c{citation_offset + i + 1}]"
            lines.append(
                f"{cn} [{alert.severity.upper()}] {alert.alert_type}: {alert.payload.get('message', '')}",
            )
        return "\n".join(lines)

    def format_market_overview(self, ctx: Any) -> str:
        """Format market overview snapshot."""
        if ctx is None or ctx.market_overview is None:
            return ""
        mo = ctx.market_overview
        lines: list[str] = []
        if mo.sector_performance:
            lines.append("Sector performance:")
            for sector, pct in sorted(mo.sector_performance.items(), key=lambda x: -abs(x[1]))[:5]:
                lines.append(f"  - {sector}: {pct:+.1%}")
        return "\n".join(lines)

    def format_events(self, ctx: Any, citation_offset: int = 0) -> str:
        """Format structured events from context with [cN] prefixes.

        WHY citation_offset: events come after news items in the citation index.
        The caller sets offset = len(news_articles) so events are numbered
        [c(N+1)], [c(N+2)], … continuing from where news left off.
        """
        if ctx is None or not ctx.recent_events:
            return ""
        lines: list[str] = []
        for i, ev in enumerate(ctx.recent_events[:6]):
            cn = f"[c{citation_offset + i + 1}]"
            date_str = ev.event_date.strftime("%Y-%m-%d") if ev.event_date else "unknown date"
            lines.append(f"{cn} [{date_str}] {ev.event_type}: {ev.event_text[:200]}")
        return "\n".join(lines)

    # ── Instrument brief ───────────────────────────────────────────────────────

    def format_entity_context(self, ctx: Any) -> str:
        """Format the center entity's basic info for an instrument brief."""
        if ctx is None or ctx.entity_graph is None:
            return ""
        eg = ctx.entity_graph
        lines = [
            f"Entity: {eg.canonical_name}",
            f"Type: {eg.entity_type}",
        ]
        if eg.ticker:
            lines.append(f"Ticker: {eg.ticker}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_usd_billions(value: Any) -> str:
        """Format a raw integer dollar value (e.g. 2_800_000_000_000) as '$X.XXB'.

        EODHD returns MarketCapitalization and RevenueTTM as raw integers (full USD).
        The LLM must receive a pre-formatted human string — otherwise it picks random
        unit conventions (sometimes billions, sometimes trillions, sometimes raw bytes).
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        if v >= 1e12:
            return f"${v / 1e12:.2f}T"
        if v >= 1e9:
            return f"${v / 1e9:.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:.2f}M"
        return f"${v:,.0f}"

    @staticmethod
    def _fmt_percent(value: Any) -> str:
        """Format a decimal ratio (e.g. 0.2543) as 'XX.X%'.

        EODHD returns margin/growth fields as raw floats in [0, 1] (or negative).
        """
        try:
            return f"{float(value) * 100:.1f}%"
        except (TypeError, ValueError):
            return str(value)

    def format_fundamentals(self, ctx: Any) -> str:
        """Format fundamental data highlights for an instrument brief.

        Reports a curated set of financial metrics when present in the data dict.
        Missing metrics are silently omitted (no 'N/A' placeholders — prompt template
        instructs the LLM to write 'Not in retrieved context' for absent metrics).

        All raw EODHD values are pre-formatted into human-readable strings before
        being passed to the LLM to prevent unit-convention hallucinations (BP-F-002).
        """
        if ctx is None or ctx.fundamentals is None:
            return ""
        data = ctx.fundamentals.data

        # Fields that arrive as raw integer USD values and must be scaled to B/T.
        # NOTE: MarketCapitalizationMln is intentionally excluded — it conflicts with
        # MarketCapitalization and causes the LLM to present the same metric twice in
        # different units. Use only the raw-integer canonical field.
        large_usd_fields: dict[str, str] = {
            "MarketCapitalization": "Market Cap",
            "RevenueTTM": "Revenue TTM",
        }

        # Fields that arrive as decimal ratios in [-1, 1] and must be shown as %.
        percent_fields: dict[str, str] = {
            "ProfitMargin": "Net Profit Margin",
            "OperatingMarginTTM": "Operating Margin TTM",
            "QuarterlyRevenueGrowthYOY": "Revenue Growth YoY",
            "QuarterlyEarningsGrowthYOY": "Earnings Growth YoY",
        }

        # Fields rendered verbatim (already in correct unit or not financial amounts).
        verbatim_fields: dict[str, str] = {
            "PERatio": "P/E TTM",
            "DilutedEpsTTM": "EPS TTM (USD)",
            "EPSEstimateNextYear": "EPS Est. Next FY (USD)",
            "WallStreetTargetPrice": "Consensus Target (USD)",
            "MostRecentQuarter": "Most Recent Quarter",
        }

        lines: list[str] = []
        for key, label in large_usd_fields.items():
            if key in data:
                lines.append(f"- **{label}**: {self._fmt_usd_billions(data[key])}")
        for key, label in percent_fields.items():
            if key in data:
                lines.append(f"- **{label}**: {self._fmt_percent(data[key])}")
        for key, label in verbatim_fields.items():
            if key in data:
                lines.append(f"- **{label}**: {data[key]}")
        return "\n".join(lines) if lines else ""

    def format_relationships(self, ctx: Any) -> str:
        """Format entity relationships from the knowledge graph as a markdown table."""
        if ctx is None or ctx.entity_graph is None or not ctx.entity_graph.relationships:
            return ""
        lines = ["| Entity | Relation | Confidence |", "|--------|----------|------------|"]
        for rel in ctx.entity_graph.relationships[:10]:
            target = rel.get("target_name", rel.get("target_entity_id", "Unknown"))
            rel_type = rel.get("relation_type", "RELATED_TO")
            confidence = float(rel.get("confidence", 0.0))
            lines.append(f"| {target} | {rel_type} | {confidence:.0%} |")
        return "\n".join(lines)

    # ── Risk summary ───────────────────────────────────────────────────────────

    def build_morning_risk_summary(self, ctx: Any) -> dict[str, Any]:
        """Compute HHI concentration score from portfolio holdings.

        Mirrors the logic in GenerateBriefingUseCase._build_risk_summary() but
        operates on BriefingContext.portfolio rather than a raw dict.
        Returns 0.0 concentration when context or portfolio is unavailable.
        """
        concentration_score: float = 0.0
        sector_breakdown: dict[str, float] = {}

        if ctx is not None and ctx.portfolio is not None and ctx.portfolio.holdings:
            holdings = ctx.portfolio.holdings
            total_weight = sum(float(h.current_weight or 0.0) for h in holdings)
            if total_weight > 0:
                weights = [float(h.current_weight or 0.0) / total_weight for h in holdings]
                # Herfindahl-Hirschman Index normalised to [0, 1]
                concentration_score = round(sum(w * w for w in weights), 4)

        return {
            "concentration_score": concentration_score,
            "sector_breakdown": sector_breakdown,
        }

    # ── Citations / entity mentions ────────────────────────────────────────────

    def build_citations(self, ctx: Any) -> list[dict[str, Any]]:
        """Build a structured citation list from articles, events, and alerts in context.

        Each citation includes BOTH 'source_id' (legacy) and 'document_id' (PLAN-0062-W4)
        so older clients that read 'source_id' continue to work, and new clients can
        use 'document_id' (the canonical field on BriefCitation).

        PLAN-0062-W4 (T-W4-C-02): added 'document_id' and 'snippet' fields so the
        top-level citations list can be used by the frontend to display citation
        chips, while the per-bullet citations in BriefSection.bullets are the
        primary citation mechanism.

        WHY separate from materialize_brief_citations (on BriefParser): build_citations
        returns the top-level 'citations' list (legacy compatibility for old frontend code).
        materialize_brief_citations returns the ordered list used by the parser to
        resolve [cN] markers into per-bullet BriefCitation objects.
        """
        if ctx is None:
            return []
        citations: list[dict[str, Any]] = []

        # Articles
        for a in ctx.news_articles or []:
            title_part = (a.title or "")[:240]
            summary_part = (getattr(a, "summary", None) or "")[:160]
            snippet = (f"{title_part} — {summary_part}" if summary_part else title_part)[:400]
            citations.append(
                {
                    "source_type": "article",
                    # WHY both: back-compat (source_id) + new canonical (document_id)
                    "source_id": str(a.article_id),
                    "document_id": str(a.article_id),
                    "title": a.title,
                    "url": a.url,
                    "snippet": snippet[:400],
                }
            )

        # Structured events
        for ev in ctx.recent_events or []:
            event_text = getattr(ev, "event_text", "") or ""
            event_type = getattr(ev, "event_type", "") or ""
            snippet = f"{event_type}: {event_text[:200]}"[:400]
            citations.append(
                {
                    "source_type": "event",
                    "source_id": str(ev.event_id),
                    "document_id": str(ev.event_id),
                    "title": f"{event_type}: {event_text[:80]}",
                    "url": None,
                    "snippet": snippet,
                }
            )

        # Alerts (morning brief only — instrument context has no alerts)
        for alert in ctx.active_alerts or []:
            severity = getattr(alert, "severity", "").upper()
            alert_type = getattr(alert, "alert_type", "")
            message = (getattr(alert, "payload", None) or {}).get("message", "")
            snippet = f"[{severity}] {alert_type}: {message}"[:400]
            citations.append(
                {
                    "source_type": "alert",
                    "source_id": str(alert.alert_id),
                    "document_id": str(alert.alert_id),
                    "title": f"[{severity}] {alert_type}",
                    "url": None,
                    "snippet": snippet,
                }
            )

        return citations

    def extract_entity_mentions(self, ctx: Any) -> list[dict[str, Any]]:
        """Extract entity mentions from BriefingContext for the response payload.

        For morning briefs: extracts holdings + watchlist entities.
        For instrument briefs: extracts the center entity + relationship targets.

        Returns list of dicts with keys: entity_id, name, ticker.
        Deduplicates by entity_id (first occurrence wins).
        """
        if ctx is None:
            return []
        mentions: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Morning: portfolio holdings and watchlist
        if ctx.portfolio is not None:
            for h in ctx.portfolio.holdings:
                eid = str(h.entity_id) if h.entity_id else None
                if eid and eid not in seen and (h.canonical_name or h.ticker):
                    seen.add(eid)
                    mentions.append(
                        {
                            "entity_id": eid,
                            "name": h.canonical_name or h.ticker or "",
                            "ticker": h.ticker,
                        }
                    )
            for w in ctx.portfolio.watchlist:
                eid = str(w.entity_id) if w.entity_id else None
                if eid and eid not in seen and (w.canonical_name or w.ticker):
                    seen.add(eid)
                    mentions.append(
                        {
                            "entity_id": eid,
                            "name": w.canonical_name or w.ticker or "",
                            "ticker": w.ticker,
                        }
                    )

        # Instrument: center entity from entity_graph
        if ctx.entity_graph is not None:
            eid = ctx.entity_graph.entity_id
            if eid and eid not in seen and ctx.entity_graph.canonical_name:
                seen.add(eid)
                mentions.append(
                    {
                        "entity_id": eid,
                        "name": ctx.entity_graph.canonical_name,
                        "ticker": ctx.entity_graph.ticker,
                    }
                )
            # Relationship targets also become entity mentions
            for rel in ctx.entity_graph.relationships or []:
                target_id = rel.get("target_entity_id", "")
                target_name = rel.get("target_name", "")
                if target_id and target_id not in seen and target_name:
                    seen.add(target_id)
                    mentions.append(
                        {
                            "entity_id": target_id,
                            "name": target_name,
                            "ticker": None,
                        }
                    )

        return mentions
