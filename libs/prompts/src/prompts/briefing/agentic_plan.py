"""Agentic morning-brief planning prompt (PLAN-0099 Wave C scaffold).

Migrated from the inline ``_PLAN_PROMPT`` constant on
``rag_chat.application.use_cases.agentic_brief_generator.AgenticBriefGenerator``
on 2026-06-05 (Phase 2B prompt consolidation).

This is intentionally a *minimal* planning prompt — it does NOT (yet) match the
full ``MORNING_BRIEFING`` prompt used by the standard generator. The PLAN-0099
Wave A+B agent owns the production prompt engineering; this scaffold prompt
only proves the wiring (planning → tool call → injection → assembly loop).

Version: 0.1 — pre-1.0, indicates the prompt is provisional. Bump to 1.0 once
A/B tells us the agentic loop pays for itself and Wave A+B authors a real
multi-section planning rubric.
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# WHY a short planning prompt:
# A longer, opinionated prompt would diverge from the eventually-shipped
# Wave A+B prompt. Keep it generic until A/B tells us the agentic loop
# actually pays for itself.
AGENTIC_BRIEF_PLAN = PromptTemplate(
    name="agentic_brief_plan",
    # 0.1 == experimental scaffold. The ``_base`` semver regex accepts
    # ``MAJOR.MINOR`` with MAJOR == 0.
    version="0.1",
    description=(
        "Planning system prompt for the experimental agentic morning-brief loop. "
        "Instructs the LLM to use brief-relevant tools then write a multi-paragraph "
        "narrative with [c1], [c2], ... citations."
    ),
    template=(
        "You are an institutional research analyst preparing a morning brief "
        "for a user's portfolio. Use the available tools to gather portfolio "
        "news, top movers, and macro events relevant to today's session. "
        "After you have enough context, write a concise multi-paragraph brief "
        "with a clear lead and key takeaways. Cite sources using [c1], [c2], ..."
    ),
    # No render-time parameters — the user/system prompt boundary is at the
    # LLM message stack, not template interpolation. The agentic loop puts
    # this content into the ``role="system"`` turn and the per-request
    # context (user_id / tenant_id) into the first ``role="user"`` turn.
    parameters=frozenset(),
)

__all__ = ["AGENTIC_BRIEF_PLAN"]
