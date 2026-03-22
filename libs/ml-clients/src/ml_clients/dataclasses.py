"""Immutable dataclasses for ML client inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass, field  # noqa: F401


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
    result: dict  # type: ignore[type-arg]
    raw_response: str
    model_id: str
    extraction_confidence: float | None = None
