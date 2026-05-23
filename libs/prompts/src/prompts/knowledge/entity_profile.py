"""Provisional entity profile extraction prompt (S7 Worker 13E — PRD §6.7 Block 13E)."""

from __future__ import annotations

from prompts._base import PromptTemplate

ENTITY_PROFILE = PromptTemplate(
    name="entity_profile",
    version="2.0",
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
        "- entity_type MUST be exactly one of: financial_instrument | person | event |"
        " sector | industry | macro_indicator | place | product | index | currency | unknown\n"
        "  Definitions: financial_instrument=stocks/ETFs/bonds/futures/options/companies;"
        " person=named individuals (executives, analysts, politicians);"
        " event=scheduled events (earnings, Fed meetings, product launches);"
        " sector=market sectors (Technology, Healthcare, Energy);"
        " industry=industry groups (Semiconductors, Biotech, Retail);"
        " macro_indicator=economic metrics (CPI, GDP, unemployment rate);"
        " place=cities/countries/regions;"
        " product=products or services (iPhone, ChatGPT, Bitcoin);"
        " index=market indices (S&P 500, Nasdaq, FTSE);"
        " currency=currencies (USD, EUR, BTC);"
        " unknown=use only when type cannot be determined.\n"
        "  Do NOT invent new types. Do NOT use 'company', 'organization', 'country',"
        " 'commodity', 'concept', or 'other' — use the canonical list above.\n\n"
        "Respond with JSON only:\n"
        '{{"canonical_name": "...", "entity_type": "...", "ticker": null, "isin": null,'
        ' "aliases": []}}\n'
        "Use null (not empty string) for unknown fields."
    ),
    parameters=frozenset({"name", "entity_class"}),
)
