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

Enhancements #3/#4/#5 (2026-06-21 — entity-type-aware gates)
------------------------------------------------------------
The 2026-06-20 stored-relation re-measurement
(``docs/audits/2026-06-20-stored-relation-quality-remeasurement.md``) pinned the real
support rate at ~37% predicate-balanced / ~49% volume-weighted and located the failures:
**76% extraction, 22% entity-resolution, 1% evidence-storage**. The 22% entity-resolution
class and a big slice of the extraction class (WRONG_DIRECTION on firm-vs-company
predicates) are *deterministically catchable* from the NER class of each endpoint, which
is already on every ``EntityMention`` (``mention_class``, 11 ``MentionClass`` values).

Three optional, conservative gates were added, all driven by a single
``{entity_name: mention_class}`` map threaded from the call site:

  * **#3 entity-type guard** (``entity_type_mismatch``) — drop relations whose
    subject/object NER class is structurally invalid for the predicate (audit rec #5),
    e.g. ``competes_with`` against an index, ``analyst_rating`` with a firm as *subject*.
  * **#4 direction auto-swap** (``direction_swapped`` — NOT a drop) — for firm-vs-company
    / person-company predicates with a fixed convention, if the two endpoint classes are
    unambiguously reversed, swap ``subject_ref``/``object_ref`` rather than discard the
    edge (audit rec #2: "deterministic post-extraction normaliser could auto-swap").
  * **#5 predicate suppression** (``suppressed_predicate``) — drop predicates the audit
    measured at near-zero support (audit rec #3).

All three are **conservative by construction**: when an endpoint's class is unknown
(not in the map), the type/direction gates do nothing, so they never produce a
false-positive drop on entities the NER stage did not classify. They are no-ops when
``entity_classes`` is ``None`` (the default), so existing callers and tests are
unaffected.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
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


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #5: predicate suppression
# ──────────────────────────────────────────────────────────────────────────────
# Predicates the 2026-06-20 re-measurement measured at *near-zero* support — i.e. the
# model was given a new taxonomy label (PLAN-0089 Lever-4) it cannot apply reliably, so
# almost every emitted edge is wrong. The audit (rec #3, "Suppress the worst new
# predicates until extraction is reliable") explicitly names these as "near-pure noise"
# and notes they are low-volume, so dropping them is cheap and immediately lifts quality.
#
# Each entry is justified from the audit's per-predicate support table:
#   credit_rating     — 0% support  (rock-bottom by rate; "Simply Wall St. credit_rating
#                       Salesforce" — a website as a rating agency). Pure noise.
#   earnings_released — 0% support. NOTE: this is arguably an EVENT, not a relation
#                       (an EARNINGS_RELEASE event_type already exists in the prompt's
#                       event vocabulary). It should be *re-routed* to the event channel,
#                       not represented as a binary subject→object relation. We do NOT
#                       attempt that re-routing here (out of scope for a write-time gate);
#                       we only suppress the relation form. Flagged for follow-up.
#   corporate_action  — 8% support ("Berkshire Hathaway corporate_action Stock futures").
#                       Same as earnings_released: better modelled as a CORPORATE_ACTION
#                       event than a relation; suppressed here pending re-routing.
#
# CONSERVATISM: deliberately *narrow*. price_target (8%), downgraded_by (8%),
# reported_revenue_of (8%) and market_share_claim (10%) are also low but are NOT
# suppressed — #3 (type guard) and #4 (direction swap) recover a meaningful share of
# their defects (mis-typed / inverted endpoints), so blanket-dropping them would discard
# the relations those gates can *fix*. Only the three predicates with a *structural*
# modelling problem (0% rate and/or "should be an event") are suppressed outright.
#
# Config-driven: override at deploy time via the RELATION_SUPPRESSED_PREDICATES env var
# (comma-separated). Empty/unset → the audited default below.
def _load_suppressed_predicates() -> frozenset[str]:
    """Read the suppression list from env, falling back to the audited default.

    ``RELATION_SUPPRESSED_PREDICATES`` is a comma-separated predicate list. An explicit
    empty string disables suppression entirely (escape hatch). Unknown predicates in the
    override are ignored against ``VALID_PREDICATES`` so a typo cannot silently suppress
    nothing-or-everything.
    """
    import os

    raw = os.environ.get("RELATION_SUPPRESSED_PREDICATES")
    if raw is None:
        return _DEFAULT_SUPPRESSED_PREDICATES
    parsed = {p.strip() for p in raw.split(",") if p.strip()}
    # Only honour predicates that are actually in the closed vocabulary.
    return frozenset(parsed & VALID_PREDICATES)


_DEFAULT_SUPPRESSED_PREDICATES: frozenset[str] = frozenset(
    {
        "credit_rating",  # 0% support — website-as-rating-agency noise
        "earnings_released",  # 0% support — should be an EVENT, not a relation
        "corporate_action",  # 8% support — should be an EVENT, not a relation
    }
)

SUPPRESSED_PREDICATES: frozenset[str] = _load_suppressed_predicates()


# ──────────────────────────────────────────────────────────────────────────────
# NER class groupings (mirror MentionClass in nlp_pipeline.domain.enums)
# ──────────────────────────────────────────────────────────────────────────────
# We compare against bare lower-case strings so this module stays import-light and does
# not couple the gate to the domain enum (the threaded map already carries StrEnum values,
# which compare equal to their string form). Grouped for readability of the policy below.
#
# A "company-like" endpoint is anything that can legitimately be a corporate counterparty
# in a company-relation: a plain company, a bank/asset-manager, or a regulator/government
# body (which CAN be a subject of `regulates` / object of `filed_lawsuit_against`).
_CLASS_ORGANIZATION = "organization"
_CLASS_FINANCIAL_INSTITUTION = "financial_institution"
_CLASS_PERSON = "person"
_CLASS_INDEX = "index"
_CLASS_CURRENCY = "currency"
_CLASS_COMMODITY = "commodity"
_CLASS_FINANCIAL_INSTRUMENT = "financial_instrument"
_CLASS_LOCATION = "location"
_CLASS_GOVERNMENT_BODY = "government_body"
_CLASS_REGULATORY_BODY = "regulatory_body"
_CLASS_MACRO_INDICATOR = "macroeconomic_indicator"

# Classes that can NEVER be a corporate counterparty (company / firm) in a company-to-
# company predicate. These are the "abstract market object" classes the audit repeatedly
# flagged as entity-resolution defects ("American Express competes_with Dow Jones").
_NON_COMPANY_CLASSES: frozenset[str] = frozenset(
    {
        _CLASS_INDEX,
        _CLASS_CURRENCY,
        _CLASS_COMMODITY,
        _CLASS_MACRO_INDICATOR,
        _CLASS_FINANCIAL_INSTRUMENT,
    }
)

# Classes that count as a "company / firm" endpoint (an issuer, bank, or asset manager).
# Note: a person is NOT here — person-vs-company direction is handled separately by #4.
_COMPANY_LIKE_CLASSES: frozenset[str] = frozenset(
    {
        _CLASS_ORGANIZATION,
        _CLASS_FINANCIAL_INSTITUTION,
    }
)


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #3: predicate → allowed endpoint-type policy
# ──────────────────────────────────────────────────────────────────────────────
# For each guarded predicate we declare, per side, the set of NER classes that side is
# *forbidden* to be. We use a deny-list (forbidden classes) rather than an allow-list so
# the gate stays conservative: a side with no entry, or an endpoint whose class is unknown
# (absent from the threaded map), is NEVER dropped. Only an endpoint whose KNOWN class is
# in the forbidden set triggers an ``entity_type_mismatch`` drop.
#
# Derived from the prompt's predicate definitions + the audit's named ENTITY_RESOLUTION
# defects. Each `subject`/`object` value is a frozenset of FORBIDDEN classes.
_FORBIDDEN_ENDPOINT_CLASSES: dict[str, dict[str, frozenset[str]]] = {
    # listed_on — object must be a real exchange (Gate #3 already drops non-exchanges by
    # name); the type signal additionally forbids index/currency/commodity/macro/
    # instrument objects even if their spelling happened to dodge the exchange allow-list.
    "listed_on": {"object": _NON_COMPANY_CLASSES},
    # Company-to-company rivalry/relationship predicates: neither endpoint may be an
    # index/currency/commodity/macro/instrument. "American Express competes_with Dow Jones"
    # (index as competitor) is the canonical audited defect.
    "competes_with": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "partner_of": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "supplier_of": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "competes": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "acquired_by": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "subsidiary_of": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "divested_from": {"subject": _NON_COMPANY_CLASSES},
    "investment_in": {"subject": _NON_COMPANY_CLASSES, "object": _NON_COMPANY_CLASSES},
    "owns_stake_in": {"object": _NON_COMPANY_CLASSES},
    "produces": {"subject": _NON_COMPANY_CLASSES},
    "is_in_sector": {"subject": _NON_COMPANY_CLASSES},
    "is_in_industry": {"subject": _NON_COMPANY_CLASSES},
    # operates_in_country / revenue_from_country / headquartered_in: the SUBJECT is a
    # company; an index/currency/commodity/macro/instrument cannot "operate in" a country.
    # (Object is a location and is not type-guarded here — Gate #4 common-noun already
    # protects bogus place names.)
    "operates_in_country": {"subject": _NON_COMPANY_CLASSES},
    "revenue_from_country": {"subject": _NON_COMPANY_CLASSES},
    "headquartered_in": {"subject": _NON_COMPANY_CLASSES},
    # Rating / analyst predicates. Per the prompt: subject=company (issuer), object=the
    # analyst/rating firm. So NEITHER side may be an index/currency/commodity/macro/
    # instrument, AND the issuer side (subject) may not be a person.
    #   analyst_rating / price_target / credit_rating: subject=issuer, object=firm.
    #   downgraded_by: subject=company, object=firm.
    "analyst_rating": {
        "subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON},
        "object": _NON_COMPANY_CLASSES,
    },
    "price_target": {
        "subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON},
        "object": _NON_COMPANY_CLASSES,
    },
    "downgraded_by": {
        "subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON},
        "object": _NON_COMPANY_CLASSES,
    },
    # Person-company predicates: the COMPANY side may not be a person, and may not be an
    # index/currency/commodity/macro/instrument; the PERSON side must not be one of those
    # market-object classes either (a person is the only sensible value, but we only forbid
    # the clearly-wrong classes to stay conservative — direction is fixed by #4).
    #   has_executive / employs / appointed_as: subject=company, object=person.
    #   board_member_of: subject=person, object=company.
    "has_executive": {"subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON}},
    "employs": {"subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON}},
    "appointed_as": {"subject": _NON_COMPANY_CLASSES | {_CLASS_PERSON}},
    "board_member_of": {"object": _NON_COMPANY_CLASSES | {_CLASS_PERSON}},
}


# ──────────────────────────────────────────────────────────────────────────────
# Enhancement #4: direction auto-swap conventions
# ──────────────────────────────────────────────────────────────────────────────
# For predicates with a FIXED subject/object convention (read from the prompt's
# "DIRECTION RULE" + per-predicate definitions), we record the canonical class-role of
# each side. If the two endpoints' KNOWN classes are *unambiguously reversed* relative to
# the convention, we SWAP the refs instead of dropping the edge — recovering the 54
# WRONG_DIRECTION extraction defects the audit attributes to firm-vs-company confusion
# ("Wedbush analyst_rating Amazon" → should be Amazon←subject, Wedbush←object).
#
# Each convention is (subject_role, object_role) where a role is a frozenset of the
# classes that side should be. A swap fires ONLY when:
#   * both endpoint classes are known, AND
#   * subject's class matches the *object* role and object's class matches the *subject*
#     role (i.e. they are exactly transposed), AND
#   * the two roles are disjoint (so "reversed" is unambiguous — symmetric predicates,
#     where both sides share a role, can never trigger a swap).
#
# Person-company predicates (subject=company, object=person):
_ROLE_COMPANY = _COMPANY_LIKE_CLASSES
_ROLE_PERSON = frozenset({_CLASS_PERSON})
# Firm-vs-issuer rating predicates: both sides are company-like in class, so they are NOT
# class-distinguishable and are intentionally EXCLUDED from auto-swap (a swap there would
# need name-level knowledge of which org is the analyst firm — out of scope for a
# class-only gate; the audit's name-based normaliser is a separate, future enhancement).
_SWAP_CONVENTIONS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # subject=company, object=person
    "has_executive": (_ROLE_COMPANY, _ROLE_PERSON),
    "employs": (_ROLE_COMPANY, _ROLE_PERSON),
    "appointed_as": (_ROLE_COMPANY, _ROLE_PERSON),
    # subject=person, object=company
    "board_member_of": (_ROLE_PERSON, _ROLE_COMPANY),
}


def _class_of(name: Any, entity_classes: Mapping[str, str] | None) -> str | None:
    """Return the lower-cased NER class for ``name``, or ``None`` if unknown.

    Looks the raw ref up in the threaded map first (exact match — the model is instructed
    to echo refs verbatim from the entity list), then falls back to a case-insensitive
    match. Returns ``None`` when the entity was never classified, which makes every
    downstream type/direction check a no-op for that endpoint (the conservatism guarantee).
    """
    if not entity_classes or name is None:
        return None
    raw = str(name)
    cls = entity_classes.get(raw)
    if cls is None:
        # Case-insensitive fallback — build once per call would be wasteful; the maps are
        # tiny (≤ a few dozen mentions per doc) so a linear scan is fine.
        lowered = raw.lower()
        for key, value in entity_classes.items():
            if key.lower() == lowered:
                cls = value
                break
    if cls is None:
        return None
    return str(cls).lower()


def validate_relations(
    relations: list[Any],
    entity_classes: Mapping[str, str] | None = None,
) -> tuple[list[Any], dict[str, int]]:
    """Apply the deterministic precision gates to extracted relations.

    Drops, in priority order (one reason counted per dropped relation):

      * ``empty_field``         — missing/blank subject_ref, predicate, or object_ref
      * ``self_loop``           — subject and object normalise to the same entity
      * ``oov_predicate``       — predicate not in the closed 32-type vocabulary
      * ``suppressed_predicate`` — predicate is near-zero-support (Enhancement #5)
      * ``common_noun_endpoint`` — subject or object is a bare generic noun
      * ``invalid_listed_on``   — ``listed_on`` object is not a real stock exchange
      * ``entity_type_mismatch`` — an endpoint's NER class is invalid for the predicate
                                   (Enhancement #3 — only when ``entity_classes`` given)

    Plus one *normalisation* (NOT a drop), counted under ``direction_swapped``:

      * ``direction_swapped``   — a fixed-convention predicate's endpoints were reversed
                                  relative to the convention, so ``subject_ref`` and
                                  ``object_ref`` were swapped in place (Enhancement #4 —
                                  only when ``entity_classes`` given). The relation is
                                  KEPT with corrected direction; the swap is applied
                                  before the type guard so the corrected endpoints are
                                  type-checked.

    Parameters
    ----------
    relations:
        Extracted relation dicts (``subject_ref``/``predicate``/``object_ref`` + extras).
    entity_classes:
        Optional ``{entity_name: mention_class}`` map (NER class per mention). When
        ``None`` (default) the type guard (#3) and direction swap (#4) are skipped
        entirely — so existing callers/tests see *identical* behaviour. When provided,
        endpoints whose name is absent from the map (unknown class) are never dropped or
        swapped, keeping the gates free of false positives.

    Returns ``(kept_relations, drop_counts)`` where ``drop_counts`` maps reason → count
    (empty when nothing was dropped *and* nothing was swapped). The input order of kept
    relations is preserved. Relations are treated as plain mappings; non-dict items are
    dropped as ``empty_field``.
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

        # Enhancement #5: suppress near-zero-support predicates (config-driven).
        if predicate in SUPPRESSED_PREDICATES:
            drops["suppressed_predicate"] += 1
            continue

        # Gate #4 (common-noun): neither endpoint may be a bare generic common noun.
        if subject_norm in _COMMON_NOUN_ENDPOINTS or object_norm in _COMMON_NOUN_ENDPOINTS:
            drops["common_noun_endpoint"] += 1
            continue

        # Gate #3 (listed_on): object must be a real stock exchange (not an index/ticker).
        if predicate == "listed_on" and _normalize_exchange(object_raw) not in _VALID_EXCHANGES:
            drops["invalid_listed_on"] += 1
            continue

        # ── entity-type-aware gates (only when NER classes were threaded in) ──────────
        if entity_classes:
            subject_cls = _class_of(subject_raw, entity_classes)
            object_cls = _class_of(object_raw, entity_classes)

            # Enhancement #4: direction auto-swap. If a fixed-convention predicate's
            # endpoints are *unambiguously reversed* (subject has the object-role class
            # and object has the subject-role class, the two roles being disjoint), swap
            # the refs in place and KEEP the relation. Done BEFORE the type guard so the
            # corrected endpoints are what gets type-checked.
            convention = _SWAP_CONVENTIONS.get(predicate)
            if convention is not None and subject_cls is not None and object_cls is not None:
                subject_role, object_role = convention
                roles_disjoint = not (subject_role & object_role)
                reversed_match = subject_cls in object_role and object_cls in subject_role
                already_correct = subject_cls in subject_role and object_cls in object_role
                if roles_disjoint and reversed_match and not already_correct:
                    relation["subject_ref"], relation["object_ref"] = object_raw, subject_raw
                    subject_raw, object_raw = object_raw, subject_raw
                    subject_cls, object_cls = object_cls, subject_cls
                    drops["direction_swapped"] += 1

            # Enhancement #3: entity-type guard. Drop when a KNOWN endpoint class is in
            # the predicate's forbidden set for that side. Unknown class (None) → skip.
            policy = _FORBIDDEN_ENDPOINT_CLASSES.get(predicate)
            if policy is not None:
                subj_forbidden = policy.get("subject")
                obj_forbidden = policy.get("object")
                if (subject_cls is not None and subj_forbidden is not None and subject_cls in subj_forbidden) or (
                    object_cls is not None and obj_forbidden is not None and object_cls in obj_forbidden
                ):
                    drops["entity_type_mismatch"] += 1
                    continue

        kept.append(relation)

    return kept, dict(drops)
