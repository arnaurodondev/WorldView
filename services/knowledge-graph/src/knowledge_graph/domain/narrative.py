"""Domain entity for entity narrative versions (PRD-0074 §9.1, §9.2).

``EntityNarrativeVersion`` is an append-only, versioned record of LLM-generated
narrative text for a canonical entity.  Only one version per entity may carry
``is_current=True`` at any given time — enforced at the DB level by a partial
unique index (migration 0031) and in application code by
``NarrativeRepository.insert_and_promote``.

``NarrativeGenerationReason`` records *why* a generation pass was triggered so
operators can segment narrative quality by trigger type in dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class NarrativeGenerationReason(StrEnum):
    """Trigger reasons for a narrative generation pass.

    Values map directly to the ``generation_reason`` column in
    ``entity_narrative_versions`` and to the ``generation_reason`` field in the
    ``entity.narrative.generated.v1`` Avro event.
    """

    INITIAL = "INITIAL"
    PERIODIC_REFRESH = "PERIODIC_REFRESH"
    DATA_UPDATE = "DATA_UPDATE"
    EVIDENCE_SURGE = "EVIDENCE_SURGE"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"


@dataclass(frozen=True, kw_only=True)
class EntityNarrativeVersion:
    """One immutable version of an entity's LLM-generated narrative.

    Invariants (enforced in ``__post_init__``):
    - ``50 <= len(narrative_text) <= 10000``
    - ``word_count`` (when provided) must equal ``len(narrative_text.split())``
    - ``generated_at`` must be timezone-aware (UTC-aware)

    Args:
    ----
        version_id:         UUIDv7 primary key for this version row.
        entity_id:          The canonical entity this narrative describes.
        narrative_text:     Full LLM-generated narrative (50-10,000 chars).
        model_id:           Model that generated the text (e.g. ``"meta-llama/Meta-Llama-3.1-8B-Instruct"``).
        generation_reason:  Why this generation pass was triggered.
        input_snapshot:     JSONB snapshot of the inputs fed to the LLM, used
                            for idempotency checks (SHA-256 of canonical JSON).
        generated_at:       UTC-aware timestamp of when the text was produced.
        is_current:         Whether this is the active narrative for the entity.
        word_count:         Pre-computed word count; must match the text when supplied.
        quality_score:      Optional LLM self-evaluation score in [0.0, 1.0].

    """

    version_id: UUID
    entity_id: UUID
    narrative_text: str
    model_id: str
    generation_reason: NarrativeGenerationReason
    input_snapshot: dict | None = None
    generated_at: datetime = None  # type: ignore[assignment]  # validated in __post_init__
    is_current: bool = False
    word_count: int | None = None
    quality_score: float | None = None

    def __post_init__(self) -> None:
        # Validate narrative text length
        if not (50 <= len(self.narrative_text) <= 10000):
            raise ValueError(f"narrative_text length {len(self.narrative_text)} is outside allowed range [50, 10000]")

        # Validate word_count matches if provided
        if self.word_count is not None:
            actual = len(self.narrative_text.split())
            if self.word_count != actual:
                raise ValueError(f"word_count {self.word_count} does not match actual word count {actual}")

        # Validate generated_at is UTC-aware
        if self.generated_at is None:
            raise ValueError("generated_at is required")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware (UTC)")
