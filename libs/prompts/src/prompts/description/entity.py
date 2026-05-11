"""Entity description prompt (ml-clients Gemini adapter — PRD-0017 §6.5).

Uses XML-wrapped parameters to prevent prompt injection (PRD-0017 §8).
"""

from __future__ import annotations

from prompts._base import PromptTemplate

ENTITY_DESCRIPTION = PromptTemplate(
    name="entity_description",
    version="1.0",
    description=(
        "Generates a concise 2-3 sentence factual description of a non-company entity "
        "via Gemini. Uses XML-wrapped name, type, and hints for injection safety."
    ),
    template=(
        "Write a concise 2-3 sentence factual description of "
        "<entity_name>{name}</entity_name> "
        "(entity type: <entity_type>{type}</entity_type>). "
        "Additional context: <hints>{hints}</hints>. "
        "Focus on what this entity is, its significance, and its primary domain. "
        "For time-varying attributes (rates, policy, index composition),"
        " describe the entity's role and purpose — not current values. "
        "If you are not confident about a specific fact, omit it —"
        " shorter accurate is better than longer uncertain. "
        "Do not include opinions or speculation. "
        "Respond with only the description text, no JSON, no markdown."
    ),
    parameters=frozenset({"name", "type", "hints"}),
)
