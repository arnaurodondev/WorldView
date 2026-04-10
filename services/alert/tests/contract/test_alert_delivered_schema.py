"""Contract tests for alert.delivered.v1 Avro schema.

Validates:
- Forward-compatibility: records WITHOUT severity field deserialize with default applied
- Roundtrip: records WITH severity serialize + deserialize correctly
- schema_version default is 2 (PRD-0021 Wave A-2 bump)
- severity field exists with default "low"
"""

from __future__ import annotations

import io
from pathlib import Path

import fastavro  # type: ignore[import-untyped]
import fastavro.schema  # type: ignore[import-untyped]
import pytest

_SCHEMA_PATH = Path(__file__).parents[4] / "infra" / "kafka" / "schemas" / "alert.delivered.v1.avsc"


@pytest.fixture(scope="module")
def schema() -> dict:  # type: ignore[type-arg]
    return fastavro.schema.load_schema(_SCHEMA_PATH)  # type: ignore[return-value]


@pytest.mark.contract
def test_alert_delivered_has_severity_field(schema: dict) -> None:  # type: ignore[type-arg]
    """Schema loads and has a 'severity' field with default 'low'."""
    fields = {f["name"]: f for f in schema["fields"]}
    assert "severity" in fields, "severity field must be present in alert.delivered.v1"
    assert fields["severity"]["default"] == "low"


@pytest.mark.contract
def test_alert_delivered_schema_version_2(schema: dict) -> None:  # type: ignore[type-arg]
    """schema_version field default is 2 after Wave A-2 bump."""
    fields = {f["name"]: f for f in schema["fields"]}
    assert fields["schema_version"]["default"] == 2


@pytest.mark.contract
def test_alert_delivered_severity_forward_compat(schema: dict) -> None:  # type: ignore[type-arg]
    """Old record WITHOUT severity field deserializes with default 'low' applied."""
    # Simulate a record produced by the old schema (no severity field).
    # We write using a writer schema that lacks severity, then read with the
    # current reader schema — fastavro should fill the default.
    old_schema: dict = {  # type: ignore[type-arg]
        "type": "record",
        "name": "AlertDelivered",
        "namespace": "com.worldview",
        "fields": [
            {"name": "event_id", "type": "string"},
            {"name": "event_type", "type": "string", "default": "alert.delivered"},
            {"name": "schema_version", "type": "int", "default": 1},
            {"name": "occurred_at", "type": "string"},
            {"name": "alert_id", "type": "string"},
            {"name": "user_id", "type": "string"},
            {"name": "entity_id", "type": "string"},
            {"name": "alert_type", "type": "string"},
            {"name": "channel", "type": "string"},
            {"name": "correlation_id", "type": ["null", "string"], "default": None},
        ],
    }
    parsed_old = fastavro.schema.parse_schema(old_schema)

    record = {
        "event_id": "evt-001",
        "event_type": "alert.delivered",
        "schema_version": 1,
        "occurred_at": "2026-04-10T00:00:00Z",
        "alert_id": "alert-001",
        "user_id": "user-001",
        "entity_id": "entity-001",
        "alert_type": "SIGNAL",
        "channel": "websocket",
        "correlation_id": None,
    }

    # Serialize with old writer schema
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed_old, record)
    buf.seek(0)

    # Deserialize with new reader schema — severity default should be applied
    # writer_schema=parsed_old (1st positional), reader_schema=schema (keyword)
    result = fastavro.schemaless_reader(buf, parsed_old, reader_schema=schema)
    assert result["severity"] == "low", "missing severity must default to 'low'"


@pytest.mark.contract
def test_alert_delivered_roundtrip_with_severity(schema: dict) -> None:  # type: ignore[type-arg]
    """Record with severity='critical' serializes and deserializes correctly."""
    record = {
        "event_id": "evt-002",
        "event_type": "alert.delivered",
        "schema_version": 2,
        "occurred_at": "2026-04-10T00:00:00Z",
        "alert_id": "alert-002",
        "user_id": "user-002",
        "entity_id": "entity-002",
        "alert_type": "SIGNAL",
        "channel": "websocket",
        "correlation_id": None,
        "severity": "critical",
    }

    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    buf.seek(0)

    result = fastavro.schemaless_reader(buf, schema)
    assert result["severity"] == "critical"
    assert result["schema_version"] == 2
    assert result["alert_id"] == "alert-002"
