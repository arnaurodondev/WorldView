"""Canonical model for the ``graph.state.changed.v1`` event.

PLAN-0062 Wave-A audit follow-up F-006.  Mirrors the Avro schema at
``infra/kafka/schemas/graph.state.changed.v1.avsc`` field-for-field so the
producer (S7 Block 12a ``materialise_graph_writes``) can construct the dict
once and the alert service (S10 fan-out) can deserialise into a typed model.

Field alignment is asserted in
``libs/contracts/tests/test_events_kg_graph_state_changed.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalGraphStateChanged:
    """Notification that knowledge-graph state changed for one or more entities.

    Hot path:  S7 Block 12a writes relations / evidence / events / claims, then
    emits one of these events per processed message.  S10 fans the event out
    to subscribed alert rules keyed off ``primary_entity_id`` (the partition
    key) and the array of ``affected_entity_ids``.
    """

    event_id: str
    occurred_at: str
    primary_entity_id: str
    affected_entity_ids: tuple[str, ...]
    change_type: str
    source_doc_id: str | None = None
    correlation_id: str | None = None
    is_backfill: bool = False
    relation_ids: tuple[str, ...] = ()
    canonical_types: tuple[str, ...] = ()
    # Constants from the Avro schema (defaults baked in there as well).
    event_type: str = field(default="graph.state.changed")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalGraphStateChanged:
        """Build the canonical model from a deserialized Avro dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            primary_entity_id=str(d["primary_entity_id"]),
            affected_entity_ids=tuple(str(e) for e in d.get("affected_entity_ids", []) or []),
            change_type=str(d["change_type"]),
            relation_ids=tuple(str(r) for r in d.get("relation_ids", []) or []),
            canonical_types=tuple(str(t) for t in d.get("canonical_types", []) or []),
            source_doc_id=(str(d["source_doc_id"]) if d.get("source_doc_id") is not None else None),
            is_backfill=bool(d.get("is_backfill", False)),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "graph.state.changed")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "primary_entity_id": self.primary_entity_id,
            "affected_entity_ids": list(self.affected_entity_ids),
            "change_type": self.change_type,
            "relation_ids": list(self.relation_ids),
            "canonical_types": list(self.canonical_types),
            "source_doc_id": self.source_doc_id,
            "is_backfill": self.is_backfill,
            "correlation_id": self.correlation_id,
        }
