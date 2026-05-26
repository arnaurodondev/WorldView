"""Intent inference from the first batch of tool calls.

PLAN-0093 Sub-Plan E, Wave E-1, Task T-E-1-02 (audit refs F-RAG-002,
F-RAG-INTENT-001).

Decision: option (b) from the audit — infer the query intent from the
first batch of tool calls the LLM emits, rather than burning a separate
LLM round-trip on a one-shot classifier. The tool the LLM picked is a
strong signal of what the user is asking for, and the inference is a
pure function over the tool name + args, so it runs in microseconds.

The orchestrator calls ``infer_intent(tool_calls)`` immediately after
the first ``chat_with_tools`` turn and uses the returned intent for:

1. The SECOND prompt build (so the per-intent style addendum is applied).
2. Metrics labelling (``rag_queries_total{intent=...}``).
3. The audit log (so we can compute per-intent grounding pass rates).

Rules in priority order:

1. ``compare_entities`` OR ≥ 2 distinct ``entity_id``s in args → ``COMPARISON``
2. ``traverse_graph`` OR ``get_entity_paths`` → ``RELATIONSHIP``
3. ``get_fundamentals_history`` OR ``screen_universe`` → ``FINANCIAL_DATA``
4. ``get_economic_calendar`` OR ``get_temporal_events`` → ``MACRO``
5. ``search_documents`` OR ``search_claims`` → ``FACTUAL_LOOKUP``
6. Default → ``GENERAL``

The order matters: COMPARISON wins over any single-entity intent because
the moment the LLM is comparing two things the answer needs the
per-entity sub-section formatting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from collections.abc import Iterable

# Tool name → intent mapping for the single-call rules (priorities 2-5).
# We keep this as a dict (not if-chains) so adding a new rule is a one-line
# change and the priority sort below stays explicit.
_TOOL_TO_INTENT: dict[str, QueryIntent] = {
    "traverse_graph": QueryIntent.RELATIONSHIP,
    "get_entity_paths": QueryIntent.RELATIONSHIP,
    # PLAN-0095 W3 T-W3-02: bundle-style intelligence tools imply a
    # relationship-aware second turn (peers / partners / career narrative all
    # surface through these). Previously they defaulted to GENERAL and lost
    # the per-intent prompt addendum.
    "get_entity_intelligence": QueryIntent.RELATIONSHIP,
    "search_entity_relations": QueryIntent.RELATIONSHIP,
    "get_entity_narrative": QueryIntent.RELATIONSHIP,
    "get_fundamentals_history": QueryIntent.FINANCIAL_DATA,
    "screen_universe": QueryIntent.FINANCIAL_DATA,
    "get_economic_calendar": QueryIntent.MACRO,
    "get_temporal_events": QueryIntent.MACRO,
    "search_documents": QueryIntent.FACTUAL_LOOKUP,
    "search_claims": QueryIntent.FACTUAL_LOOKUP,
}

# Priority order — first match wins. COMPARISON is checked first via a
# dedicated branch (because it depends on entity_id cardinality, not just
# the tool name) but the others are checked in declaration order here.
_PRIORITY_INTENTS: tuple[QueryIntent, ...] = (
    QueryIntent.RELATIONSHIP,
    QueryIntent.FINANCIAL_DATA,
    QueryIntent.MACRO,
    QueryIntent.FACTUAL_LOOKUP,
)


def _distinct_entity_ids(tool_calls: Iterable[object]) -> set[str]:
    """Collect every distinct ``entity_id`` value across all tool call inputs.

    Tool calls store their args in ``tool.input``. We accept both
    ``entity_id`` (single string) and ``entity_ids`` (list) field names —
    different KG tools use different conventions. Returns lowercased
    strings so case differences across tools don't double-count.
    """
    seen: set[str] = set()
    for call in tool_calls:
        inp = getattr(call, "input", None) or {}
        # Single-id field — most tools use this.
        single = inp.get("entity_id")
        if isinstance(single, str) and single:
            seen.add(single.lower())
        # List-id field — used by compare/multi-entity tools.
        many = inp.get("entity_ids") or inp.get("entities")
        if isinstance(many, list):
            for value in many:
                if isinstance(value, str) and value:
                    seen.add(value.lower())
    return seen


def infer_intent(tool_calls: Iterable[object]) -> QueryIntent:
    """Return the inferred ``QueryIntent`` for the first tool-call batch.

    Empty input → ``QueryIntent.GENERAL`` (the LLM either answered
    directly with no tools, or no signal is available).

    Args:
        tool_calls: Iterable of ``ToolUseBlock``-shaped objects (only
            ``.name`` and ``.input`` attributes are read). We accept any
            duck-typed object so tests can pass plain ``MagicMock``s.
    """
    # Materialise once — we iterate twice (compare check + tool-name pass).
    calls = list(tool_calls)
    if not calls:
        return QueryIntent.GENERAL

    tool_names = {getattr(c, "name", "") for c in calls}

    # ── Priority 1: COMPARISON ────────────────────────────────────────────
    # Explicit comparison tool OR the LLM called multiple tools with
    # different entity_ids (e.g. one get_fundamentals call per company).
    if "compare_entities" in tool_names:
        return QueryIntent.COMPARISON
    if len(_distinct_entity_ids(calls)) >= 2:
        return QueryIntent.COMPARISON

    # ── Priorities 2-5: single-tool mappings ─────────────────────────────
    # We scan in declared priority order so RELATIONSHIP wins over
    # FACTUAL_LOOKUP when the LLM called both a graph tool AND a doc tool.
    for priority_intent in _PRIORITY_INTENTS:
        for name in tool_names:
            if _TOOL_TO_INTENT.get(name) is priority_intent:
                return priority_intent

    # ── Default ──────────────────────────────────────────────────────────
    return QueryIntent.GENERAL


__all__ = ["infer_intent"]
