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
        news_count = len((ctx.news_articles or [])[:8]) if ctx else 0
        events_count = len((ctx.recent_events or [])[:6]) if ctx else 0
        news_text = _formatter.format_news(ctx, citation_offset=0)
        events_text = _formatter.format_events(ctx, citation_offset=news_count)
        alerts_text = _formatter.format_alerts(ctx, citation_offset=news_count + events_count)
        market_text = _formatter.format_market_overview(ctx)

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
        content = _parser.strip_reasoning("".join(chunks))

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
        summary, narrative = _parser.split_summary_and_details(content)

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
            "lead": lead,
            "confidence": confidence,
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
        entity_text = _formatter.format_entity_context(ctx)
        fundamentals_text = _formatter.format_fundamentals(ctx)
        # WHY citation offsets: instrument brief uses news + events only (no alerts).
        # news = [c1..cN], events = [c(N+1)..].
        news_count_inst = len((ctx.news_articles or [])[:8]) if ctx else 0
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
