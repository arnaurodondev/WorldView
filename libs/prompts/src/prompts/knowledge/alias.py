"""Alias generation prompt (S7 Consumer 13D-4 — PRD §6.7 Block 13D-4).

PLAN-0057 Wave C-4 (F-MAJOR-09): bumped to v2.0.

Changes vs v1.0:
- Added ``description`` parameter — gives the LLM enough context to recognise
  the entity (a 1-token name like "AAPL" alone is rarely enough to suggest
  high-precision aliases).
- Added ``aliases_so_far`` parameter — the comma-joined list of mechanical
  aliases (NAME / TICKER / ISIN / CUSIP / FIGI / LEI / PRIMARY_TICKER) that the
  caller has already inserted; the LLM avoids proposing duplicates.
- Four worked examples replace the prior single rule list:
  Apple Inc. (with description) → "Apple Computer", "Apple"
  Meta Platforms (with description) → "Facebook", "Facebook Inc."
  NVIDIA Corporation (no description) → "NVIDIA", "nVidia"
  Foreward Industries (empty description) → [] (precision over recall)
"""

from __future__ import annotations

from prompts._base import PromptTemplate

# The template is split into a header + four labelled examples + the actual
# input section.  Each example uses double-braces ``{{`` / ``}}`` because the
# template engine treats single braces as parameters; the JSON output examples
# need literal braces so we double-escape them.
ALIAS_GENERATION = PromptTemplate(
    name="alias_generation",
    version="2.0",
    description=(
        "Generates up to 5 common alternative names or aliases for an instrument entity, "
        "given the canonical name, ticker, optional description, and the list of "
        "mechanical aliases already on the entity. Returns an empty list when no "
        "well-established alternative names exist (precision over recall)."
    ),
    template=(
        "You are an expert at financial-market entity disambiguation.  "
        "Generate up to 5 common alternative names or aliases for the entity below.\n\n"
        "STRICT RULES:\n"
        "- Include only well-established alternative names: legal name, common abbreviation, "
        "former name, or widely-used short form.\n"
        "- Do NOT include names of different entities that merely share a word "
        "(e.g. do not include 'Apple Records' as an alias for Apple Inc.).\n"
        "- Do NOT repeat any alias already in the 'Existing aliases' list.\n"
        "- Return fewer aliases rather than uncertain ones — precision over recall.\n"
        "- Exclude speculative, colloquial, or unofficial variants.\n"
        "- Maximum 5 aliases; return an empty list if no well-established aliases exist.\n\n"
        "EXAMPLES (showing the expected JSON output for each input):\n\n"
        "Example 1 — well-known company with description, has a former name:\n"
        "  Name: Apple Inc.\n"
        "  Ticker: AAPL\n"
        "  Description: Apple Inc. designs, manufactures, and markets smartphones, "
        "personal computers, tablets, wearables, and accessories worldwide. The company "
        "was founded in 1976 as Apple Computer, Inc.\n"
        "  Existing aliases: Apple Inc., AAPL, US0378331005\n"
        '  Output: {{"aliases": ["Apple Computer", "Apple"]}}\n\n'
        "Example 2 — recent corporate rename with description, former name well-known:\n"
        "  Name: Meta Platforms, Inc.\n"
        "  Ticker: META\n"
        "  Description: Meta Platforms, Inc. (formerly Facebook, Inc.) operates social "
        "media and messaging products, including Facebook, Instagram, WhatsApp.\n"
        "  Existing aliases: Meta Platforms Inc., META, US30303M1027\n"
        '  Output: {{"aliases": ["Facebook", "Facebook Inc."]}}\n\n'
        "Example 3 — well-known company, NO description, casing variant only:\n"
        "  Name: NVIDIA Corporation\n"
        "  Ticker: NVDA\n"
        "  Description: \n"
        "  Existing aliases: NVIDIA Corporation, NVDA\n"
        '  Output: {{"aliases": ["NVIDIA", "nVidia"]}}\n\n'
        "Example 4 — obscure ticker, empty description, NO well-established aliases:\n"
        "  Name: Foreward Industries Inc.\n"
        "  Ticker: FORD\n"
        "  Description: \n"
        "  Existing aliases: Foreward Industries Inc., FORD\n"
        '  Output: {{"aliases": []}}\n\n'
        "INPUT:\n"
        "  Name: {name}\n"
        "  Ticker: {ticker}\n"
        "  Description: {description}\n"
        "  Existing aliases: {aliases_so_far}\n\n"
        'Return JSON only: {{"aliases": ["..."]}}'
    ),
    parameters=frozenset({"name", "ticker", "description", "aliases_so_far"}),
)
