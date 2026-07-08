"""Shared resolver-gate logic — F-LIVE-NEW-003 symmetric guard.

Background
----------
Two resolver paths exist in rag-chat:

* **IntelligenceHandler** (tool path): calls S7 alias-search per tool
  argument (e.g. ``search_claims(entity_name="Tesla")``). Already gated
  inline by stop-word strip + 0.75 absolute similarity floor + 0.15
  delta gate + tiebreaker rules.

* **ChatOrchestrator** (pre-prompt path): calls S6 ``/entities/resolve``
  on the user's raw query text once per turn, then surfaces the
  resolved entities directly in the LLM system prompt under
  ``Entities resolved from this query:``. **Until F-LIVE-NEW-003 this
  path bypassed all gates** — generic stop-word substrings (``space``,
  ``delta``, ``shell``, ``block``, ``square``) leaked through and
  bound to real public companies (SpaceX, Delta Air Lines, Shell plc,
  Block Inc., Square Inc.) at sim ~0.62. The LLM then hallucinated
  claims about those companies even when retrieval returned zero
  matching documents.

This module factors the *shared* gate primitives so both paths apply
identical stop-word + similarity-floor logic. The IntelligenceHandler
keeps its richer tiebreaker rules (rule 1 same-canonical collapse,
rule 2 exact-canonical match, rule 3 length-penalty) because they
require S7's ``alias_text`` field which S6's resolver does not return.

Behaviour contract — primary tests live in:
* ``tests/unit/application/pipeline/test_intelligence_name_resolution.py``
  (IntelligenceHandler path; must remain green after the refactor)
* ``tests/contract/test_resolver_gate_symmetry.py``
  (orchestrator path; new in F-LIVE-NEW-003)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResolverGateConfig:
    """Immutable tuning surface for ``filter_resolver_candidates``.

    Identical defaults to ``rag_chat.config.Settings``:
      * ``top_similarity_min`` = 0.75
      * ``delta_min``          = 0.15

    Tests inject custom values directly; production wiring builds this
    from ``Settings`` once at startup and passes a single instance to
    every gate call.
    """

    stop_words: frozenset[str]
    top_similarity_min: float = 0.75
    delta_min: float = 0.15


class _GatedCandidate(Protocol):
    """Structural protocol — the minimal candidate shape the gate needs.

    Both ``rag_chat.domain.entities.chat.ResolvedEntity`` (orchestrator
    path, uses ``.confidence``) and the raw S7 dict candidates
    (IntelligenceHandler path, uses ``["similarity"]``) are adapted to
    this shape via :class:`GatedEntity` below.
    """

    entity_id: str
    canonical_name: str
    similarity: float


@dataclass(frozen=True)
class GatedEntity:
    """Path-agnostic candidate carrying the fields the gate inspects.

    The IntelligenceHandler path may later switch to this dataclass
    once its tiebreaker logic is moved here; today only the orchestrator
    path constructs ``GatedEntity`` values from ``ResolvedEntity`` rows.
    """

    entity_id: str
    canonical_name: str
    similarity: float
    # Carried opaquely so the caller can re-emit the original object
    # (e.g. ``ResolvedEntity``) instead of re-constructing it. Avoids
    # leaking the ResolvedEntity type into this domain-free module.
    payload: object | None = None
    # Set by ``filter_resolver_candidates`` on REJECTED entries so the
    # caller can label Prometheus counters with a stable reason. Always
    # ``""`` on accepted entries.
    rejection_reason: str = ""
    # BP-661: exchange ticker for the candidate (e.g. "AAPL") when the
    # upstream resolver knows it. Used by the query-ticker tiebreak so a
    # query that literally contains the ticker can break a delta-ambiguous
    # tie (the "what is AAPL?" case: "AAPL Stock" noise twin at 0.95 vs
    # "Apple Inc." at 0.90 → delta gate used to reject BOTH).
    ticker: str | None = None
    # Set by ``filter_resolver_candidates`` on accepted entries that were
    # admitted via a tiebreak rule (e.g. ``"query_ticker_exact_match"``).
    # ``""`` for ordinary unambiguous accepts — lets the caller log/metric
    # tiebreak resolutions without changing the return shape.
    accepted_reason: str = ""


# Rejection reason labels — keep in sync with the Prometheus
# ``entity_resolver_ambiguous_total{reason}`` label set.
REASON_STOP_WORD_STRIP = "stop_word_strip"
REASON_LOW_TOP_SIMILARITY = "low_top_similarity"
REASON_DELTA_BELOW_THRESHOLD = "delta_below_threshold"
# SEC-FORM-001: candidate ticker is a bare fragment of a SEC-form designator
# present in the query ("10-K" → "K" → Kellanova) with no standalone mention.
REASON_SEC_FORM_FRAGMENT = "sec_form_fragment"
# C3 (da_apple_revenue "S" fix): candidate canonical/ticker is an implausibly
# short 1-2 char stub ("S" = SentinelOne/Sprint) that the query does NOT name
# as a standalone uppercase ticker. S6's alias-embedding search occasionally
# ranks such a stub at very high similarity (0.95) for an unrelated natural
# language query ("What was Apple's revenue…"); it then dominates the floor +
# delta gate, is surfaced to the LLM prompt as the resolved entity, and the
# model answers about "S" instead of Apple.
REASON_IMPLAUSIBLE_SHORT = "implausible_short_canonical"

# Acceptance reason label for tiebreak-admitted candidates (BP-661).
ACCEPTED_QUERY_TICKER_MATCH = "query_ticker_exact_match"

# Acceptance reason label for the BP-668 canonical-name tiebreak.
ACCEPTED_QUERY_NAME_MATCH = "query_name_exact_match"

# BP-661: shape gate for "is this string a stock ticker?". Uppercase 1-6
# letters/digits with an optional exchange-style suffix ("BRK.B", "RDS-A").
# Lowercase strings ("Apple") fail the gate and go to name resolution —
# tickers are conventionally written in caps and the LLM follows that
# convention when echoing user input. Shared by IntelligenceHandler and
# NarrativeHandler so both tool paths agree on what "looks like a ticker".
TICKER_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z0-9]{1,4})?$")

# InputValidator XML wrapper: `<Q_8hexchars>message</Q_8hexchars>` (step 5 of
# validate()). The orchestrator resolves entities on the VALIDATED message,
# so the gate must unwrap before tokenising — otherwise the trailing token is
# "aapl?</q_abc123>" and the query-ticker tiebreak silently never matches
# (the exact live failure observed on 2026-06-10 during BP-661 verification).
_Q_WRAPPER_RE = re.compile(r"^<Q_([0-9a-fA-F]+)>(?P<inner>.*)</Q_\1>$", re.DOTALL)


def strip_query_wrapper(query_text: str) -> str:
    """Remove the InputValidator ``<Q_token>...</Q_token>`` wrapper if present.

    Returns the inner message when the wrapper matches; the input unchanged
    otherwise. Safe to call on already-unwrapped text.
    """
    m = _Q_WRAPPER_RE.match(query_text.strip())
    return m.group("inner") if m else query_text


def _name_tokens(name: str) -> set[str]:
    """Tokenise a canonical name on non-alphanumeric boundaries (lowercased).

    Used by the BP-661 phantom-shape filter: noise duplicates created by the
    extraction pipeline almost always EMBED the ticker in their canonical name
    ("AAPL Stock", "NasdaqGS:AAPL", "AAPL.US") while real canonicals do not
    ("Apple Inc."). Splitting on non-alphanumerics catches all three shapes;
    the whitespace pass additionally keeps dotted class-share tickers
    ("BRK.B Stock") intact so they too are recognised as ticker-derived.
    """
    lowered = name.lower()
    tokens = {t for t in re.split(r"[^a-z0-9]+", lowered) if t}
    tokens |= {t.strip(".,!?:;'\"()[]") for t in lowered.split()}
    return tokens


# BP-668: separators that delimit ticker-shaped tokens inside the raw query.
# Whitespace plus common punctuation that touches a ticker ("(AAPL,", "AAPL/MSFT").
# Hyphens and dots are NOT separators — they are part of legitimate ticker
# shapes ("BTC-USD", "BRK.B"); edge punctuation is stripped per-token below.
_QUERY_TOKEN_SPLIT_RE = re.compile(r"[\s,;:/\\()\[\]{}<>!?\"]+")

# BP-668: common English words (lowercase) that collide with real exchange
# tickers. A LOWERCASE query token in this set is never ticker evidence —
# these are the words that hijacked live resolutions ("right now" → NOW →
# ServiceNow; "news on Apple" → ON → ON Semiconductor; "does it" → IT →
# Gartner). UPPERCASE tokens bypass this list entirely: a user who types
# "what is NOW trading at?" means the ticker. Over-list freely — a word here
# only disables the lowercase CONVENIENCE match ("what is aapl?"); it never
# blocks explicit-caps queries.
_COMMON_WORD_TICKER_BLOCKLIST: frozenset[str] = frozenset(
    {
        # determiners / pronouns / prepositions / conjunctions
        "a", "an", "i", "it", "its", "in", "on", "at", "by", "of", "or", "and", "the",
        "to", "for", "so", "no", "not", "but", "if", "as", "be", "been", "am", "is",
        "are", "was", "has", "had", "he", "she", "we", "us", "you", "me", "my", "do",
        "does", "did", "out", "over", "per", "up", "with", "than", "that", "this",
        "all", "any", "some", "who", "why", "how", "when", "what", "will", "can",
        # frequent verbs / adjectives / nouns in finance questions
        "now", "new", "next", "news", "big", "get", "go", "good", "best", "worst",
        "just", "like", "love", "low", "high", "make", "many", "more", "most",
        "much", "own", "right", "run", "say", "see", "set", "show", "tell", "time",
        "top", "two", "one", "use", "very", "well", "year", "today", "main", "real",
        "fast", "nice", "play", "open", "life", "work", "home", "key", "true",
        # finance vocabulary that collides with ticker shapes
        "stock", "price", "buy", "sell", "hold", "long", "short", "call", "put",
        "cash", "gold", "oil", "gas", "fund", "bank", "tech", "car", "cars",
        "ev", "ai", "ipo", "etf", "ceo", "cfo", "eps", "pe", "usd", "eur", "gbp",
    }
)  # fmt: skip


# BP-661 P/E→Pandora fix (2026-06-12): financial-ratio acronyms + their
# single-letter fragments that the LLM and users write in UPPERCASE inside a
# question ("AAPL's P/E ratio", "EPS", "ROE"). Unlike the lowercase
# ``_COMMON_WORD_TICKER_BLOCKLIST``, these must be excluded EVEN WHEN
# UPPERCASE because that is how they are conventionally written — and the
# uppercase acceptance tier (tier 1 below) would otherwise treat the bare "P"
# split out of "P/E" as an exact ticker match for Pandora (ticker "P"),
# overriding the LLM's correct entity. Live failure: ``da_aapl_pe_dec2024``
# ("What was AAPL's P/E ratio as of December 31, 2024?") resolved to
# "Pandora (ticker: P)". The set covers the common ratio acronyms and the
# bare letters that "P/E", "P/B", "P/S", "D/E" decompose into after the
# slash split.
_FINANCIAL_ACRONYM_BLOCKLIST: frozenset[str] = frozenset(
    {
        # bare single-letter fragments of slash ratios (P/E, P/B, P/S, D/E, …)
        "p", "e", "b", "s", "d",
        # whole financial-ratio acronyms
        "pe", "peg", "pb", "ps", "eps", "roe", "roa", "roi", "roic", "ebit",
        "ebitda", "fcf", "wacc", "capex", "opex", "ttm", "yoy", "qoq", "mom",
        "de", "ev",
    }
)  # fmt: skip

# ── SEC-form designator guard (SEC-FORM-001) ──────────────────────────────────
# SEC filing form designators ("10-K", "10-Q", "8-K", "S-1", "20-F", "6-K", …)
# are NOT tickers/entities — but they decompose into short all-caps fragments
# ("K", "Q", "F", "S") that collide with real single-letter tickers. The live
# failure: "what's in Apple's latest 10-K" resolved the "K" fragment to
# Kellanova (ticker "K"), routing the whole turn to the wrong company. This is
# the same class as the R1 extraction "ticker class-blind" family — a short
# all-caps token matched as a ticker without checking its surrounding context.
#
# Guard strategy (scoped to form context, mirrors the extraction denylist
# pattern): when the query contains a SEC-form designator, the bare fragment
# letters that form decomposes into ("10-K" → "K") are removed from ticker
# evidence AND any resolved candidate whose ticker IS that fragment is rejected
# — UNLESS the same fragment also appears standalone elsewhere in the query
# (outside the form), in which case the user plausibly means the real ticker
# ("how is K doing after its 10-K?") and it still resolves.
#
# ``_SEC_FORM_RE`` matches whole-token form designators case-insensitively. The
# hyphen forms are matched with an optional hyphen so "10K"/"10-K" both hit;
# a leading/trailing alphanumeric boundary prevents matching inside longer
# tokens ("A10-KB" is not a form).
_SEC_FORM_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"10-?[KQ](?:/A)?"  # 10-K, 10-Q, 10-K/A, 10-Q/A
    r"|8-?K(?:/A)?"  # 8-K, 8-K/A
    r"|6-?K|11-?K"  # 6-K, 11-K
    r"|20-?F|40-?F"  # 20-F, 40-F
    r"|S-?(?:1|3|4|8|11)(?:/A)?"  # S-1, S-3, S-4, S-8, S-11
    r"|F-?(?:1|3|4|6|10)(?:/A)?"  # F-1, F-3, F-6, F-10
    r"|DEF\s?14A|DEFA14A|DEFM14A|DEFR14A|PREM?\s?14A"  # proxy statements
    r"|424B[0-9]"  # 424B1..424B8 prospectus
    r"|13[FDG](?:-HR)?"  # 13F, 13D, 13G, 13F-HR
    r"|SC\s?13[DG](?:/A)?"  # SC 13D, SC 13G, SC 13D/A
    r"|N-?(?:1A|CSR|Q|PORT|MFP)"  # fund forms
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def is_sec_form_designator(token: str) -> bool:
    """True when ``token`` is exactly a SEC filing form designator.

    Used by the tool-argument resolver paths (IntelligenceHandler /
    NarrativeHandler) to refuse resolving a literal form name the LLM
    mistakenly passed as an ``entity_name``/``entity_id`` (e.g. the LLM echoes
    "10-K" into a tool argument). Matches the whole string only.
    """
    t = token.strip()
    if not t:
        return False
    m = _SEC_FORM_RE.match(t)
    return m is not None and m.end() == len(t)


def _sec_form_reject_tickers(query_text: str | None) -> frozenset[str]:
    """Uppercase fragment tickers that appear ONLY inside SEC-form designators.

    For each SEC-form designator found in the query, derive its short all-caps
    alpha fragments ("10-K" → {"K"}, "S-1" → {"S"}, "20-F" → {"F"}, "SC 13D" →
    {"SC"}). A fragment is returned ONLY when it does NOT also appear as a
    standalone token elsewhere in the query (the form spans removed) — so a
    query that BOTH names the form AND the real ticker ("how is K after the
    10-K?") does not suppress the genuine ticker.

    Returns an empty set when the query carries no SEC-form context, so the
    guard is a no-op for ordinary ticker queries.
    """
    if not query_text:
        return frozenset()
    text = strip_query_wrapper(query_text)
    frags: set[str] = set()
    for m in _SEC_FORM_RE.finditer(text):
        span = m.group(0).upper()
        for piece in re.split(r"[^A-Z0-9]+", span):
            # Short pure-alpha fragments are the ones that collide with real
            # single/two-letter tickers ("K", "F", "SC"). Longer alpha pieces
            # ("DEF") are form keywords, not ticker-shaped fragments we worry
            # about here; numeric pieces ("10", "424B3") never resolve.
            if piece.isalpha() and 1 <= len(piece) <= 2:
                frags.add(piece)
    if not frags:
        return frozenset()
    # Standalone occurrences: strip the form spans, then collect bare tokens.
    without_forms = _SEC_FORM_RE.sub(" ", text)
    standalone = {tok.strip(".,!?:;'\"()[]").upper() for tok in without_forms.split()}
    return frozenset(f for f in frags if f not in standalone)


# A standalone single UPPERCASE letter is almost never strong ticker evidence
# in prose ("AAPL's P/E", "earnings per share, or E"). Real single-letter
# tickers (Ford "F", AT&T "T", Sprint "S") DO exist but a one-letter token in
# a sentence is too ambiguous to win a tiebreak — the user who means the
# ticker can disambiguate with the company name, whereas the false-positive
# (P/E → Pandora) silently misroutes the whole answer. We therefore drop
# bare single-letter tokens from ticker evidence entirely.
_MIN_TICKER_EVIDENCE_LEN = 2

# C3: a canonical name (or ticker) shorter than this is treated as an
# implausibly-short stub unless the query explicitly names it as a standalone
# uppercase ticker. 3 → "S", "Q", "IT"(as a name) are stubs; "IBM", "Ford"
# survive. Deliberately keyed on the CANONICAL NAME length, not the ticker:
# a long canonical with a short ticker ("Ford Motor Company" / "F") is a real
# entity and must not be caught.
_MIN_CANONICAL_NAME_LEN = 3


def _query_standalone_upper_tokens(query_text: str | None) -> frozenset[str]:
    """Standalone ALL-UPPERCASE ticker-shaped tokens written verbatim in the query.

    Unlike ``_query_ticker_tokens`` this KEEPS single-letter tokens — the whole
    point of the C3 short-stub guard is to let a user who explicitly writes the
    one-letter ticker ("how is S doing after earnings?") still resolve it, while
    a natural-language query that merely happens to embed the letter elsewhere
    ("What was Apple's revenue…") does not. Case-sensitive on purpose: only
    explicit caps count as intent for a one/two-letter ticker.
    """
    if not query_text:
        return frozenset()
    unwrapped = strip_query_wrapper(query_text)
    out: set[str] = set()
    for raw in _QUERY_TOKEN_SPLIT_RE.split(unwrapped):
        tok = raw.strip(".,!?:;'\"()[]")
        if tok and tok.isupper() and TICKER_SHAPE_RE.fullmatch(tok):
            out.add(tok)
    return frozenset(out)


def _query_ticker_tokens(query_text: str) -> set[str]:
    """Extract ticker-evidence tokens from the user's query.

    BP-668 (2026-06-11): the original BP-661 tiebreak lowercased the whole
    query and matched candidate tickers case-insensitively. Common English
    words that happen to be tickers then hijacked resolution:

      * "What is BTC-USD trading at right **now**?"  → NOW  → ServiceNow Inc
      * "What's the latest news **on** Apple Inc.?"  → ON   → ON Semiconductor
      * "...how does **it** compare?"                → IT   → Gartner Inc

    BP-661 P/E→Pandora (2026-06-12): financial-ratio fragments written in
    UPPERCASE ("P/E", "EPS", "ROE") used to slip through the uppercase tier
    and steal the resolution ("P" → Pandora). We now (a) drop bare
    single-letter tokens entirely and (b) reject known financial-acronym
    fragments REGARDLESS of case via ``_FINANCIAL_ACRONYM_BLOCKLIST``.

    Two acceptance tiers (per token, edge punctuation stripped):

      1. UPPERCASE ticker-shaped tokens (``TICKER_SHAPE_RE``) count — explicit
         caps is explicit intent ("what is NOW trading at?" means the ticker
         NOW) — UNLESS the token is a single letter or a financial-acronym
         fragment (P/E, EPS, ROE, …).
      2. lowercase/mixed-case tokens whose UPPERCASED form is ticker-shaped
         count ONLY when the lowercased token is not a common English word
         (``_COMMON_WORD_TICKER_BLOCKLIST``) nor a financial acronym. This
         preserves the lowercase convenience match ("what is aapl?") without
         letting prose words steal the resolution.

    Returns matching tokens lowercased (candidate tickers are compared
    lowercase downstream).
    """
    unwrapped = strip_query_wrapper(query_text)
    # SEC-FORM-001: fragments contributed only by SEC-form designators
    # ("10-K" → "K", "SC 13D" → "SC") are never ticker evidence. Single-letter
    # fragments are already dropped by _MIN_TICKER_EVIDENCE_LEN below; this also
    # covers the two-letter case ("SC") that would otherwise pass.
    _form_frags = {f.lower() for f in _sec_form_reject_tickers(query_text)}
    tokens: set[str] = set()
    for raw in _QUERY_TOKEN_SPLIT_RE.split(unwrapped):
        tok = raw.strip(".,!?:;'\"()[]")
        if not tok:
            continue
        lowered = tok.lower()
        if lowered in _form_frags:
            continue
        # BP-661 P/E→Pandora: drop single-letter fragments + financial acronyms
        # before EITHER acceptance tier, so even an UPPERCASE "P" (split out of
        # "P/E") never counts as ticker evidence.
        if len(tok) < _MIN_TICKER_EVIDENCE_LEN or lowered in _FINANCIAL_ACRONYM_BLOCKLIST:
            continue
        if TICKER_SHAPE_RE.fullmatch(tok):
            tokens.add(lowered)
            continue
        if lowered not in _COMMON_WORD_TICKER_BLOCKLIST and TICKER_SHAPE_RE.fullmatch(tok.upper()):
            tokens.add(lowered)
    return tokens


def _is_phantom_shaped(candidate: GatedEntity) -> bool:
    """True when the candidate looks like a BP-459 phantom twin.

    Phantom duplicates EMBED the ticker in a longer canonical name
    ("AAPL Stock", "NasdaqGS:AAPL", "AAPL.US"). A canonical whose name IS
    the ticker verbatim (crypto/FX pairs such as "BTC-USD", index symbols)
    is NOT phantom-shaped — for those instruments the ticker is the only
    sensible name, and penalising them caused the BP-668 BTC-USD failure
    (the real "BTC-USD" canonical lost the tiebreak to ServiceNow).
    """
    if candidate.ticker is None:
        return False
    ticker_l = candidate.ticker.strip().lower()
    name_l = candidate.canonical_name.strip().lower()
    if name_l == ticker_l:
        return False  # name IS the ticker (crypto pair / FX / index) — real canonical
    return ticker_l in _name_tokens(candidate.canonical_name)


def _query_name_tiebreak(
    survivors: list[GatedEntity],
    query_text: str | None,
) -> GatedEntity | None:
    """BP-668: break a delta-ambiguous tie via a verbatim canonical-name match.

    "What's the latest news on Apple Inc.?" carries the candidate's EXACT
    canonical name ("Apple Inc.") — far stronger evidence than the embedding
    similarity spread. Live failure: ON Semiconductor Corp. (0.95) vs Apple
    Inc. (0.90) sat inside the delta window; with no ticker token in the
    query the gate rejected BOTH and the turn lost its entity anchor
    (generic suggestions, no BP-605 grounding).

    Rules:
      * A candidate matches when its canonical_name appears in the query
        case-insensitively on word boundaries (substring with non-alnum or
        string-edge on both sides).
      * Names shorter than 4 chars or single words in the common-word
        blocklist never match (a hypothetical entity literally named "Now"
        must not re-introduce the BP-668 hijack).
      * If candidates with MORE THAN ONE distinct name match, the query
        names several entities — that is genuine ambiguity; fall through.
      * Highest similarity wins among same-name matches (duplicate
        canonical rows share the name).
    """
    if not query_text:
        return None
    query_lower = re.sub(r"\s+", " ", strip_query_wrapper(query_text).lower())

    def _name_in_query(name: str) -> bool:
        needle = re.sub(r"\s+", " ", name.strip().lower())
        if len(needle) < 4:
            return False
        if " " not in needle and needle in _COMMON_WORD_TICKER_BLOCKLIST:
            return False
        idx = query_lower.find(needle)
        while idx != -1:
            left_ok = idx == 0 or not query_lower[idx - 1].isalnum()
            right = idx + len(needle)
            right_ok = right == len(query_lower) or not query_lower[right].isalnum()
            if left_ok and right_ok:
                return True
            idx = query_lower.find(needle, idx + 1)
        return False

    matches = [c for c in survivors if _name_in_query(c.canonical_name)]
    if not matches:
        return None
    distinct_names = {re.sub(r"\s+", " ", c.canonical_name.strip().lower()) for c in matches}
    if len(distinct_names) > 1:
        return None  # query names several entities — genuinely ambiguous
    return max(matches, key=lambda c: c.similarity)


def _query_ticker_tiebreak(
    survivors: list[GatedEntity],
    query_text: str | None,
) -> GatedEntity | None:
    """BP-661: break a delta-ambiguous tie via an exact query-token ↔ ticker match.

    When the user's query literally contains a candidate's exchange ticker as
    a standalone UPPERCASE token (e.g. "what is AAPL?"), that is a strong,
    unambiguous signal which canonical the user means — far stronger than the
    embedding similarity spread the delta gate inspects.

    Selection rules (in order):
      1. Keep only survivors whose ``ticker`` appears as a ticker-evidence
         token in the query (BP-668: UPPERCASE always counts; lowercase
         counts only for non-English-word tokens — prose words like
         "now"/"on"/"it" are NOT ticker evidence; "aapl" still is).
      2. Among those, prefer candidates that are not phantom-shaped
         (BP-459 twins like "AAPL Stock" / "AAPL.US") — but a canonical
         whose name IS the ticker (crypto pairs: "BTC-USD") stays eligible.
      3. Highest similarity wins among the remaining pool (deterministic).

    Returns the winning candidate, or ``None`` when no ticker matches the
    query (caller falls through to the legacy reject-all-ambiguous path).
    """
    if not query_text:
        return None
    query_tokens = _query_ticker_tokens(query_text)
    if not query_tokens:
        return None
    matches = [c for c in survivors if c.ticker and c.ticker.strip().lower() in query_tokens]
    if not matches:
        return None
    clean = [c for c in matches if not _is_phantom_shaped(c)]
    pool = clean or matches
    return max(pool, key=lambda c: c.similarity)


def strip_stop_words(query: str, stop_words: frozenset[str]) -> str:
    """Return ``query`` with all-stop-word tokens removed (lowercased).

    Mirrors ``IntelligenceHandler._strip_stop_words`` byte-for-byte so
    the two paths agree on what counts as "no entity-shaped signal".

    Tokenises on whitespace and strips a small set of trailing
    punctuation so ``"AI semiconductor space."`` also matches.
    Returns the empty string when EVERY token is a stop word — the
    caller treats that as a resolver refusal.
    """
    if not query:
        return ""
    tokens = query.lower().split()
    kept = [t for t in tokens if t.strip(".,!?:;'\"()[]") not in stop_words]
    return " ".join(kept)


def filter_resolver_candidates(
    candidates: list[GatedEntity],
    *,
    config: ResolverGateConfig,
    query_text: str | None = None,
) -> tuple[list[GatedEntity], list[GatedEntity]]:
    """Apply 0.75 absolute floor + 0.15 delta gate (+ BP-661 ticker tiebreak).

    Returns ``(accepted, rejected)``. Every rejected entry carries a
    ``rejection_reason`` label so callers can emit per-cause metrics.

    Semantics
    ---------
    * **stop_word_strip** — set by the *caller* before invoking this
      function (the strip happens on the query text, not on
      candidates). Wired here as a symbolic constant so callers stay
      consistent.

    * **low_top_similarity** — candidate's ``similarity`` is strictly
      below ``config.top_similarity_min``. Applied per-candidate, not
      just to the top-1 row, because the orchestrator path emits ALL
      resolved entities to the prompt (not a single winner).

    * **delta_below_threshold** — when 2+ candidates pass the floor
      and the top-1/top-2 gap is below ``config.delta_min`` the
      whole result set is ambiguous; we reject everything. Matches
      the IntelligenceHandler bail-on-ambiguity behaviour and avoids
      surfacing two near-equal-similarity candidates as if they were
      both confident matches.

    * **query_ticker_exact_match (BP-661)** — BEFORE the delta gate
      rejects everything, when ``query_text`` is supplied and exactly
      one best candidate's ticker appears verbatim as a query token,
      that candidate is accepted (others rejected with the delta
      reason). This rescues ticker-only queries like "what is AAPL?"
      where a BP-459 phantom twin ("AAPL Stock") and the real canonical
      ("Apple Inc.") sit within the delta window and the gate would
      otherwise refuse to resolve anything.
    """
    if not candidates:
        return [], []

    accepted: list[GatedEntity] = []
    rejected: list[GatedEntity] = []

    # ── SEC-FORM-001 pass: drop candidates that are bare SEC-form fragments ──
    # "Apple's latest 10-K" must not resolve the "K" fragment to Kellanova
    # (ticker "K"). Runs BEFORE the floor pass because such a candidate can sit
    # well above the 0.75 floor (S6 returns it as a high-confidence ticker hit).
    # Scoped to form context: ``_sec_form_reject_tickers`` only returns
    # fragments that appear SOLELY inside a form designator, so a genuine
    # standalone "K" ("how is K after its 10-K?") still resolves.
    _form_reject = _sec_form_reject_tickers(query_text)
    if _form_reject:
        surviving: list[GatedEntity] = []
        for c in candidates:
            c_ticker = (c.ticker or "").strip().upper()
            if c_ticker and c_ticker in _form_reject:
                rejected.append(
                    GatedEntity(
                        entity_id=c.entity_id,
                        canonical_name=c.canonical_name,
                        similarity=c.similarity,
                        payload=c.payload,
                        rejection_reason=REASON_SEC_FORM_FRAGMENT,
                        ticker=c.ticker,
                    )
                )
            else:
                surviving.append(c)
        candidates = surviving
        if not candidates:
            return [], rejected

    # ── C3 pass: drop implausibly-short canonical stubs ─────────────────────
    # A 1-2 char canonical ("S" = SentinelOne/Sprint) surfaced for a
    # natural-language query ("What was Apple's revenue…") misroutes the whole
    # answer. Reject any candidate whose canonical name is shorter than
    # ``_MIN_CANONICAL_NAME_LEN`` UNLESS the query names that stub verbatim as a
    # standalone uppercase ticker ("how is S doing?"). Runs BEFORE the floor
    # pass because the stub usually sits well above the 0.75 floor (S6 returns
    # it as a high-confidence alias hit).
    _upper_tokens = _query_standalone_upper_tokens(query_text)
    surviving_short: list[GatedEntity] = []
    for c in candidates:
        name_stripped = c.canonical_name.strip()
        tkr_stripped = (c.ticker or "").strip()
        # "Named verbatim" = the stub's own text (name or its short ticker)
        # appears as a standalone uppercase token in the query.
        named = name_stripped.upper() in _upper_tokens or (bool(tkr_stripped) and tkr_stripped.upper() in _upper_tokens)
        if len(name_stripped) < _MIN_CANONICAL_NAME_LEN and not named:
            rejected.append(
                GatedEntity(
                    entity_id=c.entity_id,
                    canonical_name=c.canonical_name,
                    similarity=c.similarity,
                    payload=c.payload,
                    rejection_reason=REASON_IMPLAUSIBLE_SHORT,
                    ticker=c.ticker,
                )
            )
        else:
            surviving_short.append(c)
    candidates = surviving_short
    if not candidates:
        return [], rejected

    # ── Floor pass: drop any candidate below the absolute threshold ──
    for c in candidates:
        if c.similarity < config.top_similarity_min:
            rejected.append(
                # Re-emit with the rejection reason populated. Frozen
                # dataclass → replace via dataclasses.replace would
                # require importing dataclasses; cheaper to build new.
                GatedEntity(
                    entity_id=c.entity_id,
                    canonical_name=c.canonical_name,
                    similarity=c.similarity,
                    payload=c.payload,
                    rejection_reason=REASON_LOW_TOP_SIMILARITY,
                )
            )
        else:
            accepted.append(c)

    # ── Delta pass: top-1 vs top-2 gap on the survivors ─────────────
    # Only fires when at least two candidates survived the floor —
    # otherwise the gate is trivially unambiguous.
    if len(accepted) >= 2:
        # Survivors are not necessarily ordered; sort DESC by similarity
        # to inspect the real top-1/top-2.
        accepted_sorted = sorted(accepted, key=lambda x: x.similarity, reverse=True)
        top, second = accepted_sorted[0], accepted_sorted[1]
        if (top.similarity - second.similarity) < config.delta_min:
            # ── BP-668: verbatim canonical-name tiebreak first ───────────
            # "latest news on Apple Inc.?" names the candidate exactly —
            # the strongest evidence available; see _query_name_tiebreak.
            winner = _query_name_tiebreak(accepted_sorted, query_text)
            accepted_reason = ACCEPTED_QUERY_NAME_MATCH
            if winner is None:
                # ── BP-661: query-ticker tiebreak before the ambiguous bail ──
                # When the user's query literally names a candidate's ticker
                # ("what is AAPL?"), resolve to that candidate instead of
                # refusing — see _query_ticker_tiebreak for the full rules.
                winner = _query_ticker_tiebreak(accepted_sorted, query_text)
                accepted_reason = ACCEPTED_QUERY_TICKER_MATCH
            if winner is not None:
                losers = [c for c in accepted_sorted if c.entity_id != winner.entity_id]
                for c in losers:
                    rejected.append(
                        GatedEntity(
                            entity_id=c.entity_id,
                            canonical_name=c.canonical_name,
                            similarity=c.similarity,
                            payload=c.payload,
                            rejection_reason=REASON_DELTA_BELOW_THRESHOLD,
                            ticker=c.ticker,
                        )
                    )
                return [
                    GatedEntity(
                        entity_id=winner.entity_id,
                        canonical_name=winner.canonical_name,
                        similarity=winner.similarity,
                        payload=winner.payload,
                        ticker=winner.ticker,
                        accepted_reason=accepted_reason,
                    )
                ], rejected
            # Ambiguous — reject EVERY survivor with delta reason. The
            # orchestrator path treats this as "no confident entity"
            # and proceeds without an entity map (the symmetric
            # behaviour to IntelligenceHandler returning None).
            for c in accepted_sorted:
                rejected.append(
                    GatedEntity(
                        entity_id=c.entity_id,
                        canonical_name=c.canonical_name,
                        similarity=c.similarity,
                        payload=c.payload,
                        rejection_reason=REASON_DELTA_BELOW_THRESHOLD,
                        ticker=c.ticker,
                    )
                )
            return [], rejected

    return accepted, rejected


__all__ = [
    "ACCEPTED_QUERY_NAME_MATCH",
    "ACCEPTED_QUERY_TICKER_MATCH",
    "REASON_DELTA_BELOW_THRESHOLD",
    "REASON_IMPLAUSIBLE_SHORT",
    "REASON_LOW_TOP_SIMILARITY",
    "REASON_SEC_FORM_FRAGMENT",
    "REASON_STOP_WORD_STRIP",
    "TICKER_SHAPE_RE",
    "GatedEntity",
    "ResolverGateConfig",
    "filter_resolver_candidates",
    "is_sec_form_designator",
    "strip_query_wrapper",
    "strip_stop_words",
]
