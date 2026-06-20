"""Deterministic post-extraction relation validation (precision gates).

Background
----------
The DEEP_EXTRACTION prompt (``libs/prompts/src/prompts/extraction/deep.py``, v1.6)
*instructs* the model to never emit:

  1. self-loops (``subject_ref == object_ref``),
  2. out-of-vocabulary predicates (anything outside the closed 32-type set),
  3. ``listed_on`` objects that are an index (S&P 500) or a ticker (COST) rather
     than a real stock exchange,
  4. bare common-noun endpoints ("stock", "shares", "oil", "e-commerce").

The 2026-06-14 v1.6 re-A/B audit
(``docs/audits/2026-06-14-extraction-prompt-v16-reab.md``) proved the model ignores
these explicitly-named, few-shot-demonstrated prohibitions roughly **one third of the
time** — the prompt halves the defect rate but cannot *guarantee* the gates. Those four
defect classes are *structural*: a relation that violates one cannot be true regardless
of what the article says, so they are safe to drop deterministically in code.

This module enforces the four gates **after the LLM returns and before relations become
evidence**. A code filter makes zero-self-loop / zero-OOV / valid-exchange a guarantee
independent of model drift. It is intentionally CONSERVATIVE: it only drops relations
that are structurally invalid, never relations that are merely low-confidence —
confidence/decay handling stays in S7 (``knowledge_graph.domain.confidence``).

The valid-predicate set here mirrors the prompt's closed vocabulary; a unit test
(``test_relation_validation.py``) asserts the two stay in sync so the gate never drifts
from what the model is told to emit.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# ── Gate #2: closed predicate vocabulary ──────────────────────────────────────
# The exact 32 predicates declared in the DEEP_EXTRACTION prompt. Anything outside
# this set is an invented predicate (e.g. 'advertises_on', 'consulted', 'capital_raise')
# and is dropped. Kept alphabetised to mirror the prompt and ease diffing.
VALID_PREDICATES: frozenset[str] = frozenset(
    {
        "acquired_by",
        "analyst_rating",
        "appointed_as",
        "board_member_of",
        "competes_with",
        "corporate_action",
        "credit_rating",
        "divested_from",
        "downgraded_by",
        "earnings_guidance",
        "earnings_released",
        "employs",
        "filed_lawsuit_against",
        "has_executive",
        "headquartered_in",
        "investment_in",
        "is_in_industry",
        "is_in_sector",
        "issues_debt",
        "listed_on",
        "market_share_claim",
        "operates_in_country",
        "owns_stake_in",
        "partner_of",
        "price_target",
        "produces",
        "regulates",
        "reported_revenue_of",
        "revenue_from_country",
        "sentiment_signal",
        "subsidiary_of",
        "supplier_of",
    }
)

# ── Gate #3: real stock exchanges for `listed_on` objects ─────────────────────
# An allow-list is the right shape here: it rejects BOTH indices (S&P 500, Dow, Nasdaq
# Composite, FTSE 100, Russell 2000) and ticker symbols (COST) in one rule, because
# neither appears in the list. Keys are *alphanumeric-normalised* (lower-cased, every
# non-[a-z0-9] character removed — see ``_normalize_exchange``) so spelling/punctuation
# variants collapse onto one entry: "NASDAQ GS" / "NasdaqGS" / "Nasdaq-GS" → "nasdaqgs".
#
# This normalisation was validated against the live corpus (2026-06-18): the bare
# allow-list mis-flagged ~360 real listings written as "NasdaqGS", "NYSE MKT", "FSE",
# "CSE", "TSX Venture"; the normalised form keeps them while still dropping every index
# and ticker. Crucially "nasdaq" (exchange) stays in the set but "nasdaqcomposite"
# (index) does not, so the exchange/index distinction survives normalisation.
# Extend as real exchanges surface; NEVER add an index, ticker, country, or company.
_VALID_EXCHANGES: frozenset[str] = frozenset(
    {
        # United States
        "nyse",
        "newyorkstockexchange",
        "nyseamerican",
        "nysemkt",
        "nysearca",
        "nasdaq",
        "nasdaqgs",
        "nasdaqgm",
        "nasdaqcm",
        "nasdaqinc",
        "nasdaqomx",
        "nasdaqstockmarket",
        "nasdaqglobalselectmarket",
        "nasdaqglobalmarket",
        "nasdaqcapitalmarket",
        "cboe",
        "cboebzx",
        "cboeglobalmarkets",
        "cboeglobalmarketsinc",
        "otcmarkets",
        "otcmarketsgroup",
        "otcqx",
        "otcqb",
        "otc",
        # Canada
        "tsx",
        "torontostockexchange",
        "tsxv",
        "tsxventure",
        "tsxventureexchange",
        "cse",
        "canadiansecuritiesexchange",
        # United Kingdom / Europe
        "lse",
        "londonstockexchange",
        "aim",
        "euronext",
        "euronextparis",
        "euronextamsterdam",
        "euronextbrussels",
        "euronextlisbon",
        "deutscheborse",
        "frankfurt",
        "frankfurtstockexchange",
        "fse",
        "xetra",
        "six",
        "sixswissexchange",
        "borsaitaliana",
        "bme",
        "bolsademadrid",
        "nasdaqstockholm",
        "nasdaqcopenhagen",
        "nasdaqhelsinki",
        "oslobors",
        "moex",
        "moscowexchange",
        # Asia-Pacific
        "tse",
        "tokyostockexchange",
        "jpx",
        "japanexchangegroup",
        "hkex",
        "hongkongstockexchange",
        "sehk",
        "sse",
        "shanghaistockexchange",
        "szse",
        "shenzhenstockexchange",
        "krx",
        "koreaexchange",
        "sgx",
        "singaporeexchange",
        "asx",
        "australiansecuritiesexchange",
        "nse",
        "nationalstockexchangeofindia",
        "bse",
        "bombaystockexchange",
        "twse",
        "taiwanstockexchange",
        "set",
        "stockexchangeofthailand",
        "idx",
        "indonesiastockexchange",
        # Middle East / Africa / LatAm
        "tadawul",
        "saudiexchange",
        "jse",
        "johannesburgstockexchange",
        "b3",
        "bmv",
        "bolsamexicanadevalores",
    }
)

_EXCHANGE_STRIP = re.compile(r"[^a-z0-9]")

# ── Gate #4: generic common nouns that are never valid entity endpoints ───────
# Intentionally tight and unambiguous — only words that can NEVER name a specific entity.
# Countries, regions and cities are NOT here: they are valid endpoints for
# headquartered_in / operates_in_country / revenue_from_country.
_COMMON_NOUN_ENDPOINTS: frozenset[str] = frozenset(
    {
        "stock",
        "stocks",
        "the stock",
        "share",
        "shares",
        "equity",
        "equities",
        "the company",
        "company",
        "the market",
        "market",
        "markets",
        "oil",
        "crude",
        "crude oil",
        "gas",
        "natural gas",
        "e-commerce",
        "ecommerce",
        "the economy",
        "economy",
        "bonds",
        "bond",
        "the dollar",
    }
)


def _normalize(value: Any) -> str:
    """Lower-case, strip surrounding whitespace/punctuation, collapse inner whitespace.

    Used for equality-style comparisons (self-loop detection, allow-list / stop-list
    membership). Deliberately light: it does not attempt entity canonicalisation, only
    enough normalisation to make "Oil" == "oil" and "NYSE " == "nyse".
    """
    if value is None:
        return ""
    text = str(value).strip().strip(".,;:'\"()[]").strip()
    return " ".join(text.lower().split())


def _normalize_exchange(value: Any) -> str:
    """Lower-case and strip every non-alphanumeric character for exchange matching.

    Collapses spelling/punctuation variants onto one key ("NASDAQ GS", "NasdaqGS",
    "Nasdaq-GS" → "nasdaqgs") so the allow-list does not mis-flag real listings, while
    still separating an exchange ("nasdaq") from an index ("nasdaqcomposite").
    """
    if value is None:
        return ""
    return _EXCHANGE_STRIP.sub("", str(value).lower())


def validate_relations(relations: list[Any]) -> tuple[list[Any], dict[str, int]]:
    """Apply the four deterministic precision gates to extracted relations.

    Drops, in priority order (one reason counted per dropped relation):

      * ``empty_field``       — missing/blank subject_ref, predicate, or object_ref
      * ``self_loop``         — subject and object normalise to the same entity
      * ``oov_predicate``     — predicate not in the closed 32-type vocabulary
      * ``common_noun_endpoint`` — subject or object is a bare generic noun
      * ``invalid_listed_on`` — ``listed_on`` object is not a real stock exchange

    Returns ``(kept_relations, drop_counts)`` where ``drop_counts`` maps reason → count
    (empty when nothing was dropped). The input order of kept relations is preserved.
    Relations are treated as plain mappings; non-dict items are dropped as ``empty_field``.
    """
    kept: list[Any] = []
    drops: Counter[str] = Counter()

    for relation in relations:
        if not isinstance(relation, dict):
            drops["empty_field"] += 1
            continue

        subject_raw = relation.get("subject_ref")
        object_raw = relation.get("object_ref")
        predicate = str(relation.get("predicate") or "").strip()

        subject_norm = _normalize(subject_raw)
        object_norm = _normalize(object_raw)

        # Gate #1 (and basic hygiene): every endpoint and the predicate must be present.
        if not subject_norm or not object_norm or not predicate:
            drops["empty_field"] += 1
            continue

        # Gate #1: no self-loops — subject and object must be distinct entities.
        if subject_norm == object_norm:
            drops["self_loop"] += 1
            continue

        # Gate #2: closed predicate vocabulary — drop invented predicates.
        if predicate not in VALID_PREDICATES:
            drops["oov_predicate"] += 1
            continue

        # Gate #4: neither endpoint may be a bare generic common noun.
        if subject_norm in _COMMON_NOUN_ENDPOINTS or object_norm in _COMMON_NOUN_ENDPOINTS:
            drops["common_noun_endpoint"] += 1
            continue

        # Gate #3: listed_on object must be a real stock exchange (not an index/ticker).
        if predicate == "listed_on" and _normalize_exchange(object_raw) not in _VALID_EXCHANGES:
            drops["invalid_listed_on"] += 1
            continue

        kept.append(relation)

    return kept, dict(drops)
