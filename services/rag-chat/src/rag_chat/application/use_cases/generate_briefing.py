"""GenerateBriefingUseCase — internal briefing endpoint logic (T-B-2-04, PRD-0016 §6.2).

Called by S10 email scheduler to generate a portfolio risk narrative for digest emails.
Also provides execute_public_morning() and execute_public_instrument() for the frontend
briefing API routes (public_briefings.py).

Auth:       Enforced by InternalJWTMiddleware (PRD-0025) at the API layer — no
            additional token check is required here.
Rate limit: 100 requests/day per user_id (Valkey counter with midnight-aligned key).
LLM:        EMAIL_DEEP_BRIEF_PROMPT via LLMProviderChain (collects full stream).

PLAN-0089 C-3: parsing logic extracted to BriefParser; context-formatting logic
extracted to BriefContextFormatter. This file is now a ≤700-line orchestrator.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.application.pipeline.prompts.intent_prompts import EMAIL_DEEP_BRIEF_PROMPT
from rag_chat.application.ports.brief_archive import BriefArchivePort, NullBriefArchive, UserBriefRecord
from rag_chat.application.use_cases.brief_context_formatter import BriefContextFormatter
from rag_chat.application.use_cases.brief_parser import BriefParser
from rag_chat.domain.errors import RateLimitExceededError

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DAILY_RATE_LIMIT = 100
_BRIEFING_RL_PREFIX = "rag:v1:briefing:rl"
_BRIEFING_RL_TTL = 90_000  # 25 hours — covers DST edge cases

# AI-brief-flag fix (2026-06-19): entity (instrument) briefs are NOT user-scoped
# — the same brief is valid for everyone viewing the same instrument, and the
# screener ``has_ai_brief`` flag is a per-instrument coverage indicator. The
# ``user_briefs`` table requires NOT NULL ``user_id``/``tenant_id`` though, so
# we attribute system-generated entity briefs to a fixed all-zero "system"
# owner. The flag query ignores user/tenant (it matches only ``brief_type`` +
# ``entity_id``), so this attribution does not affect coverage detection.
_SYSTEM_OWNER_ID = UUID("00000000-0000-0000-0000-000000000000")

# How long an entity brief stays "fresh" before the on-demand/pre-gen paths will
# regenerate it. 24h matches the Valkey instrument-brief cache TTL so the DB row
# and the cache age out together.
_ENTITY_BRIEF_FRESHNESS_HOURS = 24

# Module-level singletons — stateless helpers shared across all instances.
# WHY module-level: no per-request state, no DI needed; avoids repeated allocation.
_parser = BriefParser()
_formatter = BriefContextFormatter()


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
        context_gatherer: BriefingContextGatherer | None = None,  # optional — degrades gracefully
        brief_archive: BriefArchivePort | None = None,  # PLAN-0066 Wave B — optional persistence
    ) -> None:
        self._llm_chain = llm_chain
        self._valkey = valkey
        self._context_gatherer = context_gatherer  # None when wired without context gathering
        # WHY NullBriefArchive default: callers that do not wire a real archive
        # (e.g. unit tests, email briefing path) continue to work without any
        # code change. Production wires BriefArchiveRepository via DI.
        self._brief_archive: BriefArchivePort = brief_archive if brief_archive is not None else NullBriefArchive()

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
        portfolio_text = _formatter.format_portfolio_morning(ctx)
        # WHY compute citation offsets here: news is [c1..cN], events are [c(N+1)..],
        # alerts are [c(N+events+1)..]. Offsets must match materialize_brief_citations
        # ordering so [cN] markers in the LLM output resolve to the correct documents.
        # PLAN-0099 Wave B: use the env-overridable limits from the formatter so
        # offsets stay in lock-step with what format_news / format_events emit.
        from rag_chat.application.use_cases.brief_context_formatter import (
            get_events_limit,
            get_min_context_score,
            get_news_limit,
        )

        news_cap = get_news_limit()
        events_cap = get_events_limit()
        news_count = len((ctx.news_articles or [])[:news_cap]) if ctx else 0
        events_count = len((ctx.recent_events or [])[:events_cap]) if ctx else 0
        news_text = _formatter.format_news(ctx, citation_offset=0)
        events_text = _formatter.format_events(ctx, citation_offset=news_count)
        alerts_text = _formatter.format_alerts(ctx, citation_offset=news_count + events_count)
        market_text = _formatter.format_market_overview(ctx)
        # PLAN-0102 W3 follow-up (T-W3-FU-02): prepend the real broad-market
        # tape (when available) and append upcoming earnings under a
        # "Macro Today" subsection. Both formatters return either useful
        # content or graceful placeholder/empty strings so we can safely
        # concatenate without checking for None.
        tape_text = _formatter.format_market_tape(ctx)
        earnings_text = _formatter.format_earnings_calendar(ctx)
        market_text = "\n".join(seg for seg in (tape_text, market_text, earnings_text) if seg)

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
                "risk_summary": _formatter.build_morning_risk_summary(ctx),
                "entity_mentions": [],
                "citations": [],
                "generated_at": generated_at,
                # PLAN-0099 Wave B: all-empty is the strongest form of partial
                # failure; mark it so the UI / cache can distinguish from a
                # real "no signals today" brief.
                "partial_failure": True,
                "context_availability_score": (
                    float(getattr(ctx, "context_availability_score", 0.0)) if ctx is not None else 0.0
                ),
            }

        # ── 3c. PLAN-0099 Wave B: refusal-on-low-context ─────────────────────
        # When the gatherer's weighted availability score (computed across
        # portfolio + news + events + alerts + sections_populated) falls
        # below the configured threshold, skip the LLM call entirely.  The
        # LLM produces noisy "generic" output on sparse context so we'd
        # rather show a "limited data" lead built from whatever sections
        # did populate.  Counter `brief_low_context_refusal_total` tracks
        # how often this fires so operators can tune the threshold.
        score = float(getattr(ctx, "context_availability_score", 1.0)) if ctx is not None else 0.0
        min_score = get_min_context_score()
        if min_score > 0.0 and score < min_score:
            from rag_chat.application.metrics import prometheus as _m

            _m.brief_low_context_refusal_total.inc()
            log.warning(  # type: ignore[no-any-return]
                "brief_low_context_refusal",
                user_id=user_id,
                score=score,
                threshold=min_score,
            )
            populated_bits = [
                seg
                for seg in (
                    ("Portfolio", portfolio_text),
                    ("News", news_text),
                    ("Events", events_text),
                    ("Alerts", alerts_text),
                    ("Market", market_text),
                )
                if seg[1]
            ]
            limited_data_message = (
                "Limited data available today — only " + ", ".join(name for name, _ in populated_bits) + " populated."
                if populated_bits
                else "Limited data available today — no upstream sections populated."
            )
            generated_at = datetime.now(tz=UTC).isoformat()
            return {
                "content": limited_data_message,
                "risk_summary": _formatter.build_morning_risk_summary(ctx),
                "entity_mentions": _formatter.extract_entity_mentions(ctx),
                "citations": _formatter.build_citations(ctx),
                "generated_at": generated_at,
                "partial_failure": True,
                "context_availability_score": score,
            }

        # ── 3d. PLAN-0099 Wave B: partial-failure guard for high-weight sources ─
        # If portfolio OR news (the two highest-weight sources) is empty we
        # still generate the brief but flag it as partial so the UI/cache
        # can show a small notice on the lead.
        partial_failure = (not portfolio_text) or (not news_text)
        partial_failure_notice = ""
        if partial_failure:
            missing: list[str] = []
            if not portfolio_text:
                missing.append("portfolio")
            if not news_text:
                missing.append("news")
            partial_failure_notice = (
                f" (Partial data — {', '.join(missing)} unavailable; " "showing brief based on remaining sources.)"
            )
            log.warning(  # type: ignore[no-any-return]
                "brief_partial_failure",
                user_id=user_id,
                missing=missing,
                score=score,
            )

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
        content = _parser.strip_reasoning("".join(chunks))

        # ── 4a. PLAN-0103 W3: extract v4.2 ``## Summary`` paragraph ───────────
        # The dashboard collapsed view renders this 1-3 sentence paragraph
        # (≤300 chars) before the user clicks "Read more". Legacy briefs lack
        # the heading; the parser returns (None, content) → frontend falls back
        # to the existing summary/narrative head behaviour (R11 forward-compat).
        # WHY split BEFORE the citation-aware parse: parse_sections_with_citations
        # walks the entire content looking for the legacy ``---`` divider and
        # would happily consume the Summary paragraph as part of a v3.0 LEAD
        # block — yielding a confusing duplicate lead/summary pair. Stripping
        # the Summary heading first leaves a clean Details block for the
        # downstream section parser.
        summary_paragraph, post_summary_content = _parser.split_summary_paragraph(content)

        # ── 4a-bis. PLAN-0103 W3: section completeness observability ─────────
        # FQA-01: the LLM intermittently dropped Risks + Opportunities and
        # Bonus context. Emit a structured warning + Prom counter when any of
        # the 6 v4.2 sections are missing — never fail the request (the brief
        # is still useful with N<6 sections; operators tune the threshold).
        missing_sections = _parser.check_section_completeness(content)
        if missing_sections:
            from rag_chat.application.metrics import prometheus as _prom

            for _name in missing_sections:
                _prom.brief_section_missing_total.labels(section=_name).inc()
            log.warning(  # type: ignore[no-any-return]
                "brief_section_missing",
                user_id=user_id,
                missing=missing_sections,
                summary_present=summary_paragraph is not None,
            )

        # ── 4b. PLAN-0062-W4: citation-aware parse pipeline ───────────────────
        # Build the citation index (ordered list matching [c1], [c2], … in prompt).
        context_citations = _parser.materialize_brief_citations(ctx)

        # Parse the v3.0 two-block output (LEAD + DETAILS) with [cN] resolution.
        # Falls back to (None, [], []) for legacy single-block output (no --- divider).
        lead, lead_citations, sections = _parser.parse_sections_with_citations(content, context_citations)

        # Backfill: drop sections with 0 cited bullets (can't guarantee citation coverage).
        sections = _parser.backfill_uncited_bullets(sections, context_citations)

        # ── 4c. Legacy two-tier fallback (PLAN-0048 Wave A back-compat) ───────
        # When v3.0 parse fails (old cached LLM output), try the v2.2 SUMMARY/DETAILS
        # split so the summary field still populates for existing cached briefs.
        # WHY both: during rollout, cached responses may still use the v2.2 format.
        # WHY pass ``content`` (not ``post_summary_content``): the v2.2 split
        # path is a back-compat surface for OLDER caches — those caches predate
        # v4.2 and never carried a ``## Summary`` heading, so the v2.2 splitter
        # sees the same content as before.
        summary, narrative = _parser.split_summary_and_details(content)
        # WHY: when the v4.2 ``## Summary`` heading IS present AND the legacy
        # v2.2 splitter did NOT also produce a summary (i.e. this really is a
        # v4.2-shaped response, not a v2.2 ``## SUMMARY`` + ``---`` + ``## DETAILS``
        # output that the case-insensitive v4.2 splitter happens to also match),
        # we replace the narrative with the post-Summary remainder so the
        # expanded view doesn't repeat the summary paragraph above its body.
        # WHY the ``summary is None`` guard: if the v2.2 path already cleanly
        # split into (summary, narrative-with-DETAILS-header-stripped), use that
        # — it already does the header cleanup. Overwriting with
        # post_summary_content would re-introduce the ``## DETAILS`` header
        # (BP-624 regression caught by test_morning_v22_two_tier_split).
        if summary_paragraph is not None and post_summary_content and summary is None:
            narrative = post_summary_content

        # Brief-quality eval BUG 5: the displayed narrative keeps singular [cN]
        # markers (the frontend resolves them into chips) but MUST NOT carry an
        # unresolvable range marker like [c13-c20] — the frontend resolver only
        # matches a single [cN], so a range would leak as a dangling token. Strip
        # range markers from the final narrative (the structured-section path
        # strips them too, but the v4.x morning brief has no ``---`` divider so it
        # renders this raw narrative directly). Applied AFTER the post-Summary
        # overwrite above so the chosen narrative variant is always cleaned.
        from rag_chat.application.use_cases.brief_parser import _CN_RANGE_MARKER_RE

        narrative = _CN_RANGE_MARKER_RE.sub("", narrative)

        # ── 4d. PLAN-0103 W6 (v4.3): defensive section + summary injection ────
        # The v4.3 prompt teaches the desired shape via few-shot examples but
        # we cannot RELY on the LLM emitting all 6 sections + ``## Summary``
        # on every call. This belt-and-braces step guarantees the structural
        # contract regardless of LLM compliance:
        #   - For each missing section, append a placeholder line so the
        #     dashboard always renders all 6 buckets.
        #   - When the LLM omits ``## Summary``, synthesise a short lead
        #     from the first portfolio/news bullet (NO fabrication — we
        #     quote a bullet that already exists).
        # Both paths bump per-section Prom counters + emit a structured
        # ``brief_defensive_injection`` log so operators can see how often
        # the LLM is degrading and how the parser is compensating.
        if missing_sections:
            from rag_chat.application.metrics import prometheus as _prom

            narrative = _parser.inject_missing_sections(narrative, missing_sections)
            for _name in missing_sections:
                _prom.brief_section_injected_total.labels(section=_name).inc()

        # Synthesise summary_paragraph from a parsed bullet when LLM omitted it.
        # WHY use `sections` (post-backfill): they already carry only cited
        # bullets, so the synthesised lead is grounded in a real source.
        # WHY snapshot ``had_llm_summary``: ``inject_missing_summary`` returns
        # the existing summary unchanged when present, so we can't infer
        # "did we inject?" from the post-call value alone — we must compare
        # against the pre-call value.
        had_llm_summary = summary_paragraph is not None
        narrative, summary_paragraph = _parser.inject_missing_summary(narrative, sections, summary_paragraph)
        summary_injected = (not had_llm_summary) and (summary_paragraph is not None)
        if summary_injected:
            from rag_chat.application.metrics import prometheus as _prom

            _prom.brief_section_injected_total.labels(section="__summary__").inc()

        if missing_sections or summary_injected:
            log.warning(  # type: ignore[no-any-return]
                "brief_defensive_injection",
                user_id=user_id,
                injected_sections=missing_sections,
                summary_injected=summary_injected,
            )

        # ── 5. Derive risk_summary from portfolio holdings (HHI concentration) ─
        risk_summary = _formatter.build_morning_risk_summary(ctx)

        # ── 6. Build citations and entity mentions from gathered context ───────
        citations = _formatter.build_citations(ctx)
        entity_mentions = _formatter.extract_entity_mentions(ctx)

        # ── 7. Compute confidence score ────────────────────────────────────────
        confidence = _parser.compute_confidence(sections, lead, lead_citations)

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "morning_briefing_generated",
            user_id=user_id,
            chars=len(narrative),
            has_lead=lead is not None,
            sections_count=len(sections),
            confidence=confidence,
        )

        # D-R4-003 (PLAN-0087, 2026-05-09): legacy_sections returned
        # list[dict] with string bullets (typed `bullets: list[str]`), which
        # violates the BriefSection / BriefBullet contract.  Caching this
        # legacy shape into `briefs.sections_json` then deserialising it on a
        # cache hit caused MorningBriefCard / InstrumentAISubheader to read
        # `bullet.text` → undefined → empty <li> with raw `[c0][c1]` markers.
        # Drop the legacy fallback: when v3.0 parsing fails, sections=[] and
        # the frontend falls back to MarkdownContent over the narrative —
        # already the documented degraded UX path.  Preserves the variable
        # name `legacy_sections` to keep downstream cast/persistence code
        # working unchanged.
        legacy_sections: list[dict[str, Any]] = []

        # ── 8. PLAN-0066 Wave B: fire-and-forget brief persistence ───────────
        # WHY asyncio.shield: DB failures must NEVER propagate back to the caller
        # (this is a cache/analytics write, not the primary response path). The
        # shield ensures that even if the event loop cancels the task, the DB
        # write attempt is not interrupted mid-flight.
        # WHY ensure_future (not create_task): ensure_future is available in
        # Python 3.12 without requiring an explicit running loop reference.
        # WHY skip persistence on cached returns: the cache-hit path returns
        # early (before this code), so we only persist genuinely fresh generations.
        try:
            _uid = UUID(user_id)
        except (ValueError, AttributeError):
            _uid = UUID("00000000-0000-0000-0000-000000000000")
        try:
            _tid = UUID(tenant_id)
        except (ValueError, AttributeError):
            _tid = UUID("00000000-0000-0000-0000-000000000000")

        # Build sections_json: coerce BriefSection dataclasses → plain dicts.
        # citations_json: BriefCitation dataclasses → plain dicts using to_dict().
        # WHY cast to Any: sections is list[BriefSection] and legacy_sections is
        # list[dict]; mypy cannot unify the types in the conditional. We explicitly
        # cast to Any and then normalise each entry to dict in the comprehension.
        _raw_sections: Any = sections if sections else legacy_sections
        _sections_json: list[dict] = [
            s.to_dict() if hasattr(s, "to_dict") else (s if isinstance(s, dict) else {}) for s in _raw_sections
        ]
        _citations_json: list[dict] = [
            c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {}) for c in citations
        ]

        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        _record = UserBriefRecord(
            id=new_uuid7(),
            user_id=_uid,
            tenant_id=_tid,
            brief_type="morning",
            entity_id=None,
            generated_at=utc_now(),
            headline=(lead or narrative or "")[:500],  # WHY [:500]: headline col is Text, but keep it concise
            lead=lead,
            sections_json=_sections_json,
            citations_json=_citations_json,
            confidence=confidence,
            source_version="v2",
        )

        _archive = self._brief_archive

        async def _persist_brief(record: UserBriefRecord) -> None:
            """Fire-and-forget DB write — exceptions are logged, never raised."""
            try:
                await _archive.save(record)
            except Exception as exc:
                # WHY warn (not error): persistence failure is non-critical for
                # the user experience. The brief is already generated; the archive
                # is best-effort analytics storage.
                log.warning("brief_persist_failed", error=str(exc))  # type: ignore[no-any-return]

        # asyncio.shield prevents cancellation from interrupting the DB write.
        # WHY store _task reference: RUF006 — storing the future prevents it from
        # being garbage-collected before the event loop runs it (Python GC can
        # collect unreferenced tasks mid-execution on CPython implementations).
        _task = asyncio.ensure_future(asyncio.shield(_persist_brief(_record)))
        # Attach a no-op done callback so the task reference is kept alive until
        # the event loop finalises it — avoids "Task destroyed but it is pending"
        # warnings in tests and concurrent request scenarios.
        _task.add_done_callback(lambda _: None)

        return {
            # ``content`` keeps the field name expected by the route layer (which
            # maps result["content"] → response.narrative). The narrative half of
            # the split goes here so the expanded card view shows the structured
            # ## DETAILS sections without the redundant ## SUMMARY heading.
            "content": narrative,
            # ``summary`` is the v2.2 fallback — None when the LLM didn't emit
            # the v2.2 two-tier format. Preserved for back-compat.
            "summary": summary,
            # PLAN-0062-W4: return v3.0 BriefSection list when available; otherwise
            # use legacy string-bullet sections for backward compatibility.
            "sections": sections if sections else legacy_sections,
            "risk_summary": risk_summary,
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
            # PLAN-0062-W4 new fields
            "lead": (lead + partial_failure_notice) if (lead and partial_failure_notice) else lead,
            "confidence": confidence,
            # PLAN-0099 Wave B: surface partial-failure + context score on the
            # response so the UI / cache / downstream can show a notice.
            "partial_failure": partial_failure,
            "context_availability_score": score,
            # PLAN-0103 W3 (BP-624): collapsed-view summary paragraph (v4.2
            # ``## Summary`` block). None for legacy responses — frontend
            # falls back to ``summary`` / first lines of ``narrative``.
            "summary_paragraph": summary_paragraph,
        }

    async def execute_public_instrument(
        self,
        entity_id: str,
        *,
        persist: bool = True,
        skip_if_fresh: bool = False,
    ) -> dict[str, Any]:
        """Generate an instrument-specific briefing.

        Called by GET /api/v1/briefings/instrument/{entity_id} and by the
        InstrumentBriefPregenerationWorker.

        Uses BriefingContextGatherer to fetch entity graph + fundamentals + news.

        Args:
            entity_id: the KG entity id (route param). The persisted entity-brief
                row is keyed by the RESOLVED market-data instrument_id when the
                ticker resolves (so the screener ``has_ai_brief`` flag matches),
                falling back to ``entity_id`` otherwise.
            persist: when True (default), the generated brief is persisted to
                ``user_briefs`` with ``brief_type='entity'`` so the
                ``GetAiBriefFlagUseCase`` (and therefore the screener
                ``has_ai_brief`` column) reports coverage for this instrument.
                Persistence is best-effort / fire-and-forget — a DB failure
                never affects the returned brief.
            skip_if_fresh: when True, the use case first checks whether a fresh
                (< _ENTITY_BRIEF_FRESHNESS_HOURS) entity brief already exists for
                the resolved id and, if so, returns it WITHOUT paying for an LLM
                call. Used by the pre-gen worker to avoid regenerating the whole
                active set on every interval. The on-demand route leaves this
                False (Valkey already absorbs the freshness window there).

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

        # AI-brief-flag fix (2026-06-19): the persisted row + freshness check key
        # on the RESOLVED market-data instrument_id (what the screener flag uses),
        # falling back to the KG entity_id only when the ticker did not resolve.
        persist_id_str = getattr(ctx, "resolved_instrument_id", None) or entity_id
        try:
            persist_entity_id = UUID(persist_id_str)
        except (ValueError, AttributeError):
            # Malformed id — disable persistence rather than crash; the brief is
            # still returned to the caller.
            persist_entity_id = None

        # ── Freshness skip (pre-gen path only) ───────────────────────────────
        # When asked to skip-if-fresh, avoid the (expensive) LLM call entirely if
        # a recent entity brief already exists for this instrument. The on-demand
        # route never sets this (its Valkey cache already short-circuits there).
        if skip_if_fresh and persist_entity_id is not None:
            existing = await self._brief_archive.get_latest_entity_brief(persist_entity_id, limit=1)
            if existing:
                from common.time import utc_now  # type: ignore[import-untyped]

                latest = existing[0]
                age_seconds = (utc_now() - latest.generated_at).total_seconds()
                if age_seconds < _ENTITY_BRIEF_FRESHNESS_HOURS * 3600:
                    log.info(  # type: ignore[no-any-return]
                        "instrument_brief_skipped_fresh",
                        entity_id=entity_id,
                        persist_entity_id=str(persist_entity_id),
                        age_hours=round(age_seconds / 3600, 2),
                    )
                    return {
                        "content": latest.headline,
                        "risk_summary": None,
                        "entity_mentions": [],
                        "citations": latest.citations_json,
                        "generated_at": latest.generated_at.isoformat(),
                        "sections": latest.sections_json,
                        "lead": latest.lead,
                        "confidence": latest.confidence,
                        "skipped_fresh": True,
                    }

        # ── Build prompt sections ─────────────────────────────────────────────
        entity_text = _formatter.format_entity_context(ctx)
        fundamentals_text = _formatter.format_fundamentals(ctx)
        # WHY citation offsets: instrument brief uses news + events only (no alerts).
        # news = [c1..cN], events = [c(N+1)..].
        # Brief-quality eval BUG 1: the events offset MUST equal the number of
        # news citations the LLM actually sees, which is the deduped+capped
        # ``_ordered_news`` list (NOT a raw ``[:8]`` slice). The old ``[:8]``
        # diverged from format_news (deduped+get_news_limit()) whenever dedupe
        # dropped an item or the list exceeded 8 — mis-numbering every event +
        # the trailing KG definition/narrative citations.
        news_count_inst = len(_formatter._ordered_news(ctx)) if ctx else 0
        news_text = _formatter.format_news(ctx, citation_offset=0)
        events_text = _formatter.format_events(ctx, citation_offset=news_count_inst)
        relationships_text = _formatter.format_relationships(ctx)

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
        content = _parser.strip_reasoning("".join(chunks))

        # ── Build citations and entity mentions ───────────────────────────────
        citations = _formatter.build_citations(ctx)
        entity_mentions = _formatter.extract_entity_mentions(ctx)

        # ── PLAN-0062-W4: citation-aware parse pipeline ────────────────────────
        context_citations = _parser.materialize_brief_citations(ctx)
        lead, lead_citations, sections = _parser.parse_sections_with_citations(content, context_citations)
        sections = _parser.backfill_uncited_bullets(sections, context_citations)
        confidence = _parser.compute_confidence(sections, lead, lead_citations)

        # D-R4-003 (PLAN-0087, 2026-05-09): legacy fallback used to invoke
        # _parse_sections_from_markdown which returns list[dict] with string
        # bullets — violating the BriefSection / BriefBullet contract the
        # frontend types declare.  Result: bullet.text was undefined and
        # MorningBriefCard / InstrumentAISubheader rendered raw "[c0][c1]"
        # markers + empty <li>s.  Now: drop the legacy fallback entirely.
        # When v3.0 parse returns no sections, leave sections=[] and let the
        # frontend fall back to MarkdownContent over the raw narrative —
        # already the documented degradation path.  No type: ignore needed.
        # The narrative content is preserved in the response (`content` field),
        # so the user still sees the brief — just without the structured
        # bullet UI affordance.

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "instrument_briefing_generated",
            entity_id=entity_id,
            chars=len(content),
            has_lead=lead is not None,
            sections_count=len(sections),
            confidence=confidence,
        )

        # ── AI-brief-flag fix (2026-06-19): persist as a brief_type='entity' row ─
        # WHY: the screener ``has_ai_brief`` column is materialised from S8's
        # ``GetAiBriefFlagUseCase``, which reports True only when a ``user_briefs``
        # row exists with ``brief_type='entity' AND entity_id=<instrument_id>``.
        # Before this fix NOTHING wrote such a row, so the flag was structurally
        # always false. We now fire the same best-effort persist the morning path
        # uses, but with the entity fields set and the id keyed to the resolved
        # market-data instrument_id (so the flag query matches).
        # WHY fire-and-forget (asyncio.shield + swallow): persistence is a
        # coverage/analytics write, never on the user's critical path. A DB blip
        # must never turn a generated brief into a 503.
        if persist and persist_entity_id is not None:
            from common.ids import new_uuid7  # type: ignore[import-untyped]
            from common.time import utc_now  # type: ignore[import-untyped]

            _sections_json: list[dict] = [
                s.to_dict() if hasattr(s, "to_dict") else (s if isinstance(s, dict) else {}) for s in sections
            ]
            _citations_json: list[dict] = [
                c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {}) for c in citations
            ]
            _record = UserBriefRecord(
                id=new_uuid7(),
                user_id=_SYSTEM_OWNER_ID,
                tenant_id=_SYSTEM_OWNER_ID,
                brief_type="entity",  # ← the previously-missing piece
                entity_id=persist_entity_id,  # ← keyed to the screener's instrument_id
                generated_at=utc_now(),
                headline=(lead or content or "")[:500],
                lead=lead,
                sections_json=_sections_json,
                citations_json=_citations_json,
                confidence=confidence,
                source_version="v2",
            )
            _archive = self._brief_archive

            async def _persist_entity_brief(record: UserBriefRecord) -> None:
                try:
                    await _archive.save(record)
                except Exception as exc:
                    log.warning("entity_brief_persist_failed", error=str(exc))  # type: ignore[no-any-return]

            # RUF006: keep a reference so the GC does not collect the pending task.
            _task = asyncio.ensure_future(asyncio.shield(_persist_entity_brief(_record)))
            _task.add_done_callback(lambda _: None)

        return {
            "content": content,
            "risk_summary": None,  # instrument brief has no portfolio — risk_summary is None
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
            "sections": sections,
            # PLAN-0062-W4 new fields
            "lead": lead,
            "confidence": confidence,
        }


