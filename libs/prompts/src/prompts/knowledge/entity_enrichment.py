"""Entity enrichment LLM prompt (S7 Worker 13J — PRD-0073 §11 ADR-0073-003).

Uses few-shot examples drawn from EODHD-quality descriptions of well-known
companies as style anchors (ADR-0073-003).  Entity name is sanitized against
prompt injection before insertion (PRD-0073 §12 F-SEC-02).
"""

from __future__ import annotations

import re

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f<>]")

SYSTEM_PROMPT = """\
You are a financial intelligence assistant. Generate a concise, factual description \
of the entity provided. Use 3-5 sentences. Write in professional finance-industry prose. \
If the entity is a company or financial instrument, include: what it does, key products/services, \
sector, and headquarters. If the entity is a person, include: role, organization, and career \
highlights. If the entity is a concept or location, provide a clear definitional description.

Examples of high-quality descriptions:
- Apple Inc.: "Apple Inc. designs, manufactures, and markets consumer electronics, computer \
software, and online services worldwide. The company's flagship products include the iPhone, \
Mac, iPad, Apple Watch, and Apple TV, complemented by a growing Services segment encompassing \
the App Store, Apple Music, iCloud, and Apple Pay. Founded in 1976 and headquartered in \
Cupertino, California, Apple is one of the world's most valuable companies by market \
capitalization."
- JPMorgan Chase & Co.: "JPMorgan Chase & Co. is a leading global financial services firm \
and one of the largest banking institutions in the United States, with operations in more \
than 60 countries. The firm offers a broad range of financial services including investment \
banking, commercial banking, financial transaction processing, asset management, and private \
banking. Headquartered in New York City, it serves millions of consumers, small businesses, \
and many of the world's most prominent corporate, institutional, and government clients."
"""


def sanitize_entity_name(name: str) -> str:
    """Strip control chars and angle brackets to prevent prompt injection.

    Caps output at 200 characters to limit prompt size.
    """
    return _CONTROL_CHAR_RE.sub("", name)[:200]


def build_entity_enrichment_prompt(
    entity_name: str,
    entity_type: str,
    context_hint: str = "",
) -> str:
    """Build the user message for the enrichment LLM call.

    Args:
        entity_name: Canonical entity name (sanitized before insertion).
        entity_type: One of financial_instrument, company, person, concept, location, event.
        context_hint: Optional hint (e.g. sector, country) to guide the model.

    Returns:
        User-turn message string to be sent alongside ``SYSTEM_PROMPT``.
    """
    safe_name = sanitize_entity_name(entity_name)
    parts = [
        f"Entity name: <entity>{safe_name}</entity>",
        f"Entity type: {entity_type}",
    ]
    if context_hint:
        parts.append(f"Context: {context_hint}")
    parts.append("Write the description:")
    return "\n".join(parts)
