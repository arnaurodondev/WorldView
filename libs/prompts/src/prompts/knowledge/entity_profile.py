"""Provisional entity profile extraction prompt (S7 Worker 13E — PRD §6.7 Block 13E)."""

from __future__ import annotations

from prompts._base import PromptTemplate

ENTITY_PROFILE = PromptTemplate(
    name="entity_profile",
    version="1.0",
    description=(
        "Extracts a canonical entity profile (name, type, ticker, ISIN, aliases) "
        "from a provisional mention for knowledge-graph enrichment."
    ),
    template=(
        "Extract a canonical entity profile for the financial entity described below.\n\n"
        "Entity mention: '{name}'\n"
        "Entity class: {entity_class}\n\n"
        "STRICT RULES:\n"
        "- canonical_name: use the most commonly recognised official name. Do NOT 'correct' the"
        " name to a different entity — if uncertain, return the input name verbatim.\n"
        "- ticker: return the primary exchange ticker ONLY if you are highly confident."
        " If uncertain or if multiple tickers exist, return null.\n"
        "- isin: return the 12-character ISIN ONLY if you can state it with certainty."
        " An incorrect ISIN is worse than null — return null if uncertain.\n"
        "- aliases: include only well-established alternative names (legal name, common"
        " abbreviation, former name). Maximum 5. Exclude speculative variants.\n"
        "- entity_type: use exactly one of: financial_instrument | company | person |"
        " regulator | index | fund | commodity | currency | macro_indicator | other\n\n"
        "Respond with JSON only:\n"
        '{{"canonical_name": "...", "entity_type": "...", "ticker": null, "isin": null,'
        ' "aliases": []}}\n'
        "Use null (not empty string) for unknown fields."
    ),
    parameters=frozenset({"name", "entity_class"}),
)