# ── Backward-compatible module-level aliases ─────────────────────────────────
# These private-name aliases preserve existing test and contract imports that
# reference the old module-level helper functions (e.g. test_citation_pipeline,
# test_briefing_sections_parser, test_brief_contract). PLAN-0089 C-3 moved the
# logic into BriefParser / BriefContextFormatter; we re-export via these
# one-liner lambdas / references so callers can keep importing from this module
# without modification.  They delegate 100% to the new classes — no duplication.


def _strip_reasoning(text: str) -> str:
    return _parser.strip_reasoning(text)


def _split_summary_and_details(content: str) -> tuple[str | None, str]:
    return _parser.split_summary_and_details(content)


def _parse_sections_from_markdown(markdown: str) -> list[dict]:
    return _parser.parse_sections_from_markdown(markdown)


def _strip_block_header(block: str, expected: str) -> str:
    return BriefParser._strip_block_header(block, expected)


def _materialize_brief_citations(ctx: Any) -> list:
    return _parser.materialize_brief_citations(ctx)


def _parse_sections_with_citations(
    markdown: str,
    context_citations: list,
) -> tuple:
    return _parser.parse_sections_with_citations(markdown, context_citations)


def _backfill_uncited_bullets(
    sections: list,
    context_citations: list,
) -> list:
    return _parser.backfill_uncited_bullets(sections, context_citations)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    return BriefParser._truncate_at_sentence(text, max_chars)


def _compute_confidence(
    sections: list,
    lead: str | None,
    lead_citations: list,
) -> float:
    return _parser.compute_confidence(sections, lead, lead_citations)
