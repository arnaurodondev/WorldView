"""Provisional entity profile extraction prompt (S7 Worker 13E — PRD §6.7 Block 13E)."""

from __future__ import annotations

from prompts._base import PromptTemplate

ENTITY_PROFILE = PromptTemplate(
    name="entity_profile",
    version="2.2",
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
        " sector | industry | macro_indicator | place | product | index | exchange |"
        " organization | currency | unknown\n"
        "  Definitions: financial_instrument=a TRADEABLE security with a ticker"
        " (stocks/ETFs/bonds/futures/options of PUBLICLY-LISTED companies);"
        " person=named individuals (executives, analysts, politicians);"
        " event=scheduled events (earnings, Fed meetings, product launches);"
        " sector=market sectors (Technology, Healthcare, Energy);"
        " industry=industry groups (Semiconductors, Biotech, Retail);"
        " macro_indicator=economic metrics (CPI, GDP, unemployment rate);"
        " place=cities/countries/regions;"
        " product=products or services (iPhone, ChatGPT, Bitcoin);"
        " index=market indices (the S&P 500, Dow Jones, FTSE 100 — a *basket* of"
        " securities, NOT the venue they trade on);"
        " exchange=stock exchanges / trading venues (NYSE, NASDAQ, LSE, Euronext, Cboe);"
        " organization=a company/agency/non-profit/institution that is NOT a tradeable"
        " instrument and has NO ticker — private companies (SpaceX, Anthropic, Stripe),"
        " government bodies & agencies (the Federal Reserve, the SEC, the IMF),"
        " universities & research firms (MIT, Zacks, Y Combinator), and"
        " foundations / NGOs (Duke Energy Foundation, the Gates Foundation);"
        " currency=the unit of money ONLY (USD, EUR, JPY, BTC);"
        " unknown=use only when type cannot be determined.\n"
        "  DISAMBIGUATION RULES (apply before choosing the type):\n"
        "  1. A stock exchange or trading VENUE (NYSE, NASDAQ, NasdaqGS, LSE, Cboe) is"
        " 'exchange' — NEVER 'index' and NEVER 'financial_instrument'. The NASDAQ"
        " *exchange* is 'exchange'; the Nasdaq *Composite* (an index basket) is 'index'.\n"
        "  2. Country names and abbreviations — 'U.S.', 'US', 'USA', 'U.K.', 'UK',"
        " 'United States', 'China' — are 'place', NEVER 'currency'. Use 'currency' only"
        " for the actual money unit (the U.S. dollar = currency; the U.S. = place).\n"
        "  3. 'financial_instrument' is ONLY for tradeable securities that have (or"
        " could have) a ticker — publicly-listed stocks, ETFs, bonds, futures,"
        " options. A PRIVATE company, agency, university, research firm, or"
        " foundation with NO ticker is 'organization', NEVER 'financial_instrument'."
        " (SpaceX, Anthropic, Y Combinator, Zacks, the SEC, Duke Energy Foundation"
        " are all 'organization'.) If you are tempted to type a company as"
        " 'financial_instrument' but you cannot give a confident ticker, it is"
        " almost certainly 'organization'.\n"
        "  4. A generic market PHRASE is NOT a distinct entity. If the mention is"
        " 'Nvidia shares', 'Microsoft Stock', 'Alphabet stock', 'stock futures' or"
        " similar, resolve it to the UNDERLYING company/instrument: return that"
        " company's canonical_name and ticker (e.g. 'Nvidia shares' -> canonical_name"
        " 'NVIDIA Corporation', ticker 'NVDA') — do NOT mint the phrase as its own"
        " financial_instrument.\n"
        "  Do NOT invent new types. Do NOT use 'company', 'country',"
        " 'commodity', 'concept', or 'other' — use the canonical list above"
        " (a 'company' is 'financial_instrument' if it trades with a ticker,"
        " otherwise 'organization').\n\n"
        "Respond with JSON only:\n"
        '{{"canonical_name": "...", "entity_type": "...", "ticker": null, "isin": null,'
        ' "aliases": []}}\n'
        "Use null (not empty string) for unknown fields."
    ),
    parameters=frozenset({"name", "entity_class"}),
)
