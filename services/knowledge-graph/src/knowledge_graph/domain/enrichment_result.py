"""Enrichment result value objects for S7 Worker 13J (PRD-0073 §9.1-9.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class EnrichmentSource(StrEnum):
    """Origin of the enrichment description (PRD-0073 §9.2)."""

    MARKET_DATA = "market_data"
    EODHD = "eodhd"
    LLM = "llm"
    NONE = "none"


@dataclass(frozen=True)
class EnrichmentResult:
    """Value object capturing the outcome of a single entity enrichment pass.

    Invariants:
    - ``data_completeness`` is in [0.0, 1.0] (inclusive)
    - ``enriched_at`` must be timezone-aware (UTC)
    - ``seeded_relations`` may be empty; never None
    """

    entity_id: UUID
    description: str | None
    metadata: dict[str, object]
    data_completeness: float
    enriched_at: datetime
    source: EnrichmentSource
    seeded_relations: list[str] = field(default_factory=list)


_EMPTY_RE = re.compile(r"^\s*$")


def _present(v: object) -> bool:
    """Return True iff value is non-None and non-empty-string."""
    if v is None:
        return False
    if isinstance(v, str) and _EMPTY_RE.match(v):
        return False
    return bool(v)


def compute_data_completeness(
    entity_type: str,
    description: str | None,
    metadata: dict[str, object],
) -> float:
    """Compute a 0.0-1.0 completeness score from enrichment fields (PRD-0073 §9.3).

    Empty strings are treated as absent (same as None).
    """
    if entity_type in ("financial_instrument", "company"):
        # NOTE (F-Q14): ``headquarters_city`` is intentionally excluded from the score even
        # though _extract_metadata extracts it.  Reason: it is highly correlated with
        # ``headquarters_country`` (a city implies a country) so counting both would
        # double-weight a single fact.  The city is still surfaced in the response payload
        # (EntityMetadata.headquarters_city) for UI display.
        expected = [
            description,
            metadata.get("sector"),
            metadata.get("industry"),
            metadata.get("country"),
            metadata.get("exchange"),
            metadata.get("isin"),
            metadata.get("ticker"),
            metadata.get("employee_count"),
            metadata.get("founded_year"),
            metadata.get("headquarters_country"),
        ]
        return len([f for f in expected if _present(f)]) / 10

    if entity_type == "person":
        expected = [
            description,
            metadata.get("role"),
            metadata.get("organization"),
            metadata.get("nationality"),
        ]
        return len([f for f in expected if _present(f)]) / 4

    # concept, location, event, and any other type
    expected = [
        description,
        metadata.get("category"),
    ]
    return len([f for f in expected if _present(f)]) / 2
