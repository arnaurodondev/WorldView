"""Canonical model for the ``nlp.signal.detected.v1`` event.

PLAN-0062 Wave-A audit follow-up F-006.  Mirrors the Avro schema at
``infra/kafka/schemas/nlp.signal.detected.v1.avsc`` field-for-field so the
producer (S6 ``_enqueue_signal_events`` in the article consumer) can construct
the dict once and downstream consumers (S10 alert fan-out, S6 read-side query
use cases) can deserialise into a typed model.

Field alignment is asserted in
``libs/contracts/tests/test_events_nlp_signal_detected.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalNlpSignalDetected:
    """High-confidence signal extracted from a document.

    Hot path:  S6 deep-extraction block produces ``SignalEvent`` rows; the
    article consumer's ``_enqueue_signal_events`` writes one outbox record per
    signal keyed on the ``subject_entity_id`` so S10 fan-out is per-entity.
    ``market_impact_score`` defaults to ``0.0`` and is updated later by
    ``PriceImpactLabellingWorker`` (PLAN-0020).
    """

    event_id: str
    occurred_at: str
    doc_id: str
    claim_id: str
    claim_type: str
    polarity: str
    extraction_confidence: float
    claimer_entity_id: str | None = None
    subject_entity_id: str | None = None
    is_backfill: bool = False
    correlation_id: str | None = None
    market_impact_score: float = 0.0
    # Constants from the Avro schema (defaults baked in there as well).
    event_type: str = field(default="nlp.signal.detected")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalNlpSignalDetected:
        """Build the canonical model from a deserialized Avro dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            doc_id=str(d["doc_id"]),
            claim_id=str(d["claim_id"]),
            claim_type=str(d["claim_type"]),
            polarity=str(d["polarity"]),
            extraction_confidence=float(d["extraction_confidence"]),
            claimer_entity_id=(str(d["claimer_entity_id"]) if d.get("claimer_entity_id") is not None else None),
            subject_entity_id=(str(d["subject_entity_id"]) if d.get("subject_entity_id") is not None else None),
            is_backfill=bool(d.get("is_backfill", False)),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            market_impact_score=float(d.get("market_impact_score", 0.0)),
            event_type=str(d.get("event_type", "nlp.signal.detected")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "doc_id": self.doc_id,
            "claim_id": self.claim_id,
            "claimer_entity_id": self.claimer_entity_id,
            "subject_entity_id": self.subject_entity_id,
            "claim_type": self.claim_type,
            "polarity": self.polarity,
            "extraction_confidence": self.extraction_confidence,
            "is_backfill": self.is_backfill,
            "correlation_id": self.correlation_id,
            "market_impact_score": self.market_impact_score,
        }
