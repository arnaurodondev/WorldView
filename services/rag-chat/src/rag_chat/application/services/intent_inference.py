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

import re
from typing import TYPE_CHECKING

from rag_chat.domain.enums import QueryIntent

if TYPE_CHECKING:
    from collections.abc import Iterable


# F-LIVE-O (PLAN-0093 ITER-9): CONTRADICTION question-text patterns.
#
# The tool-call signal alone is insufficient for "what contradicts X" /
# "bear case against X" questions because the LLM frequently picks general
# search tools (search_documents) and the orchestrator routes the query to
# GENERAL. The question itself carries the strongest signal, so we scan the
# user message text BEFORE the tool-call inference. Compiled once at module
# import for cheap re-execution on every turn.
_CONTRADICTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(contradict|contradicts|contradiction|contradictions|contradicted|contradicting)\b",
        r"\b(disagree|disagrees|disagreement|refute|refutes|disprove|disproves|inconsistent|opposite)\b",
        r"\bcounter[- ]?(argument|arguments|point|points|narrative)\b",
        r"\b(bear|bearish)\s+(case|thesis|argument|view|side)\b",
        r"\b(bull|bullish)\s+(case|thesis|argument|view|side)\s+(against|fail|wrong)\b",
        r"\bwhat\s+(negates|undermines|argues against|speaks against|weakens)\b",
        r"\b(argues|arguing|speaks|speaking|argument)\s+against\b",
        r"\bagainst\s+the\s+(bull|bullish|bear|bearish)\s+(case|thesis|view)\b",
    )
)


def _matches_contradiction(question_text: str | None) -> bool:
    """Return True when ``question_text`` contains an explicit contradiction cue."""
    if not question_text:
        return False
    return any(pat.search(question_text) for pat in _CONTRADICTION_PATTERNS)


# ── What-if / projection FRAMING detector (2026-07-05) ────────────────────────
#
# WHY: the not-financial-advice disclaimer and the ``analytical_intent``
# numeric-grounding relaxation were gated on ``intent in (REASONING,
# CONTRADICTION)``. But the live chat path derives intent from ``infer_intent``,
# which is STRUCTURALLY unable to emit ``REASONING`` (it maps tool calls, and no
# tool implies "reasoning") and whose CONTRADICTION regex never matches
# projection framing. So every what-if / projection question ("assuming X grows
# 25%, how might FY revenue evolve") landed on GENERAL / FINANCIAL_DATA and MISSED
# both the disclaimer and the numeric relaxation. Confirmed live.
#
# The fix re-gates on a DETERMINISTIC framing signal instead of the intent enum:
#   * QUESTION-side — the user asked a hypothetical / projection / scenario
#     question (this module's :func:`question_is_whatif`);
#   * ANSWER-side — the final answer states a HEDGED / projected figure
#     (:func:`answer_has_projected_figure`, which reuses ``numeric_grounding``'s
#     ``_HEDGE_RE`` — the same hedge lexicon the Stage-1 grounding downgrade uses,
#     so the disclaimer and the grounding relaxation agree on what "projected"
#     means).
#
# Both are pure regex functions (no I/O, no LLM) so they run in microseconds on
# every turn and are trivially unit-testable.
#
# Compiled once at import. Each alternation targets a distinct projection cue:
#   1. ``assuming …``                    — explicit assumption framing
#   2. ``if <subject> grows/rises/…``    — conditional forward movement
#   3. ``what if …``                     — canonical hypothetical opener
#   4. ``projected`` / ``projection``    — projection vocabulary
#   5. ``scenario`` / ``hypothetical`` / ``suppose`` — scenario framing
#   6. ``next quarter/year/…``           — forward-looking horizon
#   7. ``how might/could/would …``       — modal projection question
#   8. growth VERB + ``NN%``             — forward-looking growth-rate framing
#   9. ``NN%`` + growth/CAGR/annually    — the same, reversed word order
_WHATIF_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bassuming\b",
        r"\bif\s+\w+(?:\s+\w+){0,2}?\s+"
        r"(?:grow|grows|growing|grew|rise|rises|rising|rose|fall|falls|falling|fell"
        r"|increase|increases|increasing|increased|declin\w+|reach|reaches|reaching"
        r"|reached|drop|drops|dropping|dropped|hit|hits|doubl\w+|halv\w+)\b",
        r"\bwhat\s+if\b",
        r"\bproject(?:ed|ion|ions)\b",
        r"\b(?:scenario|hypothetical|hypothetically|suppose|supposing)\b",
        r"\bnext\s+(?:quarter|year|fiscal|fy|month|decade|few\s+years)\b",
        r"\bhow\s+(?:might|could|would)\b",
        r"\b(?:grow|grows|grew|rise|rises|rose|increase|increases|increased|declin\w+"
        r"|fall|falls|fell|drop|drops)\b[^.?!]{0,40}?\d+(?:\.\d+)?\s?%",
        r"\d+(?:\.\d+)?\s?%[^.?!]{0,40}?\b(?:growth|cagr|annually|per\s+year|per\s+annum|a\s+year)\b",
    )
)

