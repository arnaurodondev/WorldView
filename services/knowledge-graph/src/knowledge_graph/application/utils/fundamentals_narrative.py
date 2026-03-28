"""Deterministic fundamentals narrative builder (PRD §6.7 Block 13D-3).

Converts structured financial data into an embeddable narrative using
interpretive words.  Zero LLM cost — pure deterministic template.

The function is deliberately side-effect-free so that tests can assert
exact output and the same input always produces the same string.
"""

from __future__ import annotations

_BILLION = 1_000.0  # revenue_usd is in millions; divide by 1000 for billions


def build_fundamentals_narrative(
    canonical_name: str,
    entity_type: str,
    *,
    revenue_usd_millions: float | None = None,
    gross_margin_pct: float | None = None,
    net_margin_pct: float | None = None,
    pe_ratio: float | None = None,
    price: float | None = None,
    week_52_high: float | None = None,
    week_52_low: float | None = None,
    description: str | None = None,
) -> str:
    """Build a deterministic embeddable financial narrative.

    Args:
        canonical_name: Entity canonical name (e.g. "Apple Inc.").
        entity_type:    Entity type (e.g. "financial_instrument").
        revenue_usd_millions: Trailing twelve-month revenue in USD millions.
        gross_margin_pct: Gross margin 0-100 (%).
        net_margin_pct:   Net margin, can be negative (%).
        pe_ratio:         Trailing P/E ratio (negative = negative earnings).
        price:            Current market price.
        week_52_high:     52-week high price.
        week_52_low:      52-week low price.
        description:      Optional company description (prepended if provided).

    Returns:
        A single UTF-8 string suitable for embedding.  Same inputs always
        produce identical output.
    """
    parts: list[str] = []

    header = f"{canonical_name} ({entity_type}) — Financial State Summary"
    parts.append(header)

    if description:
        parts.append(description.strip())

    # Revenue
    if revenue_usd_millions is not None:
        rev_b = revenue_usd_millions / _BILLION
        size_word = _revenue_size(rev_b)
        parts.append(f"Revenue: ${rev_b:.2f}B — {size_word} company by revenue.")

    # Gross margin
    if gross_margin_pct is not None:
        gm_word = _gross_margin_word(gross_margin_pct)
        parts.append(f"Gross Margin: {gross_margin_pct:.1f}% — {gm_word} gross profitability.")

    # Net margin
    if net_margin_pct is not None:
        nm_word = _net_margin_word(net_margin_pct)
        parts.append(f"Net Margin: {net_margin_pct:.1f}% — {nm_word}.")

    # P/E ratio
    if pe_ratio is not None:
        pe_word = _pe_word(pe_ratio)
        parts.append(f"P/E Ratio: {pe_ratio:.1f} — {pe_word} valuation.")

    # Price vs 52-week range
    if price is not None and week_52_high is not None and week_52_low is not None:
        pos_word = _price_position_word(price, week_52_low, week_52_high)
        parts.append(f"Price: ${price:.2f} (52-week range: ${week_52_low:.2f} - ${week_52_high:.2f}) - {pos_word}.")
    elif price is not None:
        parts.append(f"Price: ${price:.2f}.")

    if len(parts) == 1:
        # Only the header — no financial data provided
        parts.append("No financial data available.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Interpretive helpers (deterministic, no randomness)
# ---------------------------------------------------------------------------


def _revenue_size(rev_billions: float) -> str:
    if rev_billions >= 100.0:
        return "large-cap"
    if rev_billions >= 10.0:
        return "mid-cap"
    if rev_billions >= 1.0:
        return "small-cap"
    return "micro-cap"


def _gross_margin_word(gm: float) -> str:
    if gm >= 40.0:
        return "strong"
    if gm >= 20.0:
        return "moderate"
    return "weak"


def _net_margin_word(nm: float) -> str:
    if nm >= 20.0:
        return "highly profitable"
    if nm >= 10.0:
        return "profitable"
    if nm >= 0.0:
        return "marginally profitable"
    return "unprofitable"


def _pe_word(pe: float) -> str:
    if pe < 0:
        return "negative earnings"
    if pe > 30.0:
        return "expensive"
    if pe >= 15.0:
        return "fairly valued"
    return "cheap"


def _price_position_word(price: float, low: float, high: float) -> str:
    if high <= low:
        return "mid-range"
    pct = (price - low) / (high - low)
    if pct >= 0.90:
        return "near highs"
    if pct <= 0.10:
        return "near lows"
    return "mid-range"
