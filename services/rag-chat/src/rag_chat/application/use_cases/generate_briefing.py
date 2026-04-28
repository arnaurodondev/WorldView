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

# Matches both [N] (literal letter N used by LLM as a citation placeholder) and
# [1], [2], [3] etc. (digit-indexed citations the LLM emits when items are present).
_ORPHAN_CITATION_RE = re.compile(r"\s*\[(?:\d+|N)\]")

# Some LLMs wrap their output in a ```markdown ... ``` code fence even when not asked.
# Strip leading/trailing fence markers so the frontend receives raw markdown.
_CODE_FENCE_RE = re.compile(r"^\s*```(?:markdown)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks, markdown code fences, and orphaned [N] markers.

    DeepSeek R1 models prepend chain-of-thought within <think> tags before the
    final answer.  Some LLMs also wrap the answer in ```markdown ... ``` fences.
    Both are stripped before returning the briefing to the frontend.
    """
    text = _REASONING_RE.sub("", text).strip()
    # Strip outer ```markdown ... ``` or ``` ... ``` code fences the LLM may emit.
    m = _CODE_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # Strip [N] citation markers — briefings never have a citations array so any
    # [N] the LLM emits are orphaned and confusing to the end user.
    text = _ORPHAN_CITATION_RE.sub("", text)
    return text


# ── Two-tier brief splitter (PLAN-0048 Wave A, prompt v2.2) ─────────────────
#
# The v2.2 MORNING_BRIEFING prompt forces the LLM to emit:
#
#     ## SUMMARY
#     <1-2 sentences>
#
#     ---
#
#     ## DETAILS
#     ### Market Overview
#     ...
#
# We split on the FIRST line that is exactly ``---`` (after trim) so:
#   - The summary half feeds the collapsed card view (replaces line-clamp-3).
#   - The details half feeds the expanded card view.
#
# WHY a strict line-mode split (not ``str.split("---", 1)``):
# Markdown content can legitimately contain ``---`` mid-paragraph (e.g. an
# em-dash range). Requiring the divider to be on its own line eliminates
# false-positive splits.
def _split_summary_and_details(content: str) -> tuple[str | None, str]:
    """Split a v2.2 morning brief into ``(summary, narrative)``.

    The LLM is instructed to emit a ``## SUMMARY`` block, a literal ``---``
    divider line, then a ``## DETAILS`` block. Older prompts and instrument
    briefs emit a single block with no divider — those return ``(None, full_text)``
    so the frontend can degrade gracefully.

    Both returned strings have their leading ``## SUMMARY`` / ``## DETAILS``
    headers stripped — the card chrome already labels the two views, so the
    duplicate headers would just steal vertical space.
    """
    if not content:
        return None, content

    lines = content.splitlines()
    divider_idx: int | None = None
    # Walk the first ~50 lines looking for a bare "---" line. We cap the search
    # because a divider after that point almost certainly belongs to a markdown
    # rule inside the body, not to our two-tier separator.
    for i, line in enumerate(lines[:50]):
        if line.strip() == "---":
            divider_idx = i
            break

    if divider_idx is None:
        # No divider found — assume legacy single-block output. Return the full
        # content as the narrative and leave summary unset.
        return None, content

    summary_block = "\n".join(lines[:divider_idx]).strip()
    details_block = "\n".join(lines[divider_idx + 1 :]).strip()

    # Strip the redundant block headers ("## SUMMARY" / "## DETAILS") — the
    # frontend chrome already labels these regions, so the headers would
    # double-decorate the rendered output.
    summary_block = _strip_block_header(summary_block, "summary")
    details_block = _strip_block_header(details_block, "details")

    # Defensive: if the summary block is empty after stripping, fall back to
    # treating the full content as narrative. An empty summary would render as
    # a blank line in the collapsed view which is worse than a clamp-3 fallback.
    if not summary_block:
        return None, content

    return summary_block, details_block or content


def _parse_sections_from_markdown(markdown: str) -> list[dict[str, Any]]:
    """Parse a markdown narrative into structured ``[{title, bullets[]}]`` sections.

    Recognised section headings: ``## Heading``, ``### Heading``, or bold-only lines
    (``**Heading**``). Bullets: lines starting with ``- ``, ``* `` or ``• ``.

    PLAN-0049 T-A-1-04: when the LLM honours the v2.2 prompt and emits a clean
    ``## DETAILS`` block split into ``### Drivers`` / ``### Implications`` /
    ``### Risks``, this parser produces a structured ``BriefSection[]`` payload
    that the frontend renders as polished cards. When parsing fails (no
    headings, no bullets, malformed markdown) we return ``[]`` and the
    frontend falls back to ``<MarkdownContent>`` over the raw narrative —
    no UI breakage either way.

    Hard caps: ≤8 bullets per section, ≤120 chars per section title — matches
    the ``BriefSection`` Pydantic constraints so callers can hand the result
    straight to ``BriefSection(**...)`` without further validation.
    """
    if not markdown or not markdown.strip():
        return []

    sections: list[dict[str, Any]] = []
    current_title: str | None = None
    current_bullets: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_bullets
        if current_title and current_bullets:
            # Cap bullets to 8 (matches Pydantic `max_length=8`); cap title to 120.
            sections.append(
                {
                    "title": current_title[:120],
                    "bullets": current_bullets[:8],
                }
            )
        current_title = None
        current_bullets = []

    heading_re = re.compile(r"^\s{0,3}(#{2,3})\s+(.+?)\s*$")
    bold_only_re = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
    bullet_re = re.compile(r"^\s*(?:[-*•])\s+(.+)$")

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m_h = heading_re.match(line)
        m_b = bold_only_re.match(line) if not m_h else None
        if m_h:
            flush()
            current_title = m_h.group(2).strip()
            continue
        if m_b:
            flush()
            current_title = m_b.group(1).strip()
            continue
        m_bullet = bullet_re.match(line)
        if m_bullet and current_title:
            bullet_text = m_bullet.group(1).strip()
            if bullet_text:
                current_bullets.append(bullet_text)
    flush()

    # Discard the result if it's a single section with one bullet — that means
    # we mis-parsed prose as a section. Frontend renders narrative instead.
    if len(sections) == 1 and len(sections[0]["bullets"]) <= 1:
        return []
    return sections


def _strip_block_header(block: str, expected: str) -> str:
    """Remove a leading ``## SUMMARY`` / ``## DETAILS`` header from ``block``.

    Case-insensitive; tolerates 1-3 leading ``#`` characters and an optional
    trailing colon. Returns the block unchanged if no matching header is found.
    """
    lines = block.splitlines()
    if not lines:
        return block
    first = lines[0].strip().lower().rstrip(":")
    # Match "# summary", "## summary", "### summary" — same for "details".
    if first in (f"# {expected}", f"## {expected}", f"### {expected}", expected):
        return "\n".join(lines[1:]).lstrip()
    return block


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

        # ── 3b. Empty context guard ───────────────────────────────────────────
        # WHY: When all upstream services are unavailable or return empty data,
        # the LLM receives a completely empty prompt and degrades to a retail-grade
        # disclaimer ("Please ensure all relevant context sections are populated").
        # This is unacceptable for institutional users. Return a professional
        # placeholder so the UI renders something useful instead of LLM confusion.
        all_sections_empty = not any([portfolio_text, news_text, alerts_text, market_text, events_text])
        if all_sections_empty:
            log.warning("morning_briefing_empty_context", user_id=user_id)  # type: ignore[no-any-return]
            generated_at = datetime.now(tz=UTC).isoformat()
            return {
                "content": (
                    "Portfolio data is being synchronized with upstream services. "
                    "Your morning briefing will be available shortly — "
                    "please refresh in a few minutes."
                ),
                "risk_summary": _build_morning_risk_summary(ctx),
                "entity_mentions": [],
                "citations": [],
                "generated_at": generated_at,
            }

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

        # ── 4b. Two-tier split (PLAN-0048 Wave A) ─────────────────────────────
        # The v2.2 MORNING_BRIEFING prompt asks the LLM to emit a ``## SUMMARY``
        # block + ``---`` divider + ``## DETAILS`` block. Splitting here lets the
        # frontend show the summary in the collapsed card and the details when
        # expanded, eliminating the redundant "Morning Briefing" / date headers
        # that wasted ~15% of the dashboard row before this change.
        # Returns (None, full_content) for legacy single-block output so the UI
        # can fall back to the old line-clamp-3 path.
        summary, narrative = _split_summary_and_details(content)

        # ── 5. Derive risk_summary from portfolio holdings (HHI concentration) ─
        risk_summary = _build_morning_risk_summary(ctx)

        # ── 6. Build citations and entity mentions from gathered context ───────
        citations = _build_citations(ctx)
        entity_mentions = _extract_entity_mentions(ctx)

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "morning_briefing_generated",
            user_id=user_id,
            # Track whether the LLM honored the v2.2 two-tier contract. If
            # has_summary is consistently False in production we know the model
            # is ignoring the format directive and we can adjust temperature
            # or switch providers.
            chars=len(narrative),
            has_summary=summary is not None,
        )

        # PLAN-0049 T-A-1-04: parse narrative into structured sections so the
        # frontend can render polished cards instead of raw markdown. Returns []
        # when parsing fails — frontend falls back to MarkdownContent on narrative.
        structured_sections = _parse_sections_from_markdown(narrative)

        return {
            # ``content`` keeps the field name expected by the route layer (which
            # maps result["content"] → response.narrative). The narrative half of
            # the split goes here so the expanded card view shows the structured
            # ## DETAILS sections without the redundant ## SUMMARY heading.
            "content": narrative,
            # ``summary`` is the new field — None when the LLM didn't emit the
            # v2.2 two-tier format (legacy fallback path).
            "summary": summary,
            # PLAN-0049 additive structured fields. ``headline`` mirrors summary
            # (the 1-2 sentence top-of-card line); ``sections`` is the parsed
            # narrative — empty list on parse failure (graceful fallback).
            "headline": summary,
            "sections": structured_sections,
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

        # PLAN-0049 T-A-1-04: parse instrument brief into structured sections.
        # Empty list when parse fails — frontend falls back to MarkdownContent.
        instrument_sections = _parse_sections_from_markdown(content)

        return {
            "content": content,
            "risk_summary": None,  # instrument brief has no portfolio — risk_summary is None
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
            # Instrument briefs do not yet emit a top-line summary; leave None.
            "headline": None,
            "sections": instrument_sections,
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


def _fmt_percent(value: Any) -> str:
    """Format a decimal ratio (e.g. 0.2543) as 'XX.X%'.

    EODHD returns margin/growth fields as raw floats in [0, 1] (or negative).
    """
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_fundamentals(ctx: Any) -> str:
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
            lines.append(f"- **{label}**: {_fmt_usd_billions(data[key])}")
    for key, label in percent_fields.items():
        if key in data:
            lines.append(f"- **{label}**: {_fmt_percent(data[key])}")
    for key, label in verbatim_fields.items():
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
