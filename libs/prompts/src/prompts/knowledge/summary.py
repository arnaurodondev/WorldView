"""Relation summary prompt (S7 Worker 13C — PRD §6.7 Block 13C)."""

from __future__ import annotations

from prompts._base import PromptTemplate

RELATION_SUMMARY = PromptTemplate(
    name="relation_summary",
    version="1.0",
    description=(
        "Generates a concise 2-3 sentence summary from evidence statements about a relationship between two entities."
    ),
    template=(
        "Summarize the following evidence statements about a relationship "
        "between two entities into a concise 2-3 sentence summary. "
        "Focus on key facts and avoid repetition.\n\n"
        "STRICT RULES:\n"
        "- Do not invent or add any claims not present in the evidence statements below.\n"
        "- If the evidence statements are contradictory, write:"
        " 'Evidence is conflicting on [topic].'\n"
        "- Do not use qualitative adjectives ('strong', 'strategic', 'important')"
        " unless they appear verbatim in the evidence.\n\n"
        "{evidence_statements}"
    ),
    parameters=frozenset({"evidence_statements"}),
)
