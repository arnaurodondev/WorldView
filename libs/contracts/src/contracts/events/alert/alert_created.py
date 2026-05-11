"""Canonical model for the ``alert.created.v1`` event.

PLAN-0082 Wave B. Mirrors the Avro schema at
``infra/kafka/schemas/alert.created.v1.avsc`` field-for-field.

Producer is S10's new ``POST /api/v1/alerts`` route (user-initiated alert
creation via the LLM ``create_alert`` tool). The event is written to S10's
outbox table in the same DB transaction as the Alert row, then dispatched to
Kafka by the outbox dispatcher.

No consumer exists at time of writing — the event is emitted for auditability
and future consumers (e.g. analytics, alert-aggregation services).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalAlertCreated:
    """Trigger event published when a user-initiated alert rule is persisted.

    ``source`` distinguishes LLM-created alerts (``llm_tool``) from future
    programmatic origins (``api``) so downstream consumers can filter by origin.
    ``threshold`` is a JSON-encoded string to remain schema-stable as condition
    types gain new parameters over time.
    """

    event_id: str
    occurred_at: str
    alert_id: str
    user_id: str
    tenant_id: str
    entity_id: str
    condition: str
    threshold: str
    severity: str = "low"
    source: str = "llm_tool"
    correlation_id: str | None = None
    event_type: str = field(default="alert.created")
    schema_version: int = field(default=1)

    @classmethod
    def from_dict(cls, d: dict) -> CanonicalAlertCreated:
        """Build the canonical model from a deserialized Avro/JSON dict."""
        return cls(
            event_id=str(d["event_id"]),
            occurred_at=str(d["occurred_at"]),
            alert_id=str(d["alert_id"]),
            user_id=str(d["user_id"]),
            tenant_id=str(d["tenant_id"]),
            entity_id=str(d["entity_id"]),
            condition=str(d["condition"]),
            threshold=str(d["threshold"]),
            severity=str(d.get("severity", "low")),
            source=str(d.get("source", "llm_tool")),
            correlation_id=(str(d["correlation_id"]) if d.get("correlation_id") is not None else None),
            event_type=str(d.get("event_type", "alert.created")),
            schema_version=int(d.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict matching the Avro schema field set."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at,
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "entity_id": self.entity_id,
            "condition": self.condition,
            "threshold": self.threshold,
            "severity": self.severity,
            "source": self.source,
            "correlation_id": self.correlation_id,
        }
