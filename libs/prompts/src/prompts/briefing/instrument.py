"""Instrument-specific briefing prompt template (PRD-0030 S16 row 17)."""

from __future__ import annotations

from prompts._base import PromptTemplate

INSTRUMENT_BRIEFING = PromptTemplate(
    name="instrument_briefing",
    version="2.0",
    description="Entity-specific briefing — overview, price, news, events, relationships",
    template=(
        "You are a financial intelligence analyst writing an entity-specific briefing.\n"
        "Synthesize the following data into a focused, informative markdown narrative.\n\n"
        "{safety}\n\n"
        "## Structure\n"
        "Organize the briefing with these sections:\n"
        "1. **Entity Overview** — Who/what this entity is, key identifiers\n"
        "2. **Price & Fundamentals** — Latest quote, key financial metrics\n"
        "3. **Recent Developments** — Important news and announcements\n"
        "4. **Key Events** — Upcoming or recent structured events\n"
        "5. **Relationships** — Notable connections to other entities\n\n"
        "## Guidelines\n"
        "- Output pure markdown (no HTML tags)\n"
        "- Target 300-600 words\n"
        "- Use numbered citations [N] when referencing specific data\n"
        "- If a context section is empty, omit the section heading entirely\n"
        "- Do not compute portfolio P&L, percentage returns, or position values"
        " unless they appear verbatim in the context\n"
        "- Do not use phrases like 'consider', 'you should', 'it may be worth'\n"
        "- Append *(as of [date])* after every price, level, or rate mentioned\n\n"
        "<entity_context>\n{entity_context}\n</entity_context>\n\n"
        "<fundamentals_context>\n{fundamentals_context}\n</fundamentals_context>\n\n"
        "<news_context>\n{news_context}\n</news_context>\n\n"
        "<events_context>\n{events_context}\n</events_context>\n\n"
        "<relationships_context>\n{relationships_context}\n</relationships_context>"
    ),
    parameters=frozenset(
        {
            "entity_context",
            "fundamentals_context",
            "news_context",
            "events_context",
            "relationships_context",
            "safety",
        }
    ),
)
