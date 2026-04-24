"""Alias generation prompt (S7 Consumer 13D-4 — PRD §6.7 Block 13D-4)."""

from __future__ import annotations

from prompts._base import PromptTemplate

ALIAS_GENERATION = PromptTemplate(
    name="alias_generation",
    version="1.0",
    description=("Generates up to 5 common alternative names or aliases for an instrument entity."),
    template=(
        "Generate up to 5 common alternative names or aliases for '{name}' "
        "(ticker: {ticker}).\n\n"
        "STRICT RULES:\n"
        "- Include only well-established alternative names: legal name, common abbreviation,"
        " former name, or widely-used short form.\n"
        "- Do NOT include names of different entities that merely share a word"
        " (e.g. do not include 'Apple Records' as an alias for Apple Inc.).\n"
        "- Return fewer aliases rather than uncertain ones — precision over recall.\n"
        "- Exclude speculative, colloquial, or unofficial variants.\n"
        "- Maximum 5 aliases; return an empty list if no well-established aliases exist.\n\n"
        'Return JSON: {{"aliases": ["..."]}}'
    ),
    parameters=frozenset({"name", "ticker"}),
)
