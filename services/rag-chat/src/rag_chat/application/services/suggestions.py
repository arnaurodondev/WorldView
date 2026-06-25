"""Server-side follow-up suggestion derivation — `suggestions` SSE event.

After the final answer streams, the orchestrator emits a ``suggestions``
SSE event with 3 follow-up questions. The frontend currently client-templates
these from the answer text; when the server event is present the frontend
prefers it (forward-compatible contract).

WHY no LLM call: an extra completion per message would add latency + cost on
EVERY turn for a nicety. The suggestions here are derived deterministically
from what the turn already computed — the resolved entities and the tools
that actually produced data — which is enough signal to template relevant,
clickable follow-ups. If richer LLM-generated suggestions are ever wanted,
gate them behind a new config flag and keep this as the fallback.

Cost: zero extra upstream calls; pure string templating (<1µs per turn).
Toggle: ``RAG_CHAT_SUGGESTIONS_ENABLED`` (default true) — read per-call in
the orchestrator so it can be flipped without a restart (same pattern as
``RAG_COMPLETION_CACHE_DISABLED``).
"""

from __future__ import annotations

from typing import Any

# Tool-name buckets used to pick which templates are still "fresh" (i.e. the
# user has NOT already seen that data in this turn). If the turn already
# called a price tool we don't suggest "How has X performed?" — we suggest
# something orthogonal instead.
_PRICE_TOOLS = frozenset({"get_price_history", "get_market_movers", "compare_entities"})
_NEWS_TOOLS = frozenset({"get_entity_news", "search_documents", "get_morning_brief"})
_FUNDAMENTALS_TOOLS = frozenset({"get_fundamentals_history", "get_fundamentals_history_batch", "screen_universe"})
_RELATION_TOOLS = frozenset(
    {
        "get_entity_graph",
        "traverse_graph",
        "search_entity_relations",
        "get_entity_paths",
        "get_entity_intelligence",
        "get_entity_narrative",
    }
)


def derive_followup_suggestions(
    entities: list[Any],
    tool_names: list[str],
    intent: str | None = None,
) -> list[str]:
    """Derive exactly 3 follow-up questions from this turn's context.

    Args:
        entities:   resolved entities for the turn (duck-typed — needs
                    ``canonical_name`` and optionally ``ticker``).
        tool_names: names of the tools that executed this turn (used to avoid
                    suggesting data the user just saw).
        intent:     QueryIntent value string (currently unused beyond
                    portfolio detection; kept in the signature so future
                    intent-specific templates don't need a call-site change).

    Returns:
        Exactly 3 suggestion strings. Falls back to generic market questions
        when no entity was resolved.
    """
    used = set(tool_names)
    suggestions: list[str] = []

    primary = entities[0] if entities else None
    if primary is not None:
        name = str(getattr(primary, "canonical_name", "") or "").strip()
        ticker = str(getattr(primary, "ticker", "") or "").strip()
        display = name or ticker
        if display:
            # Orthogonal-first ordering: prefer follow-ups about data the
            # turn did NOT already surface.
            candidates: list[tuple[bool, str]] = [
                # (already_seen, template)
                (bool(used & _NEWS_TOOLS), f"What's the latest news on {display}?"),
                (
                    bool(used & _PRICE_TOOLS),
                    f"How has {ticker or display} performed recently?",
                ),
                (bool(used & _FUNDAMENTALS_TOOLS), f"How do {display}'s fundamentals look?"),
                (bool(used & _RELATION_TOOLS), f"Who are {display}'s main competitors and partners?"),
                (False, f"What are the biggest risks for {display} right now?"),
            ]
            # Unseen-data templates first, then the rest, preserving order.
            ordered = [t for seen, t in candidates if not seen] + [t for seen, t in candidates if seen]
            suggestions.extend(ordered)

        # When the turn resolved 2+ entities, a comparison is usually the
        # most natural follow-up — insert it right after the top suggestion.
        if len(entities) >= 2:
            second = entities[1]
            d2 = str(getattr(second, "canonical_name", "") or getattr(second, "ticker", "") or "").strip()
            if display and d2:
                suggestions.insert(1, f"Compare {display} and {d2} side by side.")

    if (intent or "").upper() == "PORTFOLIO" or "get_portfolio_context" in used:
        suggestions.insert(0, "Which of my holdings carry the most risk right now?")

    # Generic fallbacks pad the list to 3 when entity-derived templates are
    # insufficient (e.g. zero resolved entities on a macro question).
    generic = [
        "What are today's biggest market movers?",
        "What's in my morning brief today?",
        "Are there any notable earnings coming up this week?",
    ]
    for g in generic:
        if len(suggestions) >= 3:
            break
        if g not in suggestions:
            suggestions.append(g)

    return suggestions[:3]


__all__ = ["derive_followup_suggestions"]
