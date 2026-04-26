"""GenerateBriefingUseCase — internal briefing endpoint logic (T-B-2-04, PRD-0016 §6.2).

Called by S10 email scheduler to generate a portfolio risk narrative for digest emails.
Also provides execute_public_morning() and execute_public_instrument() for the frontend
briefing API routes (public_briefings.py).

Auth:       Enforced by InternalJWTMiddleware (PRD-0025) at the API layer — no
            additional token check is required here.
Rate limit: 100 requests/day per user_id (Valkey counter with midnight-aligned key).
LLM:        EMAIL_DEEP_BRIEF_PROMPT via LLMProviderChain (collects full stream).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.application.pipeline.prompts.intent_prompts import EMAIL_DEEP_BRIEF_PROMPT
from rag_chat.domain.errors import RateLimitExceededError

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DAILY_RATE_LIMIT = 100
_BRIEFING_RL_PREFIX = "rag:v1:briefing:rl"
_BRIEFING_RL_TTL = 90_000  # 25 hours — covers DST edge cases

# Regex to strip <think>...</think> reasoning blocks emitted by some DeepSeek models.
# These blocks appear before the actual content and must be removed before returning
# the briefing to the frontend.
_REASONING_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    """Remove <think>…</think> reasoning blocks from LLM output.

    DeepSeek R1 models prepend chain-of-thought within <think> tags before the
    final answer.  We strip those before storing or returning the briefing content.
    """
    return _REASONING_RE.sub("", text).strip()


class GenerateBriefingUseCase:
    """Generate an AI-narrative portfolio risk brief for email delivery or frontend.

    Args:
        llm_chain:        LLM provider chain (DeepInfra → OpenRouter → Ollama).
        valkey:           Valkey client for daily rate-limit counters.
        context_gatherer: Optional BriefingContextGatherer for gathering upstream
                          context in execute_public_morning() / execute_public_instrument().
                          When None, public methods degrade gracefully.

    Note:
        Authentication is handled by InternalJWTMiddleware (PRD-0025) at the
        API layer before this use case is invoked.
    """

    def __init__(
        self,
        llm_chain: LLMProviderChain,
        valkey: ValkeyClient,  # type: ignore[name-defined]
        context_gatherer: BriefingContextGatherer | None = None,  # NEW — optional
    ) -> None:
        self._llm_chain = llm_chain
        self._valkey = valkey
        self._context_gatherer = context_gatherer  # None when wired without context gathering

    async def execute(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
    ) -> dict[str, Any]:
        """Run the briefing pipeline.

        Returns a dict with keys: narrative, risk_summary, citations, generated_at.

        Raises:
            RateLimitExceededError: User has exceeded 100 briefings today.
            ProviderUnavailableError: All LLM providers failed.
        """
        # ── 0. Anti-hallucination guard (BP-184) ─────────────────────────────
        # When portfolio_context is empty or contains no meaningful holdings/
        # positions, the LLM fabricates realistic-looking but false portfolio data.
        # Instead of letting that happen, return an empty narrative immediately so
        # the email template can render a "no data available" message rather than
        # fictional risk analysis.
        # WHY check market_snapshots type: the API schema validates it as
        # list[dict] with min_length=1 but we guard defensively here.
        _context_has_data = any(
            [
                portfolio_context.get("holdings"),
                portfolio_context.get("positions"),
                # Exclude the sentinel "morning_overview" type which carries no
                # real per-holding data — only real position snapshots count.
                bool(market_snapshots)
                and any(isinstance(s, dict) and s.get("type") != "morning_overview" for s in market_snapshots),
            ]
        )
        if not _context_has_data:
            log.warning(  # type: ignore[no-any-return]
                "briefing_empty_context_guard",
                user_id=str(user_id),
                detail="All context empty — returning placeholder narrative to prevent hallucination",
            )
            return {
                "narrative": "",
                "risk_summary": {},
                "citations": [],
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }

        # ── 1. Daily rate limit (100/day per user_id) ─────────────────────────
        await self._check_daily_rate_limit(user_id)

        # ── 3. Build prompt ───────────────────────────────────────────────────
        prompt = self._build_prompt(
            user_id=user_id,
            tenant_id=tenant_id,
            portfolio_context=portfolio_context,
            market_snapshots=market_snapshots,
            active_signals=active_signals,
            lookback_days=lookback_days,
        )

        # ── 4. LLM completion (collect streaming tokens) ─────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(
            prompt,
            max_tokens=6000,
            temperature=0.1,
        ):
            chunks.append(chunk)
        narrative = "".join(chunks)

        # ── 5. Derive risk_summary from input signals ─────────────────────────
        risk_summary = self._build_risk_summary(
            portfolio_context=portfolio_context,
            active_signals=active_signals,
        )

        generated_at = datetime.now(tz=UTC).isoformat()

        log.info(  # type: ignore[no-any-return]
            "briefing_generated",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            narrative_chars=len(narrative),
        )

        return {
            "narrative": narrative,
            "risk_summary": risk_summary,
            "citations": [],
            "generated_at": generated_at,
        }

    async def _check_daily_rate_limit(self, user_id: UUID) -> None:
        """Increment the daily briefing counter and raise if over limit.

        Key format: ``rag:v1:briefing:rl:{user_id}:{YYYY-MM-DD}`` (UTC date).
        TTL is 25 hours to cover DST transitions.
        """
        today = datetime.now(tz=UTC).date().isoformat()
        key = f"{_BRIEFING_RL_PREFIX}:{user_id}:{today}"

        count = await self._valkey.incr(key)
        if count == 1:
            # First request today — set expiry
            await self._valkey.expire(key, _BRIEFING_RL_TTL)

        if count > _DAILY_RATE_LIMIT:
            raise RateLimitExceededError(
                f"Briefing rate limit exceeded: {count} requests today (limit: {_DAILY_RATE_LIMIT})",
            )

    def _build_prompt(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
    ) -> str:
        """Assemble the EMAIL_DEEP_BRIEF prompt with XML-wrapped context."""
        context_block = (
            f"<portfolio_context>\n{json.dumps(portfolio_context, indent=2)}\n</portfolio_context>\n\n"
            f"<market_snapshots lookback_days='{lookback_days}'>\n"
            f"{json.dumps(market_snapshots, indent=2)}\n</market_snapshots>\n\n"
        )
        if active_signals:
            context_block += f"<active_signals>\n{json.dumps(active_signals, indent=2)}\n</active_signals>\n\n"

        return (
            f"{EMAIL_DEEP_BRIEF_PROMPT}\n\n"
            f"<context>\n{context_block}</context>\n\n"
            f"Generate the portfolio risk brief for user {user_id} (tenant {tenant_id})."
        )

    def _build_risk_summary(
        self,
        *,
        portfolio_context: dict[str, Any],
        active_signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Derive a structured risk summary from input data (no extra LLM call).

        Computes a simple concentration score from portfolio positions if available.
        """
        positions: list[dict[str, Any]] = portfolio_context.get("positions", [])

        # Concentration score: 1.0 = fully concentrated in one position
        concentration_score: float = 0.0
        sector_breakdown: dict[str, float] = {}
        if positions:
            total_value = sum(float(p.get("value", 0)) for p in positions)
            if total_value > 0:
                weights = [float(p.get("value", 0)) / total_value for p in positions]
                # Herfindahl-Hirschman Index normalised to [0, 1]
                concentration_score = round(sum(w * w for w in weights), 4)

            for pos in positions:
                sector = str(pos.get("sector", "unknown"))
                value = float(pos.get("value", 0))
                sector_breakdown[sector] = round(
                    sector_breakdown.get(sector, 0.0) + (value / total_value if total_value > 0 else 0.0),
                    4,
                )

        top_risk_signals = [
            {"signal_id": str(s.get("id", "")), "description": str(s.get("description", ""))}
            for s in active_signals[:5]  # cap at 5 top signals
        ]

        return {
            "concentration_score": concentration_score,
            "top_risk_signals": top_risk_signals,
            "sector_breakdown": sector_breakdown,
        }

    # ── Public briefing methods (frontend-facing) ────────────────────────────

    async def execute_public_morning(
        self,
        user_id: str,
        tenant_id: str,
        internal_jwt: str | None = None,
    ) -> dict[str, Any]:
        """Generate a morning portfolio briefing for an authenticated frontend user.

        Called by GET /api/v1/briefings/morning (public_briefings.py route).
        Uses BriefingContextGatherer to assemble context from S1/S3/S5/S6/S7,
        then renders MORNING_BRIEFING prompt and streams LLM completion.

        Rate-limited: 100 requests/day per user_id (same counter as execute()).

        Returns dict with keys: content, risk_summary, entity_mentions, citations, generated_at

        Raises:
            RateLimitExceededError: User has exceeded 100 briefings today.
            ProviderUnavailableError: All LLM providers failed.
        """
        from prompts._safety import SAFETY_FOOTER  # type: ignore[import-untyped]
        from prompts.briefing.morning import MORNING_BRIEFING  # type: ignore[import-untyped]

        # ── 1. Daily rate limit (shared counter with execute()) ───────────────
        # WHY convert to UUID: _check_daily_rate_limit builds a Valkey key with
        # str(user_id) — a UUID string is stable and avoids ambiguous formats.
        try:
            uid_for_rl = UUID(user_id)
        except (ValueError, AttributeError):
            uid_for_rl = UUID("00000000-0000-0000-0000-000000000000")
        await self._check_daily_rate_limit(uid_for_rl)

        # ── 2. Gather context via BriefingContextGatherer ─────────────────────
        ctx = None
        if self._context_gatherer is not None:
            try:
                ctx = await self._context_gatherer.gather_morning_context(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    internal_jwt=internal_jwt,
                )
            except Exception as exc:
                # R9 safe degradation: log warning, proceed without context
                log.warning("morning_context_gathering_failed", error=str(exc))  # type: ignore[no-any-return]
                ctx = None

        # ── 3. Build prompt sections from context ─────────────────────────────
        # WHY: datetime.now(tz=UTC).date() is the UTC-aware equivalent of date.today()
        # and avoids DTZ011 (date.today() is timezone-naive).
        today = datetime.now(tz=UTC).date().isoformat()
        portfolio_text = _format_portfolio_morning(ctx)
        news_text = _format_news(ctx)
        alerts_text = _format_alerts(ctx)
        market_text = _format_market_overview(ctx)
        events_text = _format_events(ctx)

        prompt = MORNING_BRIEFING.render(
            safety=SAFETY_FOOTER,
            current_date=today,
            portfolio_context=portfolio_text,
            news_context=news_text,
            alerts_context=alerts_text,
            market_overview=market_text,
            events_context=events_text,
        )

        # ── 4. LLM completion (collect streaming tokens) ──────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(prompt, max_tokens=2000, temperature=0.1):
            chunks.append(chunk)
        content = _strip_reasoning("".join(chunks))

        # ── 5. Derive risk_summary from portfolio holdings (HHI concentration) ─
        risk_summary = _build_morning_risk_summary(ctx)

        # ── 6. Build citations and entity mentions from gathered context ───────
        citations = _build_citations(ctx)
        entity_mentions = _extract_entity_mentions(ctx)

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "morning_briefing_generated",
            user_id=user_id,
            chars=len(content),
        )

        return {
            "content": content,
            "risk_summary": risk_summary,
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
        }

    async def execute_public_instrument(
        self,
        entity_id: str,
    ) -> dict[str, Any]:
        """Generate an instrument-specific briefing.

        Called by GET /api/v1/briefings/instrument/{entity_id}.
        Uses BriefingContextGatherer to fetch entity graph + fundamentals + news.

        Returns dict with keys: content, risk_summary (None), entity_mentions, citations, generated_at

        Raises:
            EntityNotFoundError: entity_id not found in knowledge graph.
            ProviderUnavailableError: All LLM providers failed.
        """
        from prompts._safety import SAFETY_FOOTER  # type: ignore[import-untyped]
        from prompts.briefing.instrument import INSTRUMENT_BRIEFING  # type: ignore[import-untyped]

        if self._context_gatherer is None:
            # No context gatherer wired — degrade gracefully rather than crashing
            log.warning("instrument_brief_no_context_gatherer", entity_id=entity_id)  # type: ignore[no-any-return]
            return {
                "content": "Instrument briefing context gatherer not configured.",
                "risk_summary": None,
                "entity_mentions": [],
                "citations": [],
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }

        # gather_instrument_context raises EntityNotFoundError if entity not in KG
        # — let the exception propagate to the route handler for a 404 response
        ctx = await self._context_gatherer.gather_instrument_context(entity_id=entity_id)

        # ── Build prompt sections ─────────────────────────────────────────────
        entity_text = _format_entity_context(ctx)
        fundamentals_text = _format_fundamentals(ctx)
        news_text = _format_news(ctx)
        events_text = _format_events(ctx)
        relationships_text = _format_relationships(ctx)

        prompt = INSTRUMENT_BRIEFING.render(
            safety=SAFETY_FOOTER,
            entity_context=entity_text,
            fundamentals_context=fundamentals_text,
            news_context=news_text,
            events_context=events_text,
            relationships_context=relationships_text,
        )

        # ── LLM completion ────────────────────────────────────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(prompt, max_tokens=1500, temperature=0.1):
            chunks.append(chunk)
        content = _strip_reasoning("".join(chunks))

        # ── Build citations and entity mentions ───────────────────────────────
        citations = _build_citations(ctx)
        entity_mentions = _extract_entity_mentions(ctx)

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "instrument_briefing_generated",
            entity_id=entity_id,
            chars=len(content),
        )

        return {
            "content": content,
            "risk_summary": None,  # instrument brief has no portfolio — risk_summary is None
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
        }


