"""EntityChatContext — domain value object for entity-scoped chat (PLAN-0074 Wave F).

Carries all the context loaded from S7 Knowledge Graph that the
EntityContextChatUseCase uses to build a focused system-prompt prefix.

Design notes:
- Frozen dataclass: immutable after construction, safe to pass between layers.
- ``is_empty=True`` signals a graceful fallback: S7 was unreachable or returned
  404, so the use case falls back to a generic prompt without entity context.
- R12 (domain layer independence): no infrastructure imports allowed here.
  All fields use only stdlib types (UUID, str, float, dict, list, bool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class EntityChatContext:
    """Aggregated S7 intelligence context for a single entity.

    Fields map directly from the S7 ``/internal/v1/entities/{id}/intelligence``
    response and the ``/api/v1/entities/{id}/graph?depth=1&limit=5`` response.

    Attributes:
        entity_id:          UUID of the entity.
        canonical_name:     Human-readable display name (e.g. "Apple Inc.").
        entity_type:        Domain type string (e.g. "financial_instrument", "person").
        narrative_text:     Latest LLM-generated narrative from S7 (may be None when
                            the entity has not been enriched yet).
        health_score:       Composite data-health score in [0.0, 1.0] (optional).
        data_completeness:  Fraction of enrichment tasks completed (optional).
        key_metrics:        Dict of key-value metrics from S7 fundamentals snapshot.
                            Empty dict when none are available.
        top_relations:      Up to 5 egocentric graph edges from S7 graph endpoint.
                            Each entry is a dict with at least ``relation_type`` and
                            ``target_name`` keys.
        is_empty:           When True, the context load failed gracefully (404, 5xx,
                            or timeout from S7). The use case uses a generic prompt.
    """

    entity_id: UUID
    # WHY non-empty defaults for strings: prevents AttributeError when callers access
    # these fields without checking is_empty first. Empty string is safe for f-string
    # interpolation in system prompts.
    canonical_name: str = ""
    entity_type: str = ""
    narrative_text: str | None = None
    health_score: float | None = None
    data_completeness: float | None = None
    # WHY field(default_factory=dict): frozen dataclasses cannot use mutable default
    # literals; field() is required for list/dict defaults in dataclasses.
    key_metrics: dict[str, Any] = field(default_factory=dict)
    top_relations: list[dict[str, Any]] = field(default_factory=list)
    is_empty: bool = False
