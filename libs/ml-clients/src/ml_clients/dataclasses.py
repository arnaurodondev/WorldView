"""Immutable dataclasses for ML client inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass, field  # noqa: F401
from decimal import Decimal


@dataclass(frozen=True)
class EmbeddingInput:
    text: str
    model_id: str
    instruction_prefix: str | None = None


@dataclass(frozen=True)
class EmbeddingOutput:
    embedding: list[float]
    model_id: str
    dimension: int


@dataclass(frozen=True)
class NERInput:
    text: str
    entity_classes: list[str]
    threshold: float = 0.5


@dataclass(frozen=True)
class EntityMention:
    text: str
    label: str
    start: int
    end: int
    score: float


@dataclass(frozen=True)
class NEROutput:
    mentions: list[EntityMention]


@dataclass(frozen=True)
class ExtractionInput:
    prompt: str
    context: str
    output_schema: dict  # type: ignore[type-arg]
    model_id: str
    template_id: str | None = None


@dataclass(frozen=True)
class ExtractionOutput:
    """Result of a single structured-extraction call.

    Task #36 (extraction 429 fallback) adds three resilience-audit fields. They
    are all defaulted so EVERY existing construction site (tests, other adapters)
    stays valid without edits — backward-compatible by design:

      * ``model_used``      — the model that ACTUALLY produced this result. When a
                              429/timeout on the primary forced a fallback hop this
                              is the SECONDARY model slug, NOT the configured
                              primary.  ``None`` falls back to ``model_id`` for
                              callers that pre-date the field.
      * ``fallback_reason`` — why the fallback fired, one of the literal strings
                              ``"none" | "rate_limit" | "timeout" | "server_error"``.
                              ``"none"`` means the primary served the call directly.
      * ``attempts``        — total number of provider HTTP attempts made across
                              the primary AND fallback models (>=1).  Lets the
                              usage-log/ops see how hard a call had to work.
    """

    result: dict  # type: ignore[type-arg]
    raw_response: str
    model_id: str
    extraction_confidence: float | None = None
    # ── Task #36 resilience-audit metadata (all backward-compatible defaults) ──
    model_used: str | None = None
    fallback_reason: str = "none"
    attempts: int = 1
    # ── PLAN-0117 FR-1: provider-reported cost (backward-compatible default) ──
    # Verbatim ``usage.estimated_cost`` when the provider (DeepInfra) returns it,
    # as a :class:`decimal.Decimal`; ``None`` when the provider did not report a
    # cost (→ caller resolves via the price matrix). Surfacing it here lets the
    # KG fallback chain / S6 deep-extraction stamp ``cost_source="provider"``
    # without re-parsing the raw HTTP response.
    provider_cost_usd: Decimal | None = None