# ── Module-level context-formatting helpers ──────────────────────────────────
# These functions accept a BriefingContext (or None) and return formatted strings
# for use in prompt templates. They are module-level (not methods) so they can
# be used by both execute_public_morning() and execute_public_instrument().


def _format_portfolio_morning(ctx: Any) -> str:
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


def _format_news(ctx: Any) -> str:
    """Format news articles from context into a readable list."""
    if ctx is None or not ctx.news_articles:
        return ""
    lines: list[str] = []
    for a in ctx.news_articles[:8]:
        date_str = a.published_at.strftime("%Y-%m-%d") if a.published_at else "unknown date"
        score = f" (relevance: {a.display_relevance_score:.0%})" if a.display_relevance_score else ""
        lines.append(f"- [{date_str}] {a.title}{score}")
        if a.url:
            lines.append(f"  Source: {a.url}")
    return "\n".join(lines)


def _format_alerts(ctx: Any) -> str:
    """Format active alerts from context."""
    if ctx is None or not ctx.active_alerts:
        return ""
    lines: list[str] = []
    for alert in ctx.active_alerts[:5]:
        lines.append(
            f"- [{alert.severity.upper()}] {alert.alert_type}: {alert.payload.get('message', '')}",
        )
    return "\n".join(lines)


def _format_market_overview(ctx: Any) -> str:
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


