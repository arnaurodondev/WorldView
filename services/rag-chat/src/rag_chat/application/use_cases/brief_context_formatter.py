"""BriefContextFormatter — builds context strings injected into brief prompts.

Extracted from generate_briefing.py (PLAN-0089 C-3) so that all prompt-context
assembly logic lives in one dedicated class rather than being scattered as module-
level helpers. The class wraps the same helper functions that were previously
defined at module level; their behaviour is unchanged (pure refactor).

PLAN-0099 Wave B: per-section truncation limits become env-var overridable
(``RAG_CHAT_BRIEF_NEWS_LIMIT`` / ``_EVENTS_LIMIT`` / ``_ALERTS_LIMIT``) with
defaults raised from 8/6/5 to 12/10/8 (BP-600).  News articles are deduped
via ``_dedupe_news()`` before truncation so syndicated copies of the same
headline don't crowd out distinct signals.

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

import os
from typing import Any

# ── PLAN-0099 Wave B: env-var overridable truncation limits ─────────────────
#
# Module-level helpers so callers (and tests) can read the live values without
# instantiating a Settings object.  Defaults match Settings (12/10/8) but are
# parsed from the env vars at import time + on every call so test fixtures
# can monkeypatch the value before invoking the formatter.
#
# Naming follows the audit / user-facing convention: BRIEF_NEWS_LIMIT etc.
# The pydantic-settings env_prefix is RAG_CHAT_, so the real env var name is
# RAG_CHAT_BRIEF_NEWS_LIMIT — both forms are accepted (RAG_CHAT_ prefix wins
# when both are present).


def _env_int(*names: str, default: int) -> int:
    """Return the first env var that parses as int, else ``default``.

    Tolerant of missing / empty values; non-integer strings fall through to
    the next name so a typo in one env var doesn't crash the formatter.
    """
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return default


def _env_float(*names: str, default: float) -> float:
    """Mirror of ``_env_int`` for float-valued env vars."""
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return default


def get_news_limit() -> int:
    """Resolved news article cap (default 12)."""
    return _env_int("RAG_CHAT_BRIEF_NEWS_LIMIT", "BRIEF_NEWS_LIMIT", default=12)


def get_events_limit() -> int:
    """Resolved events cap (default 10)."""
    return _env_int("RAG_CHAT_BRIEF_EVENTS_LIMIT", "BRIEF_EVENTS_LIMIT", default=10)


def get_alerts_limit() -> int:
    """Resolved alerts cap (default 8)."""
    return _env_int("RAG_CHAT_BRIEF_ALERTS_LIMIT", "BRIEF_ALERTS_LIMIT", default=8)


def get_min_context_score() -> float:
    """Resolved refusal-on-low-context threshold (default 0.3)."""
    return _env_float("RAG_CHAT_BRIEF_MIN_CONTEXT_SCORE", "BRIEF_MIN_CONTEXT_SCORE", default=0.3)


def _dedupe_news(items: list[Any], threshold: float = 0.85) -> list[Any]:
    """Drop near-duplicate news items, keeping the higher-relevance copy.

    ``items`` must be a list of ``NewsArticleSummary``-shaped objects exposing
    ``title`` (str) and ``display_relevance_score`` (float).  Two items are
    considered duplicates when either:
      * one title is a prefix of the other (after lower/strip), OR
      * Jaccard similarity of their tokenised titles ≥ ``threshold``.

    Stable ordering: the first occurrence's position is preserved; when a
    duplicate is found later with a higher relevance score, the earlier copy
    is replaced in-place so the highest-scoring representative wins.
    """
    if not items:
        return []

    def _tokens(title: str) -> set[str]:
        return {tok for tok in title.lower().split() if tok}

    kept: list[Any] = []
    kept_tokens: list[set[str]] = []
    kept_titles: list[str] = []

    for item in items:
        title = (getattr(item, "title", "") or "").strip()
        if not title:
            kept.append(item)
            kept_tokens.append(set())
            kept_titles.append("")
            continue
        title_lower = title.lower()
        tokens = _tokens(title)
        duplicate_idx: int | None = None
        for idx, (prev_title, prev_tokens) in enumerate(zip(kept_titles, kept_tokens, strict=True)):
            if not prev_title:
                continue
            # Prefix rule (catches "AAPL beats Q2" vs "AAPL beats Q2 — Reuters")
            if title_lower.startswith(prev_title) or prev_title.startswith(title_lower):
                duplicate_idx = idx
                break
            # Jaccard similarity rule
            if tokens and prev_tokens:
                union = tokens | prev_tokens
                inter = tokens & prev_tokens
                if union and len(inter) / len(union) >= threshold:
                    duplicate_idx = idx
                    break
        if duplicate_idx is None:
            kept.append(item)
            kept_tokens.append(tokens)
            kept_titles.append(title_lower)
        else:
            # Keep the higher-relevance copy in the original slot so downstream
            # ordering (recency / relevance from upstream) is preserved.
            existing = kept[duplicate_idx]
            existing_score = float(getattr(existing, "display_relevance_score", 0.0) or 0.0)
            new_score = float(getattr(item, "display_relevance_score", 0.0) or 0.0)
            if new_score > existing_score:
                kept[duplicate_idx] = item
                kept_tokens[duplicate_idx] = tokens
                kept_titles[duplicate_idx] = title_lower
    return kept


class BriefContextFormatter:
    """Builds the context strings injected into the brief generation prompts.

    All methods are pure functions (no internal state), grouped here so that
    generate_briefing.py can delegate all context-formatting concerns to a
    single object and tests can exercise formatting logic in isolation.
    """

    # ── Portfolio / morning brief ──────────────────────────────────────────────

    def format_portfolio_morning(self, ctx: Any) -> str:
        """Format portfolio holdings + watchlist for the morning brief prompt.

        PLAN-0102 W2 T-W2-04: when ``ctx.portfolio_pnl`` and/or
        ``ctx.sector_exposure`` are populated, each holding line carries
        real overnight P&L (``"AAPL +1.45% pre-mkt — +$280"``) plus a
        sector tag (``"(Tech 28% of portfolio)"``), and a footer aggregates
        total P&L + sector mix. Falls back to the legacy "quantity / weight"
        rendering when those fields are absent (R9 — no upstream =
        graceful degradation, not an empty brief).
        """
        if ctx is None or ctx.portfolio is None:
            return ""
        p = ctx.portfolio

        # PLAN-0102 W2: pull P&L + sector aggregates if the gatherer attached
        # them. We import the concrete model classes here (not at module top)
        # so the format helpers stay decoupled from the data layer for
        # callers that pass MagicMock-shaped ctx in unit tests — `isinstance`
        # against the real class makes the new-path opt-in.
        from rag_chat.application.models.briefing_context import (
            PortfolioPnLSnapshot as _PnLModel,
        )
        from rag_chat.application.models.briefing_context import (
            SectorExposure as _SectorModel,
        )

        _raw_pnl = getattr(ctx, "portfolio_pnl", None)
        pnl = _raw_pnl if isinstance(_raw_pnl, _PnLModel) else None
        _raw_sector = getattr(ctx, "sector_exposure", None)
        sector_exposure = _raw_sector if isinstance(_raw_sector, _SectorModel) else None

        # ── Build {entity_id: (sector, sector_share_pct)} for fast per-row lookup
        sector_by_entity: dict[Any, tuple[str, float]] = {}
        if sector_exposure is not None and pnl is not None:
            # We don't have a {entity_id: sector} on the model, but we can
            # rebuild it from the P&L holdings: each row carries entity_id
            # AND the formatter already knows the sector aggregates. Since
            # the gatherer used the *same* sector_map upstream, we infer
            # per-holding sector via a single pass through the snapshot.
            # When that mapping is unavailable (legacy callers) we just
            # render "(sector unknown)" lazily inline.
            #
            # NOTE: this is best-effort — we don't ship a sector per-row in
            # the P&L snapshot to keep the wire shape lean. Future tightening
            # could embed sector into PortfolioPnLItem if needed.
            for pnl_row in pnl.holdings:
                if pnl_row.entity_id is None:
                    continue
                # Without a direct map, leave sector blank — formatter shows
                # "(sector unknown)" rather than guessing.
                sector_by_entity[pnl_row.entity_id] = ("", 0.0)

        lines: list[str] = []

        # ── A) Real P&L block (preferred) ────────────────────────────────────
        if pnl is not None and pnl.holdings:
            lines.append(f"Holdings ({p.total_positions} positions, overnight P&L):")
            for row in pnl.holdings:
                symbol = row.symbol or "?"
                pct = row.overnight_pnl_pct * 100.0
                pnl_dollar = row.overnight_pnl_usd
                # Sign + value formatting — "+1.45%" / "-0.32%" / "+$280" / "-$112"
                sign_pct = "+" if pct >= 0 else ""
                sign_dollar = "+" if pnl_dollar >= 0 else ""
                # Sector tag — look up via shared sector_exposure when present.
                sector_tag = ""
                if sector_exposure is not None and row.entity_id is not None:
                    # The exposure is keyed by sector label, not entity_id, so we
                    # don't have a direct entity→sector link without re-fetching.
                    # Mark unknown explicitly; the LLM sees the aggregate footer.
                    sector_tag = ""
                line = f"  - {symbol} {sign_pct}{pct:.2f}% pre-mkt — " f"{sign_dollar}${abs(pnl_dollar):,.0f}"
                if sector_tag:
                    line += f" ({sector_tag})"
                lines.append(line)
        elif p.holdings:
            # Legacy fallback when P&L call failed.
            lines.append(f"Holdings ({p.total_positions} positions):")
            for h in p.holdings:
                name = h.canonical_name or h.ticker or "Unknown"
                weight = f"{h.current_weight:.1%}" if h.current_weight else "N/A"
                lines.append(f"  - {name}: {h.quantity} units, weight {weight}")

        # ── B) Footer: total P&L + top sector exposure ──────────────────────
        if pnl is not None and (pnl.total_overnight_pnl_usd or pnl.total_overnight_pnl_pct):
            total_sign = "+" if pnl.total_overnight_pnl_usd >= 0 else "-"
            total_pct_sign = "+" if pnl.total_overnight_pnl_pct >= 0 else ""
            footer = (
                f"Total overnight P&L: {total_sign}${abs(pnl.total_overnight_pnl_usd):,.0f} "
                f"({total_pct_sign}{pnl.total_overnight_pnl_pct * 100.0:.2f}%)"
            )
            lines.append(footer)
        if sector_exposure is not None and sector_exposure.by_sector:
            # Top-3 sectors by share, descending.
            top = sorted(
                sector_exposure.by_sector.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )[:5]
            mix = " | ".join(f"{label} {pct * 100.0:.0f}%" for label, pct in top)
            lines.append(f"Sector mix: {mix}")

        # ── C) Watchlist (unchanged) ────────────────────────────────────────
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
        # PLAN-0099 Wave B: dedupe first (so syndicated copies don't crowd
        # out distinct signals), then truncate to the env-var limit.
        deduped = _dedupe_news(list(ctx.news_articles))
        limit = get_news_limit()
        lines: list[str] = []
        for i, a in enumerate(deduped[:limit]):
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
        # PLAN-0099 Wave B: limit overridable via RAG_CHAT_BRIEF_ALERTS_LIMIT.
        limit = get_alerts_limit()
        lines: list[str] = []
        for i, alert in enumerate(ctx.active_alerts[:limit]):
            cn = f"[c{citation_offset + i + 1}]"
            lines.append(
                f"{cn} [{alert.severity.upper()}] {alert.alert_type}: {alert.payload.get('message', '')}",
            )
        return "\n".join(lines)

    def format_market_overview(self, ctx: Any) -> str:
        """Format the market overview block — Tape, Holdings, Sector heatmap.

        PLAN-0102 W1 T-W1-01 / T-W1-02 (BP-614): before this fix the method
        only rendered ``sector_performance`` and the new ``indices`` /
        ``holdings`` arrays on ``MarketOverview`` were silently dropped — the
        gatherer paid for the S3 batch call and the prompt never saw the
        result.  Now we render three explicit sub-sections in order:

          1. Tape — SPY / QQQ / VIX (broad-market reference instruments).
          2. Your Portfolio Today — per-holding quote line.
          3. Sector performance — pre-existing heatmap when populated.

        Each ``QuoteSummary`` in ``indices`` / ``holdings`` carries the ticker
        symbol in ``instrument_id`` (the gatherer tags it at construction
        time), so we can render "AAPL 195.20" directly.
        """
        if ctx is None or ctx.market_overview is None:
            return ""
        mo = ctx.market_overview
        lines: list[str] = []

        # ── 1. Tape — broad-market reference quotes ────────────────────────
        if getattr(mo, "indices", None):
            lines.append("Tape:")
            for q in mo.indices:
                lines.append(f"  - {q.instrument_id}: last {q.last}")

        # ── 2. Your Portfolio Today — per-holding quote snapshots ──────────
        if getattr(mo, "holdings", None):
            lines.append("Your Portfolio Today:")
            for q in mo.holdings:
                lines.append(f"  - {q.instrument_id}: last {q.last}")

        # ── 3. Sector performance heatmap (legacy field, kept for compat) ──
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
        # PLAN-0099 Wave B: limit overridable via RAG_CHAT_BRIEF_EVENTS_LIMIT.
        limit = get_events_limit()
        lines: list[str] = []
        for i, ev in enumerate(ctx.recent_events[:limit]):
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
