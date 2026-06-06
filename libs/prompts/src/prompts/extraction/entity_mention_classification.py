"""Entity-mention classification prompts (S6 NLP-pipeline — PLAN-0072 T-72-1-05).

Migrated from ``services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/
unresolved_resolution_worker.py`` (Phase 2C, 2026-06-05).

The legacy worker carried two distinct strings:
  * a static instruction block (sent as the system role for DeepInfra and
    prefixed to the prompt for Ollama), and
  * a dynamic "SURFACE/CONTEXT" user-turn template.

We migrate both as separate ``PromptTemplate`` instances so callers can pick
the right role wiring for their provider without re-fragmenting the prompt
later. Versioning is held at ``1.0`` to match the prompt's existing
production lineage (PLAN-0072 hardening — replaced the "would have its own
Wikipedia article" prompt with this finance-domain block).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# ---------------------------------------------------------------------------
# System role: static instruction block. Identical wording to the legacy
# ``_CLASSIFICATION_SYSTEM_PROMPT`` constant in the worker.
#
# All literal "{" and "}" in the JSON examples are doubled to "{{"/"}}" so the
# template renders cleanly via ``str.format_map`` even though no parameters
# are required.  Without doubling, ``render()`` raises KeyError on the JSON
# braces in the worked examples.
# ---------------------------------------------------------------------------
ENTITY_MENTION_CLASSIFIER_SYSTEM = PromptTemplate(
    name="entity_mention_classifier_system",
    version="1.0",
    description=(
        "Static instruction block telling an LLM to classify a financial-news "
        "entity mention as ENTITY (is_entity=true) or NOISE (is_entity=false). "
        "Replaces the legacy 'would have its own Wikipedia article' prompt "
        "(PLAN-0072 hardening) — recall on subsidiaries / ETFs / regulators "
        "was ~40% under the old prompt. Includes five worked examples covering "
        "the audit-flagged failure modes (pronouns, generic roles, jargon, "
        "calendar fragments, media-outlet attribution)."
    ),
    template=(
        "You are classifying a candidate entity mention extracted from a "
        "financial-news or filing pipeline. Decide whether the SURFACE refers "
        "to a real, named entity worth tracking in a market-intelligence "
        "knowledge graph.\n"
        "\n"
        "Treat as ENTITY (is_entity=true) any of:\n"
        "  - public or private company, subsidiary, or business unit\n"
        "  - investable fund, ETF, mutual fund, index, or other named "
        "investable vehicle\n"
        "  - regulator, central bank, government body, ministry, or "
        "supra-national institution (IMF, ECB, BIS, etc.)\n"
        "  - named person (executive, regulator, politician, analyst)\n"
        "  - named financial product (specific bond series, named index, "
        "named option product, etc.)\n"
        "\n"
        "Treat as NOISE (is_entity=false) any of:\n"
        '  - pronouns and generic anaphora ("he", "she", "they", "it", "we", '
        '"the company", "the firm")\n'
        "  - generic roles or groups without a specific referent "
        '("analysts", "management", "investors", "executives", "regulators", '
        '"shareholders")\n'
        "  - financial jargon that names a concept, not a trackable entity "
        '("constant currency", "organic growth", "market share", "guidance")\n'
        "  - media-outlet names when used as attribution rather than as the "
        'subject of a relation ("Bloomberg", "Reuters", "Seeking Alpha", '
        '"The Motley Fool", "CNBC", "MarketWatch")\n'
        "  - pure number, date, or ticker fragments without context "
        '("Q3", "10-K", "FY24")\n'
        '  - common-noun event words ("merger", "earnings", "IPO")\n'
        "  - misparsed sentence fragments or partial phrases\n"
        "\n"
        "Worked examples:\n"
        '  - surface="iShares Core S&P 500 ETF", '
        'context="The iShares Core S&P 500 ETF (IVV) saw inflows of $1.2B." '
        '→ {{"is_entity": true, "confidence": 0.98, "reason": "named investable fund"}}\n'
        '  - surface="MAS", '
        'context="Singapore\'s MAS raised the benchmark rate by 25bps." '
        '→ {{"is_entity": true, "confidence": 0.95, "reason": "Monetary Authority of Singapore — regulator"}}\n'
        '  - surface="analysts", '
        'context="Analysts said the company would miss guidance." '
        '→ {{"is_entity": false, "confidence": 0.98, "reason": "generic role, not a named entity"}}\n'
        '  - surface="constant currency", '
        'context="Revenue grew 8% on a constant currency basis." '
        '→ {{"is_entity": false, "confidence": 0.97, "reason": "financial jargon, not a trackable entity"}}\n'
        '  - surface="Q3", '
        'context="Q3 revenue rose 8% year-over-year." '
        '→ {{"is_entity": false, "confidence": 0.99, "reason": "calendar fragment, not a named entity"}}\n'
        "\n"
        "Respond with a single JSON object ONLY (no prose, no code fences). "
        'Schema: {{"is_entity": <true|false>, "confidence": <0.0-1.0>, "reason": "<short rationale>"}}'
    ),
    # System block has zero dynamic substitutions.
    parameters=frozenset(),
)


# ---------------------------------------------------------------------------
# User role: dynamic per-mention turn. Migrated verbatim from the worker's
# ``_CLASSIFICATION_PROMPT_TEMPLATE`` constant. The worker still wraps
# ``surface`` and ``context`` with ``json.dumps`` BEFORE rendering so any
# quotes/control chars inside user-supplied text stay safely escaped — see
# F-SEC-006 / F-SEC-205. That preprocessing remains in the worker; this
# template only enforces the SURFACE/CONTEXT shape.
# ---------------------------------------------------------------------------
ENTITY_MENTION_CLASSIFIER_USER = PromptTemplate(
    name="entity_mention_classifier_user",
    version="1.0",
    description=(
        "Dynamic per-mention user turn for the entity-mention classifier. "
        "Caller MUST pre-escape ``surface`` and ``context`` with ``json.dumps`` "
        "(including the surrounding double-quotes) BEFORE rendering — see "
        "F-SEC-006 / F-SEC-205 (prevents prompt injection via double-quotes / "
        "backslashes in news article text). The rendered values are inlined "
        "verbatim with no extra quoting by this template."
    ),
    template="SURFACE: {surface}\nCONTEXT: {context}",
    parameters=frozenset({"surface", "context"}),
)
