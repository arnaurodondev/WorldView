"""Ticker-symbol normalisation helpers shared across services.

The knowledge-graph entity-resolution path (S6) and the NLP entity-resolution
block (S5) both turn raw, provider-suffixed symbols into the canonical bare
ticker used as a dedup key.  Before this module each service stripped (or failed
to strip) suffixes inconsistently, so an EODHD-style ``AAPL.MX`` or ``NVDA.US``
never matched the bare ``AAPL`` / ``NVDA`` canonical and a *new* tickerless
duplicate canonical was minted (root cause, 2026-06-15 entity-matching audit).

The single source of truth is :func:`strip_exchange_qualifier`.
"""

from __future__ import annotations

import re

# Known EODHD / vendor exchange-code suffixes that decorate a base symbol as
# ``SYMBOL.EXCHANGE`` (e.g. ``AAPL.MX`` = Apple on the Mexican BMV, ``NVDA.US``
# = the EODHD US-composite form of ``NVDA``).  These are *venue* qualifiers: the
# underlying instrument is the same company, so they must collapse to the bare
# symbol for identity/dedup purposes.
#
# DESIGN — why an allowlist and not "strip anything after a dot":
#   * Single-letter share classes (``BRK.A``, ``BRK.B``) must be PRESERVED — they
#     are genuinely different securities.  An allowlist excludes them for free:
#     ``A``/``B`` are not exchange codes, so they never match.
#   * Preferred-share notations (``JPM.PRM``, ``BAC.PRK``) must be PRESERVED —
#     a preferred share is a distinct instrument.  ``PRM``/``PRK`` are not
#     exchange codes, so they never match either.
#   * We deliberately list only MULTI-LETTER codes.  Single-letter venue codes
#     (``.L`` London, ``.F`` Frankfurt, ``.V`` TSX-V) are intentionally omitted
#     so the rule can never collide with a single-letter share class.  The
#     concrete artifacts this fixes (``.US/.MX/.BA/.SN`` …) are all multi-letter,
#     so excluding single-letter codes costs nothing today and keeps the rule
#     provably safe.
#
# Sourced from EODHD's exchange-code list (multi-letter entries only) plus the
# Latin-American venues observed in the live tickerless-canonical artifacts.
_EXCHANGE_SUFFIXES: frozenset[str] = frozenset(
    {
        # North America
        "US",  # EODHD US composite
        "TO",  # Toronto (TSX)
        "NEO",  # NEO Exchange (Canada)
        "MX",  # Mexico (BMV)
        # South America
        "SA",  # Brazil (B3)
        "BA",  # Argentina (BCBA)
        "SN",  # Chile (Santiago)
        "LM",  # Peru (Lima)
        "CR",  # Colombia
        # Europe (multi-letter only)
        "XETRA",  # Deutsche Börse Xetra
        "BE",  # Berlin
        "MU",  # Munich
        "STU",  # Stuttgart
        "HM",  # Hamburg
        "HA",  # Hanover
        "DU",  # Düsseldorf
        "MI",  # Milan (Borsa Italiana)
        "PA",  # Euronext Paris
        "AS",  # Euronext Amsterdam
        "BR",  # Euronext Brussels
        "LS",  # Euronext Lisbon
        "MC",  # Madrid (BME)
        "VI",  # Vienna
        "IR",  # Euronext Dublin
        "ST",  # Stockholm (Nasdaq Nordic)
        "CO",  # Copenhagen
        "HE",  # Helsinki
        "OL",  # Oslo
        "IC",  # Iceland
        "WAR",  # Warsaw (GPW)
        "SW",  # SIX Swiss
        "AT",  # Athens
        "BUD",  # Budapest
        "RO",  # Bucharest
        "ZSE",  # Zagreb
        "TA",  # Tel Aviv
        # Asia-Pacific
        "AU",  # Australia (ASX)
        "AX",  # ASX (alt code)
        "NZ",  # New Zealand (NZX)
        "HK",  # Hong Kong (HKEX)
        "SHG",  # Shanghai
        "SHE",  # Shenzhen
        "KO",  # Korea (KOSPI)
        "KQ",  # KOSDAQ
        "KS",  # Korea (alt)
        "TW",  # Taiwan
        "TWO",  # Taipei (OTC)
        "NSE",  # India National Stock Exchange
        "BSE",  # India Bombay Stock Exchange
        "JK",  # Jakarta (Indonesia)
        "KLSE",  # Malaysia (Bursa)
        "BK",  # Thailand (SET)
        "SR",  # Saudi (Tadawul)
        "QA",  # Qatar
        "KW",  # Kuwait
        # Africa
        "JSE",  # Johannesburg
        "EGX",  # Egypt
    }
)


