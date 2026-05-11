"""Contract tests — nlp.signal.detected.v1 Avro schema.

Verifies backward-compatibility of the market_impact_score field addition (PRD-0020 §6.3).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import fastavro
import pytest

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "nlp.signal.detected.v1.avsc"
)

# Minimal old-schema message — no market_impact_score field
_OLD_RECORD = {
    "event_id": "01JQ000000000000000000",
    "event_type": "nlp.signal.detected",
    "schema_version": 1,
    "occurred_at": "2026-04-09T10:00:00Z",
    "doc_id": "01JQ000000000000000001",
    "claim_id": "01JQ000000000000000002",
    "claimer_entity_id": None,
    "subject_entity_id": "01JQ000000000000000003",
    "claim_type": "factual",
    "polarity": "positive",
    "extraction_confidence": 0.92,
    "is_backfill": False,
    "correlation_id": None,
}

# Old Avro schema without market_impact_score (13 fields)
_OLD_SCHEMA_DICT = {
    "type": "record",
    "name": "NlpSignalDetected",
    "namespace": "com.worldview",
    "fields": [
        {"name": "event_id", "type": "string"},
        {"name": "event_type", "type": "string", "default": "nlp.signal.detected"},
        {"name": "schema_version", "type": "int", "default": 1},
        {"name": "occurred_at", "type": "string"},
        {"name": "doc_id", "type": "string"},
        {"name": "claim_id", "type": "string"},
        {"name": "claimer_entity_id", "type": ["null", "string"], "default": None},
        {"name": "subject_entity_id", "type": ["null", "string"], "default": None},
        {"name": "claim_type", "type": "string"},
        {"name": "polarity", "type": "string"},
        {"name": "extraction_confidence", "type": "float"},
        {"name": "is_backfill", "type": "boolean", "default": False},
        {"name": "correlation_id", "type": ["null", "string"], "default": None},
    ],
}


def _load_current_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _serialize(schema_dict: dict, record: dict) -> bytes:
    parsed = fastavro.parse_schema(schema_dict)
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, record)
    return buf.getvalue()


def _deserialize(schema_dict: dict, data: bytes) -> dict:
    parsed = fastavro.parse_schema(schema_dict)
    buf = io.BytesIO(data)
    return fastavro.schemaless_reader(buf, parsed)  # type: ignore[return-value]


@pytest.mark.contract
class TestSignalDetectedV1Schema:
    def test_signal_detected_v1_backward_compatible(self) -> None:
        """Old messages (no market_impact_score) can be deserialized with the new schema."""
        current_schema = _load_current_schema()

        # Serialize with OLD schema (no market_impact_score)
        payload = _serialize(_OLD_SCHEMA_DICT, _OLD_RECORD)

        # Deserialize with NEW schema (reader) against old writer — must not raise
        writer = fastavro.parse_schema(_OLD_SCHEMA_DICT)
        reader = fastavro.parse_schema(current_schema)
        buf = io.BytesIO(payload)
        result = fastavro.schemaless_reader(buf, writer, reader)
        assert result is not None

    def test_signal_detected_v1_new_field_defaults(self) -> None:
        """Old messages deserialized with the new schema receive market_impact_score = 0.0."""
        current_schema = _load_current_schema()

        # Serialize with old schema
        payload = _serialize(_OLD_SCHEMA_DICT, _OLD_RECORD)

        # Deserialize with new schema using writer/reader schema evolution
        writer = fastavro.parse_schema(_OLD_SCHEMA_DICT)
        reader = fastavro.parse_schema(current_schema)
        buf = io.BytesIO(payload)
        result = fastavro.schemaless_reader(buf, writer, reader)

        assert result["market_impact_score"] == 0.0

    def test_signal_detected_v1_serialise_with_score(self) -> None:
        """Signal with market_impact_score=0.75 serialises and deserialises correctly."""
        current_schema = _load_current_schema()

        record_with_score = {**_OLD_RECORD, "market_impact_score": 0.75}
        payload = _serialize(current_schema, record_with_score)

        result = _deserialize(current_schema, payload)
        assert abs(result["market_impact_score"] - 0.75) < 1e-9
        assert result["doc_id"] == _OLD_RECORD["doc_id"]
        assert result["polarity"] == "positive"