def _format_events(ctx: Any) -> str:
    """Format structured events from context."""
    if ctx is None or not ctx.recent_events:
        return ""
    lines: list[str] = []
    for ev in ctx.recent_events[:6]:
        date_str = ev.event_date.strftime("%Y-%m-%d") if ev.event_date else "unknown date"
        lines.append(f"- [{date_str}] {ev.event_type}: {ev.event_text[:200]}")
    return "\n".join(lines)


def _format_entity_context(ctx: Any) -> str:
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


def _format_fundamentals(ctx: Any) -> str:
    """Format fundamental data highlights for an instrument brief.

    Reports a curated set of financial metrics when present in the data dict.
    Missing metrics are silently omitted (no 'N/A' placeholders — prompt template
    instructs the LLM to write 'Not in retrieved context' for absent metrics).
    """
    if ctx is None or ctx.fundamentals is None:
        return ""
    field_labels = {
        "MarketCapitalization": "Market Cap (USD)",
        "PERatio": "P/E TTM",
        "DilutedEpsTTM": "EPS TTM (USD)",
        "RevenueTTM": "Revenue TTM (USD)",
        "ProfitMargin": "Net Profit Margin",
        "OperatingMarginTTM": "Operating Margin TTM",
        "EPSEstimateNextYear": "EPS Estimate Next FY (USD)",
        "WallStreetTargetPrice": "Consensus Target (USD)",
        "MostRecentQuarter": "Most Recent Quarter",
        "QuarterlyRevenueGrowthYOY": "Revenue Growth YoY",
        "QuarterlyEarningsGrowthYOY": "Earnings Growth YoY",
    }
    lines: list[str] = []
    data = ctx.fundamentals.data
    for key, label in field_labels.items():
        if key in data:
            lines.append(f"- **{label}**: {data[key]}")
    return "\n".join(lines) if lines else ""


