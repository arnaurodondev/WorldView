"""Deterministic event-type VALUE signal for the deep-extraction gate.

Ref: docs/audits/2026-07-17-article-backlog-lever.md (follow-up).

WHY THIS EXISTS
===============
The backlog-drain lever (``apply_deep_extraction_value_gate`` in ``suppression.py``)
downgrades ``FULL_PIPELINE`` → ``SECTION_EMBEDDINGS_ONLY`` when a doc's composite
routing score is below the floor. That composite score is dominated by
``entity_density`` (org/FI mention count / 15) — it is a DENSITY proxy, NOT a VALUE
proxy. A *focused single-company* financial event (a Q1 earnings miss, an M&A / stake
disclosure, an analyst rating action, a material contract award) mentions only a
handful of organisations, so it scores in the low ``[0.35, 0.45)`` band and gets gated
OUT of KG extraction — despite being exactly the kind of fact a finance KG should
capture (observed on prod: PulteGroup Q1 miss, Nebius stake disclosure, a $186M Army
contract).

THE SIGNAL
==========
A cheap, deterministic pattern match over the *title + early body* that answers a
single question: does this doc report a substantive financial EVENT? It adds NO extra
LLM call — it is pure regex over text the pipeline already has in memory. When it
fires, the gate is instructed to keep the doc on ``FULL_PIPELINE`` regardless of the
(low) density score, so real earnings/M&A/analyst/contract news is never gated out.

It is deliberately CONSERVATIVE about the opposite failure — it must NOT fire on
genuinely thin docs (promos, "10 stocks to buy now" listicles, market-colour
round-ups). The patterns therefore require event-specific phrasing (e.g. ``buy
rating`` / ``rated buy`` rather than a bare "buy"; ``to acquire`` / ``agrees to buy``
rather than a bare "to buy") so the common listicle vocabulary does NOT trip it.

The category set + minimum-hit threshold + scan window are all config/env-driven so
the signal can be tuned or disabled per environment without a rebuild.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "ALL_EVENT_CATEGORIES",
    "detect_event_categories",
    "has_high_value_event",
]

# ── Event-type pattern catalogue ─────────────────────────────────────────────
#
# Each category maps to a list of case-insensitive regexes. A category is
# considered PRESENT if ANY of its patterns matches the scanned text. Patterns
# use word boundaries and event-specific phrasing to keep listicle/promo
# vocabulary from matching (see module docstring).
#
# Versioned in code (NOT env) on purpose: regexes shipped through environment
# variables are an injection / operability hazard. The ENABLED categories and
# the hit threshold ARE env-tunable (see has_high_value_event) — that is the
# safe tuning surface.
_EVENT_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    # Earnings / results / guidance — quarterly or annual financial performance.
    "earnings": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\bearnings\b",
            r"\bEPS\b",
            r"\bquarterly (?:results|earnings|profit|revenue|report)\b",
            r"\b(?:first|second|third|fourth)[- ]quarter\b",
            r"\bQ[1-4]\b",
            r"\b(?:full[- ]year|fiscal|half[- ]year|H[12])\b.{0,20}\b(?:results|earnings|profit|revenue)\b",
            r"\b(?:revenue|net income|net loss|operating income|pretax profit|profit)\b",
            r"\b(?:beat|beats|missed|misses|topped|tops)\b.{0,25}\b(?:estimates?|expectations?|forecasts?|consensus|views?)\b",
            r"\bguidance\b",
            r"\bprofit warning\b",
            r"\b(?:raises?|cuts?|lifts?|lowers?)\b.{0,15}\b(?:outlook|forecast|guidance)\b",
        )
    ),
    # M&A / stake / corporate action.
    "m_and_a": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(?:acquire|acquires|acquired|acquisition|acquiring)\b",
            r"\b(?:merger|merges|to merge|merging)\b",
            r"\b(?:takeover|buyout|buy-?out)\b",
            r"\bto acquire\b",
            r"\b(?:agrees?|agreed) to (?:buy|acquire|merge|purchase)\b",
            r"\b(?:divest|divestiture|divests?|spin-?off|spinoff|carve-?out)\b",
            r"\bstake\b",
            r"\b(?:tender offer|all-cash deal|cash-and-stock|definitive agreement)\b",
        )
    ),
    # Sell-side analyst rating / price-target actions.
    "analyst": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(?:upgrade|upgrades|upgraded|downgrade|downgrades|downgraded)\b",
            r"\b(?:price target|target price)\b",
            r"\b(?:initiates?|initiated) (?:coverage|at)\b",
            r"\b(?:overweight|underweight|equal[- ]weight)\b",
            r"\b(?:reiterates?|maintains?|reaffirms?) (?:buy|sell|hold|neutral|outperform|underperform)\b",
            r"\brated? (?:buy|sell|hold|neutral|outperform|underperform)\b",
            r"\b(?:buy|sell|hold|neutral|outperform|underperform) rating\b",
            r"\b(?:raises?|cuts?|lifts?|lowers?|boosts?|trims?|hikes?) (?:its )?(?:price )?target\b",
        )
    ),
    # Material contract / award / order.
    "contract": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(?:contract|contracts)\b",
            r"\b(?:awarded|awards)\b.{0,25}\b(?:contract|deal|order|grant)\b",
            r"\b(?:wins?|won|secures?|secured|lands?|landed|nabs?) (?:a |the )?"
            r"(?:\$|contract|deal|order|bid|tender|award)\b",
            r"\bpurchase order\b",
            r"\bdeal worth\b",
        )
    ),
    # Insider / ownership / 13D-13G disclosures.
    "ownership": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(?:schedule )?13[dg]\b",
            r"\binsider (?:buying|selling|trade|trading|transaction|purchase|sale)\b",
            r"\b(?:files?|filed|reports?|reported|discloses?|disclosed) (?:a )?(?:\d+(?:\.\d+)?% )?stake\b",
            r"\b(?:increases?|raises?|cuts?|reduces?|trims?|boosts?) (?:its )?stake\b",
            r"\bactivist (?:investor|stake|position)\b",
        )
    ),
}

# Immutable view of the known categories, for callers building an enabled set.
ALL_EVENT_CATEGORIES: Final[frozenset[str]] = frozenset(_EVENT_PATTERNS)


def detect_event_categories(
    text: str,
    *,
    categories: frozenset[str] | None = None,
) -> frozenset[str]:
    """Return the set of substantive-financial-event categories present in ``text``.

    Pure and deterministic — no I/O, no LLM. Runs each enabled category's regexes
    over ``text`` (already-lowercased matching via re.IGNORECASE) and returns the
    names of the categories that fired.

    Args:
        text: The scan text (typically title + early body). Empty/whitespace → {}.
        categories: The category names to evaluate. ``None`` evaluates ALL known
            categories. Unknown names are ignored. Restrict this set to disable a
            category class without changing the pattern catalogue.

    Returns:
        A frozenset of matched category names (subset of ``ALL_EVENT_CATEGORIES``).
    """
    if not text or not text.strip():
        return frozenset()
    active = ALL_EVENT_CATEGORIES if categories is None else (categories & ALL_EVENT_CATEGORIES)
    matched: set[str] = set()
    for category in active:
        for pattern in _EVENT_PATTERNS[category]:
            if pattern.search(text):
                matched.add(category)
                break  # one hit is enough to mark the category present
    return frozenset(matched)


def has_high_value_event(
    title: str | None,
    body_head: str | None,
    *,
    enabled: bool,
    categories: frozenset[str] | None = None,
    min_hits: int = 1,
    scan_chars: int = 600,
) -> bool:
    """Decide whether a doc reports a substantive financial event worth deep extraction.

    Combines ``title`` with the first ``scan_chars`` characters of ``body_head`` and
    checks how many distinct event categories match. The doc qualifies when at least
    ``min_hits`` categories fire.

    Args:
        title: Document title (may be None).
        body_head: Leading body text — lede / first section(s) (may be None). Only the
            first ``scan_chars`` characters are scanned (cheap; the signal lives in the
            lede, and a full-body scan would slow every article for no accuracy gain).
        enabled: Master toggle. ``False`` → always returns ``False`` (signal off).
        categories: Enabled category names; ``None`` = all. Passed through to
            ``detect_event_categories``.
        min_hits: Minimum number of DISTINCT matched categories required to qualify.
            Default 1 (any single substantive event rescues the doc). Raise it to make
            the override stricter.
        scan_chars: How many leading body characters to scan (default 600).

    Returns:
        ``True`` iff the signal is enabled and the doc carries a substantive event.
    """
    if not enabled:
        return False
    parts: list[str] = []
    if title:
        parts.append(title)
    if body_head:
        parts.append(body_head[:scan_chars])
    if not parts:
        return False
    matched = detect_event_categories("\n".join(parts), categories=categories)
    return len(matched) >= min_hits