# Cheap "the answer states a number" probe — a projected FIGURE requires an
# actual digit, so a bare hedge word with no number ("this could vary") does not
# spuriously trigger the disclaimer.
_ANSWER_DIGIT_RE = re.compile(r"\d")


def question_is_whatif(question_text: str | None) -> bool:
    """Return True when ``question_text`` is a what-if / projection / scenario question.

    Deterministic regex scan (see :data:`_WHATIF_PATTERNS`). Used in place of the
    ``intent in (REASONING, CONTRADICTION)`` enum check for BOTH the
    not-financial-advice disclaimer and the ``analytical_intent`` numeric-gate
    relaxation — the live agent-era ``infer_intent`` cannot emit those intents for
    projection framing, so the enum check silently missed every what-if.
    """
    if not question_text:
        return False
    return any(pat.search(question_text) for pat in _WHATIF_PATTERNS)


def answer_has_projected_figure(answer_text: str | None) -> bool:
    """Return True when the final answer states a HEDGED / projected numeric figure.

    A projected figure = the answer contains a digit AND a hedge/projection marker
    (``could`` / ``would`` / ``roughly`` / ``~`` / ``assuming`` / ``projected`` /
    ``estimate`` / …). Reuses ``numeric_grounding._HEDGE_RE`` so this answer-side
    signal and the Stage-1 grounding downgrade share one definition of "projected".

    Requiring a digit keeps the disclaimer off answers that merely hedge in prose
    with no figure at all.
    """
    if not answer_text:
        return False
    # Local import avoids a module-load coupling to the (sibling-mutated)
    # numeric_grounding module and dodges any import-order edge cases.
    from rag_chat.application.services.numeric_grounding import _HEDGE_RE

    return bool(_ANSWER_DIGIT_RE.search(answer_text)) and bool(_HEDGE_RE.search(answer_text))


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


def infer_intent(tool_calls: Iterable[object], question_text: str | None = None) -> QueryIntent:
    """Return the inferred ``QueryIntent`` for the first tool-call batch.

    Empty input → ``QueryIntent.GENERAL`` (the LLM either answered
    directly with no tools, or no signal is available).

    Args:
        tool_calls: Iterable of ``ToolUseBlock``-shaped objects (only
            ``.name`` and ``.input`` attributes are read). We accept any
            duck-typed object so tests can pass plain ``MagicMock``s.
        question_text: Optional user message text. When supplied it is
            scanned for explicit CONTRADICTION cues BEFORE tool-call
            inference (F-LIVE-O). Backwards compatible — callers that
            omit it get the original tool-only behaviour.
    """
    # ── Priority 0: explicit CONTRADICTION cue in question text ──────────
    # Checked first because the LLM's tool selection often misses the
    # "what contradicts X" pattern, leaving the intent as GENERAL even
    # though the question is structurally a contradiction probe.
    if _matches_contradiction(question_text):
        return QueryIntent.CONTRADICTION

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


__all__ = ["answer_has_projected_figure", "infer_intent", "question_is_whatif"]