def _format_relationships(ctx: Any) -> str:
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


def _build_morning_risk_summary(ctx: Any) -> dict[str, Any]:
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


def _build_citations(ctx: Any) -> list[dict[str, Any]]:
    """Build a structured citation list from articles, events, and alerts in context.

    Each citation matches the BriefingCitation schema:
        source_type: "article" | "event" | "alert"
        source_id:   str (UUID)
        title:       str
        url:         str | None
    """
    if ctx is None:
        return []
    citations: list[dict[str, Any]] = []

    # Articles
    for a in ctx.news_articles or []:
        citations.append(
            {
                "source_type": "article",
                "source_id": str(a.article_id),
                "title": a.title,
                "url": a.url,
            }
        )

    # Structured events
    for ev in ctx.recent_events or []:
        citations.append(
            {
                "source_type": "event",
                "source_id": str(ev.event_id),
                "title": f"{ev.event_type}: {ev.event_text[:80]}",
                "url": None,
            }
        )

    # Alerts (morning brief only — instrument context has no alerts)
    for alert in ctx.active_alerts or []:
        citations.append(
            {
                "source_type": "alert",
                "source_id": str(alert.alert_id),
                "title": f"[{alert.severity.upper()}] {alert.alert_type}",
                "url": None,
            }
        )

    return citations


def _extract_entity_mentions(ctx: Any) -> list[dict[str, Any]]:
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
