"""Numeric grounding shared contracts (PLAN-0093 Wave E-2).

These are the *types* shared between the rag-chat NumericGroundingValidator
and any downstream consumer (eval harness, audit replay, future tool result
schemas). The actual validation logic lives in
``services/rag-chat/src/rag_chat/application/services/numeric_grounding.py``.

Why this lives in libs/contracts: ``FieldKind`` is the classification
vocabulary that lets a tool emit its rows already tagged with the right
grounding-tolerance bucket. Today only rag-chat reads these, but
future work (S6 result envelopes, briefing fact-checker) will read
them too — keeping the enum + default tolerances behind a contract
boundary means callers depend on ``contracts``, not on the rag-chat
service package, which would be an R12/R25 violation.

Per-kind default tolerances are TUNED for the GPT-4o-class LLM behaviour:

- PRICE / RETURN_PCT (0.1%): analysts will spot a 1¢ error on a $100 stock.
- YEAR / QUARTER (0%): must match exactly — a "Q2 2026 revenue $10.3B"
  before AMD has reported Q2 2026 is an outright lie, not a rounding bug.
- EPS (2%): EPS quoted to 2 decimals; $0.45 vs $0.46 acceptable.
- RATIO (2%): P/E 23.7 vs 24.1 ok; 23.7 vs 28.0 NOT.
- REVENUE / MARKET_CAP (0.5%): $68.1B vs $68.127B passes; $34.6B vs
  $10.25B fails (the canonical AMD case from the QA audit).
- SHARES (1%): share counts are exact in filings but LLM rounds.
- HEADCOUNT (5%): quarterly snapshots with lag.
- UNKNOWN (0.5%): conservative default for unclassifiable numbers.
"""

from __future__ import annotations

from enum import Enum


class FieldKind(str, Enum):
    """Financial field families that share rounding behaviour.

    Inherits from ``str`` so the enum value serialises directly to JSON
    (settings overrides, audit logs) without a custom encoder.
    """

    PRICE = "price"  # daily price, intraday — LLM must quote exact
    RETURN_PCT = "return_pct"  # day/week/period returns — exact
    YEAR = "year"  # 2024, 2025 — exact (or skip)
    QUARTER = "quarter"  # Q1 2026 — exact (label match, not numeric)
    EPS = "eps"  # earnings per share — tighter than revenue
    RATIO = "ratio"  # P/E, P/B, ROE, ROA, gross/operating margin
    REVENUE = "revenue"  # revenue, EBIT, net income, FCF — LLM rounds
    MARKET_CAP = "market_cap"  # often quoted in B/T with rounding
    SHARES = "shares"  # share count
    HEADCOUNT = "headcount"  # employee count
    PROSE = "prose"  # rationalisation prose (no numeric value) — surfaced by validator
    UNKNOWN = "unknown"  # default fallback for unclassifiable numbers


# Default per-kind tolerances (% relative diff). Override via settings.
# These are intentionally exposed as a module-level dict (not a frozen
# class attribute) so a deployment can patch the dict at startup — e.g.
# briefly relax HEADCOUNT during a quarterly hiring announcement — without
# code changes.
DEFAULT_TOLERANCES: dict[FieldKind, float] = {
    FieldKind.PRICE: 0.001,  # 0.1%
    FieldKind.RETURN_PCT: 0.001,  # 0.1%
    FieldKind.YEAR: 0.0,  # exact
    FieldKind.QUARTER: 0.0,  # exact
    FieldKind.EPS: 0.02,  # 2%
    FieldKind.RATIO: 0.02,  # 2%
    FieldKind.REVENUE: 0.005,  # 0.5%
    FieldKind.MARKET_CAP: 0.005,  # 0.5%
    FieldKind.SHARES: 0.01,  # 1%
    FieldKind.HEADCOUNT: 0.05,  # 5%
    FieldKind.PROSE: 0.0,  # n/a — PROSE entries carry no numeric value, surfaced by exact-phrase match
    FieldKind.UNKNOWN: 0.005,  # 0.5% conservative default
}


__all__ = ["DEFAULT_TOLERANCES", "FieldKind"]
