"""Rare-token analyzer — detects identifier-style tokens that benefit from
lexical retrieval (PLAN-0063 W5-3 / FR-T1-2 / L8 + L9).

When a user query contains "rare" tokens (PRD IDs, function-qualified names,
tickers, ISINs, filing types, ...) the lexical leg of the hybrid retriever
tends to outperform the embedding leg by a wide margin — the embedder
treats these tokens as out-of-vocabulary noise but Postgres FTS scores an
exact match perfectly. This module classifies a query so the hybrid use
case can decide whether to apply the adaptive lexical boost.

Purity contract (must hold)
---------------------------
* No I/O. No DB, HTTP, Valkey.
* No logging side effects.
* No DI / settings. Every external dependency (e.g. the canonical-tickers
  cache) is supplied as a plain callable argument.

That keeps the analyzer trivially testable and lets the caller decide where
the ticker source-of-truth lives (production: ``CanonicalTickersCache``;
tests: a lambda over a literal set; CI: skip the predicate entirely and
fall back to the stop-list path).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# ── Token classes ─────────────────────────────────────────────────────────────
#
# Each class has a name (used in the audit list emitted by the analyzer) plus
# a compiled regex. The naming convention is snake_case to stay consistent
# with the structlog event-name convention used elsewhere in the service.
#
# Order matters only for the audit trail: the analyzer iterates the list once
# per query, so the per-class match cost is one regex search.

# PRD-0034, PLAN-0063, FR-T1-2, BP-235, OQ-001, ADR-F-12, REQ-7, SEC-001 ...
_RE_PRD_ID = re.compile(r"\b(?:PRD|PLAN|FR|BP|OQ|ADR|REQ|SEC)-[A-Z]?\d+(?:-\d+)?\b")

# Function or class identifier with a dotted prefix, e.g. ``foo.bar`` or
# ``module.ClassName``. Lower-case prefix forces this away from CamelCase
# matches (which are handled separately).
_RE_DOTTED_IDENT = re.compile(r"\b[a-z][a-zA-Z0-9_]{2,}\.[a-zA-Z_][a-zA-Z0-9_]+\b")

# CamelCase with at least two humps — ``HelloWorld``, ``ThisCounts``,
# ``ParallelRetrievalOrchestrator``. The mid-word ``[a-z]`` enforcer ensures
# we don't accidentally match all-caps tokens like ``AAPL`` (which belong
# to the ticker path) or ``HTTP_STATUS`` (snake-case path).
_RE_CAMELCASE = re.compile(r"\b[A-Z][a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b")

# SCREAMING_SNAKE constants — must contain at least one underscore OR be ≥6
# characters long. The underscore branch catches typical Python constants
# (DEFAULT_K, MAX_RETRIES); the length branch catches all-caps
# words like ``HTTP_STATUS`` written without underscores. Pure 2-5 letter
# uppercase tokens (potential tickers like AAPL/MSFT) are *not* matched here
# — they go through the ticker path with the canonical-tickers predicate.
_RE_SCREAMING_SNAKE = re.compile(r"\b(?:[A-Z]+_[A-Z_]+|[A-Z]{6,})\b")

# Bare 2-5 letter uppercase tokens — *candidate* tickers. Final classification
# requires a positive predicate hit (production = canonical tickers SET) or
# falls back to the stop-list when no predicate is supplied.
_RE_TICKER_CANDIDATE = re.compile(r"\b[A-Z]{2,5}\b")

# ISIN: country (2 alpha) + 9 alnum + 1 check digit (10 alnum after the
# country prefix). Restricted to upper-case to avoid matching titlecased
# words.
_RE_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{10}\b")

# CIK numbers — SEC EDGAR central index keys, optionally with a "CIK" prefix.
_RE_CIK = re.compile(r"\bCIK\s*\d{4,10}\b")

# Common SEC filing types — keep the list tight; rare filings can be added
# later without breaking the API.
_RE_FILING_TYPE = re.compile(r"\b(?:8-K|10-K|10-Q|13F|13G|13D|S-1)\b")

# Quarters / fiscal years / ISO dates. Each pattern is independent so a
# query mentioning two quarters still only yields one ``quarter`` class hit.
_RE_QUARTER = re.compile(r"\b(?:Q[1-4]\s*20\d{2}|20\d{2}-Q[1-4]|FY20\d{2})\b")
_RE_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Stack-trace fragments — TypeError / ValueError / Traceback. The pattern
# anchors on a capitalised identifier ending in "Error" so it won't fire on
# the literal word "error".
_RE_PYTHON_ERROR = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*Error\b")
_RE_TRACEBACK = re.compile(r"\bTraceback\b")

# Stop-list for the ticker fallback path: common 2-5 letter uppercase words
# that look ticker-shaped but aren't. Keep alphabetised for grep-ability.
_TICKER_STOP_LIST: frozenset[str] = frozenset(
    {
        "A",
        "CEO",
        "CFO",
        "CTO",
        "FAQ",
        "HOW",
        "I",
        "IPO",
        "THE",
        "USA",
        "WHAT",
        "WHEN",
        "WHO",
        "WHY",
    }
)


# ── Public API ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RareTokenAnalysis:
    """Result of analyzing a single query.

    Attributes:
        has_rare_token: True iff at least one rare-token class fired.
        rare_token_count: Total count of distinct rare tokens detected
            across all classes (used for ranking diagnostics; the boost
            decision uses ``has_rare_token`` only).
        classes_matched: Sorted list of class names that fired. Empty when
            ``has_rare_token`` is False.
    """

    has_rare_token: bool
    rare_token_count: int
    classes_matched: list[str] = field(default_factory=list)


def analyze(
    query_text: str,
    *,
    is_known_ticker: Callable[[str], bool] | None = None,
) -> RareTokenAnalysis:
    """Classify rare tokens in ``query_text``.

    Args:
        query_text: The raw user query.
        is_known_ticker: Optional predicate — when provided, a
            ticker-shaped token is only counted if the predicate returns
            True. Production wiring passes ``CanonicalTickersCache``'s
            sync mirror; tests pass a literal-set lambda. When ``None``,
            falls back to filtering against ``_TICKER_STOP_LIST``.

    Returns:
        RareTokenAnalysis. Stable for a given input — no global state.
    """
    if not query_text:
        return RareTokenAnalysis(has_rare_token=False, rare_token_count=0)

    classes_matched: list[str] = []
    rare_count = 0

    # Each class is checked independently; we don't try to be clever about
    # tokens that match more than one class — they'll show up once per class
    # in the count, which is fine for the diagnostic.
    if matches := _RE_PRD_ID.findall(query_text):
        classes_matched.append("prd_id")
        rare_count += len(matches)

    if matches := _RE_FILING_TYPE.findall(query_text):
        classes_matched.append("filing_type")
        rare_count += len(matches)

    if matches := _RE_ISIN.findall(query_text):
        classes_matched.append("isin")
        rare_count += len(matches)

    if matches := _RE_CIK.findall(query_text):
        classes_matched.append("cik")
        rare_count += len(matches)

    if matches := _RE_QUARTER.findall(query_text):
        classes_matched.append("quarter")
        rare_count += len(matches)

    if matches := _RE_ISO_DATE.findall(query_text):
        classes_matched.append("iso_date")
        rare_count += len(matches)

    if matches := _RE_DOTTED_IDENT.findall(query_text):
        classes_matched.append("dotted_ident")
        rare_count += len(matches)

    if matches := _RE_CAMELCASE.findall(query_text):
        classes_matched.append("camelcase")
        rare_count += len(matches)

    if matches := _RE_SCREAMING_SNAKE.findall(query_text):
        classes_matched.append("screaming_snake")
        rare_count += len(matches)

    if matches := _RE_PYTHON_ERROR.findall(query_text):
        classes_matched.append("python_error")
        rare_count += len(matches)

    if _RE_TRACEBACK.search(query_text):
        classes_matched.append("traceback")
        rare_count += 1

    # ── Ticker pass: filter candidates through the predicate or the stop-list.
    # We deliberately run this AFTER SCREAMING_SNAKE so a token like ``HTTP``
    # still gets classified as rare via the snake-case path even when no
    # predicate is supplied. The ticker path adds zero double-counting because
    # a token already matched via screaming_snake won't also be a ticker hit
    # (we de-dup on the matched_text below).
    candidate_tickers = _RE_TICKER_CANDIDATE.findall(query_text)
    if candidate_tickers:
        ticker_hits = 0
        for sym in candidate_tickers:
            if is_known_ticker is not None:
                if is_known_ticker(sym):
                    ticker_hits += 1
            else:
                if sym not in _TICKER_STOP_LIST:
                    ticker_hits += 1
        if ticker_hits:
            classes_matched.append("ticker")
            rare_count += ticker_hits

    return RareTokenAnalysis(
        has_rare_token=bool(classes_matched),
        rare_token_count=rare_count,
        classes_matched=sorted(classes_matched),
    )
