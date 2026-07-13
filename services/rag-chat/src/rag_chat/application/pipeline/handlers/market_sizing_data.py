"""Loader + search for the curated TAM / market-size reference table.

Area-2 P3 (chat-enhancement-roadmap): projection / what-if questions need a
SCENARIO PARAMETER (total addressable market, served-market size, or segment
share) that the live platform does not ingest. This module loads a small,
hand-curated, DATED reference table from ``market_sizing_reference.yaml`` and
exposes a keyword search over it so the ``get_market_sizing`` tool can return
CITABLE rows — grounding a projection on a sourced analyst estimate instead of
a bare parametric assumption.

NOT A LIVE FEED. Every row is an analyst estimate with an explicit measurement
year + source. The loader carries the file-level ``disclaimer`` through so the
handler (and therefore the chat) always frames a figure as a dated estimate.

Design notes:
  * The YAML is packaged next to this module and read once, lazily, via
    ``Path(__file__).parent`` — the SAME pattern the tool registry uses for
    ``capability_manifest.yaml`` (single source of truth, no DB round-trip for
    static reference data).
  * Search is deterministic keyword overlap over ``segment`` + ``aliases`` +
    ``category`` — no embeddings, no network. A reference table this small does
    not warrant ANN retrieval, and determinism keeps the tests stable.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Reference table lives next to this module (mirrors capability_manifest.yaml).
_DATA_PATH = Path(__file__).parent / "market_sizing_reference.yaml"

# Tokeniser for free-text query matching: lowercase alphanumeric words of >=2
# chars. Kept intentionally simple + deterministic (no stemming) so the curated
# ``aliases`` list stays the authoritative match surface.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Very common words that would otherwise inflate overlap scores with no signal.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "and",
        "or",
        "to",
        "in",
        "on",
        "is",
        "are",
        "what",
        "whats",
        "size",
        "market",
        "tam",
        "share",
        "total",
        "addressable",
    }
)


@dataclass(frozen=True)
class MarketSizingRow:
    """A single curated market-size / TAM reference row (analyst estimate)."""

    id: str
    segment: str
    category: str
    market_size_usd: str
    size_year: int
    cagr: str
    source: str
    as_of_date: str
    aliases: tuple[str, ...] = ()
    forecast: str | None = None
    vendor_shares: tuple[str, ...] = ()

    def match_tokens(self) -> set[str]:
        """The token surface a query is scored against (segment + aliases + category)."""
        haystack = " ".join([self.segment, self.category, *self.aliases]).lower()
        return {t for t in _TOKEN_RE.findall(haystack) if t not in _STOPWORDS}

    def to_display_text(self, disclaimer: str) -> str:
        """Human-readable, citation-ready summary of the row.

        Explicitly leads with the ESTIMATE framing + as-of date so the synthesis
        turn cannot present the figure as a live/spot number.
        """
        lines = [
            f"{self.segment} — ANALYST-ESTIMATE reference (not real-time; as of {self.as_of_date}):",
            f"  Market size: {self.market_size_usd}",
            f"  Forward CAGR: {self.cagr}",
        ]
        if self.forecast:
            lines.append(f"  Forecast: {self.forecast}")
        if self.vendor_shares:
            lines.append("  Notable vendor shares: " + "; ".join(self.vendor_shares))
        lines.append(f"  Source: {self.source} (category: {self.category})")
        lines.append(f"  NOTE: {disclaimer.strip()}")
        return "\n".join(lines)

    def grounding_pairs(self) -> tuple[tuple[str, str], ...]:
        """Structured numeric fields for the chat-eval substantiation sampler."""
        pairs: list[tuple[str, str]] = [
            ("segment", self.segment),
            ("market_size_usd", self.market_size_usd),
            ("size_year", str(self.size_year)),
            ("cagr", self.cagr),
            ("as_of_date", self.as_of_date),
        ]
        if self.forecast:
            pairs.append(("forecast", self.forecast))
        return tuple(pairs)


@dataclass(frozen=True)
class MarketSizingReference:
    """The full loaded reference table + file-level metadata."""

    version: str
    as_of: str
    disclaimer: str
    rows: tuple[MarketSizingRow, ...] = field(default_factory=tuple)

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        limit: int = 5,
    ) -> list[MarketSizingRow]:
        """Return the best-matching rows for a free-text ``query``.

        Matching is deterministic keyword overlap against each row's
        segment + aliases + category token surface. When ``query`` is empty we
        return a stable slice (optionally category-filtered) so a bare
        ``get_market_sizing`` call still yields useful reference rows.

        ``limit`` is clamped to 1..20.
        """
        limit = max(1, min(int(limit), 20))
        cat = (category or "").strip().lower() or None

        candidates = [r for r in self.rows if cat is None or r.category.lower() == cat]

        q_tokens = {t for t in _TOKEN_RE.findall((query or "").lower()) if t not in _STOPWORDS}
        if not q_tokens:
            # No usable query terms → return a deterministic slice (list order is
            # the curated file order, which is grouped by category).
            return candidates[:limit]

        scored: list[tuple[int, int, MarketSizingRow]] = []
        for idx, row in enumerate(candidates):
            overlap = len(q_tokens & row.match_tokens())
            if overlap > 0:
                # Sort by overlap desc, then original file order (idx) asc for
                # a stable, reproducible ranking.
                scored.append((overlap, -idx, row))

        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [row for _, _, row in scored[:limit]]


def _coerce_row(raw: dict[str, Any]) -> MarketSizingRow:
    """Build a frozen row from a YAML mapping, tolerating missing optionals."""
    return MarketSizingRow(
        id=str(raw["id"]),
        segment=str(raw["segment"]),
        category=str(raw["category"]),
        market_size_usd=str(raw["market_size_usd"]),
        size_year=int(raw["size_year"]),
        cagr=str(raw["cagr"]),
        source=str(raw["source"]),
        as_of_date=str(raw["as_of_date"]),
        aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
        forecast=(str(raw["forecast"]) if raw.get("forecast") else None),
        vendor_shares=tuple(str(v) for v in (raw.get("vendor_shares") or [])),
    )


@functools.lru_cache(maxsize=1)
def load_market_sizing_reference() -> MarketSizingReference:
    """Load + validate the reference table once (cached for process lifetime).

    Raises ``ValueError`` if the file is malformed (missing rows / required
    fields) so a packaging regression fails fast at first use rather than
    silently serving an empty table.
    """
    with open(_DATA_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict) or "rows" not in doc:
        raise ValueError(f"market_sizing_reference.yaml malformed: expected top-level 'rows' mapping ({_DATA_PATH})")

    raw_rows = doc.get("rows") or []
    if not raw_rows:
        raise ValueError("market_sizing_reference.yaml contains no rows")

    rows = tuple(_coerce_row(r) for r in raw_rows)

    ids = [r.id for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("market_sizing_reference.yaml has duplicate row ids")

    log.info("market_sizing_reference_loaded", rows=len(rows), version=str(doc.get("version", "?")))
    return MarketSizingReference(
        version=str(doc.get("version", "1")),
        as_of=str(doc.get("as_of", "")),
        disclaimer=str(doc.get("disclaimer", "Analyst-estimate reference data — not real-time.")),
        rows=rows,
    )