def strip_exchange_qualifier(symbol: str | None) -> str | None:
    """Return ``symbol`` with a trailing ``.EXCHANGE`` venue suffix removed.

    ``AAPL.MX`` -> ``AAPL``; ``NVDA.US`` -> ``NVDA``.  Symbols without a
    recognised exchange suffix are returned unchanged (case and surrounding
    whitespace preserved aside from a leading/trailing strip), so:

    * ``BRK.A`` -> ``BRK.A`` (``A`` is a share class, not an exchange)
    * ``JPM.PRM`` -> ``JPM.PRM`` (``PRM`` is a preferred-share notation)
    * ``AAPL`` -> ``AAPL`` (no dot)
    * ``""`` / ``None`` -> returned as-is

    The split is on the LAST dot only, and only a single qualifier is removed
    (``BABA.US`` -> ``BABA``; we never recurse).  The base part must itself be
    non-empty, so a pathological ``".US"`` is left untouched.

    Args:
        symbol: Raw ticker, possibly suffixed with an exchange code.

    Returns:
        The bare ticker if a recognised exchange suffix was stripped, otherwise
        the input unchanged (``None``/empty passed straight through).
    """
    if not symbol:
        return symbol
    candidate = symbol.strip()
    if "." not in candidate:
        return candidate
    base, _, suffix = candidate.rpartition(".")
    if base and suffix.upper() in _EXCHANGE_SUFFIXES:
        return base
    return candidate


# Leading ``EXCHANGE:`` prefix as it appears in raw news/GLiNER mention spans:
# ``"NYSE: BCS"``, ``"NASDAQ:AAPL"``, ``"LSE: TSCO"``. This is the venue-qualified
# TICKER *alias* form and must NEVER leak into a canonical_name (R2:
# docs/audits/2026-07-16-kg-data-quality-eval.md flagged 87 junk
# ``^(NYSE|NASDAQ|LSE|NSE): …`` canonical entities minted from the news backfill).
# Matches 2-6 uppercase letters (an MIC/venue code) + ``:`` + optional whitespace
# at the START of the string only. Kept deliberately narrow so a legitimate name
# containing a colon (e.g. "Vroom: The Car Company") is not mangled — a real
# company name does not begin with an all-caps 2-6 letter token immediately
# followed by a colon.
_EXCHANGE_PREFIX_RE = re.compile(r"^[A-Z]{2,6}:\s*")


def strip_exchange_prefix(name: str | None) -> str | None:
    """Strip a leading ``EXCHANGE:`` venue prefix from a would-be canonical name.

    ``"NYSE: BCS"`` -> ``"BCS"``; ``"NASDAQ:AAPL"`` -> ``"AAPL"``;
    ``"LSE: TSCO"`` -> ``"TSCO"``. Strings without a leading exchange prefix are
    returned unchanged (aside from a surrounding strip):

    * ``"Apple Inc."`` -> ``"Apple Inc."`` (no prefix)
    * ``"Vroom: The Car Company"`` -> unchanged (``Vroom`` is not all-caps 2-6)
    * ``""`` / ``None`` -> returned as-is

    Only a SINGLE leading prefix is removed (never recurses). If stripping would
    leave an empty string the original (stripped) value is returned so we never
    manufacture a blank canonical name.

    Args:
        name: Raw canonical-name candidate, possibly an exchange-prefixed ticker.

    Returns:
        The name with any leading ``EXCHANGE:`` prefix removed.
    """
    if not name:
        return name
    candidate = name.strip()
    stripped = _EXCHANGE_PREFIX_RE.sub("", candidate, count=1).strip()
    return stripped or candidate
