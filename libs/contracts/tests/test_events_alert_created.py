"""Contract tests for ``CanonicalAlertCreated`` ↔ ``alert.created.v1.avsc``.

PLAN-0082 Wave B.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.alert.alert_created import CanonicalAlertCreated

pytestmark = pytest.mark.contract

_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "alert.created.v1.avsc"


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalAlertCreated:
    base: dict[str, object] = {
        "event_id": "01900000-0000-7000-0000-000000000082",
        "occurred_at": "2026-05-09T10:00:00+00:00",
        "alert_id": "01900000-0000-7000-0000-000000000083",
        "user_id": "01900000-0000-7000-0000-000000000001",
        "tenant_id": "01900000-0000-7000-0000-000000000002",
        "entity_id": "01900000-0000-7000-0000-000000000003",
        "condition": "price_below",
        "threshold": '{"value": 200.0}',
    }
    base.update(overrides)
    return CanonicalAlertCreated(**base)  # type: ignore[arg-type]


class TestSchemaAlignment:
    def test_avro_schema_field_set_matches_to_dict(self) -> None:
        schema = _load_schema()
        avro_fields = {f["name"] for f in schema["fields"]}
        emitted = set(_sample().to_dict().keys())
        assert (
            avro_fields == emitted
        ), f"In Avro only: {avro_fields - emitted}\n  In to_dict only: {emitted - avro_fields}"

    def test_correlation_id_is_nullable(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "correlation_id":
                assert isinstance(f["type"], list) and "null" in f["type"]
                assert f.get("default") is None
                return
        pytest.fail("correlation_id missing from schema")

    def test_event_type_default_matches_constant(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "event_type":
                assert f.get("default") == "alert.created"
                return
        pytest.fail("event_type missing from schema")

    def test_severity_default_is_low(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "severity":
                assert f.get("default") == "low"
                return
        pytest.fail("severity missing from schema")

    def test_source_default_is_llm_tool(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "source":
                assert f.get("default") == "llm_tool"
                return
        pytest.fail("source missing from schema")


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            severity="high",
            source="llm_tool",
            correlation_id="01900000-0000-7000-0000-000000000099",
        )
        round_tripped = CanonicalAlertCreated.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_to_dict_with_null_correlation(self) -> None:
        original = _sample()
        assert original.correlation_id is None
        round_tripped = CanonicalAlertCreated.from_dict(original.to_dict())
        assert round_tripped.correlation_id is None

    def test_defaults_preserved_across_round_trip(self) -> None:
        obj = _sample()
        assert obj.severity == "low"
        assert obj.source == "llm_tool"
        assert obj.event_type == "alert.created"
        assert obj.schema_version == 1

    def test_condition_and_threshold_preserved(self) -> None:
        obj = _sample(condition="price_above", threshold='{"value": 300.0}')
        d = obj.to_dict()
        assert d["condition"] == "price_above"
        assert d["threshold"] == '{"value": 300.0}'
        restored = CanonicalAlertCreated.from_dict(d)
        assert restored.condition == "price_above"
        assert restored.threshold == '{"value": 300.0}'


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(severity="medium", source="llm_tool")
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["alert_id"] == sample.alert_id
        assert decoded["user_id"] == sample.user_id
        assert decoded["condition"] == "price_below"
        assert json.loads(decoded["threshold"]) == {"value": 200.0}
        assert decoded["severity"] == "medium"
        assert decoded["source"] == "llm_tool"
        assert decoded["correlation_id"] is None

    def test_nullable_correlation_id_round_trips_through_avro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(correlation_id="01900000-0000-7000-0000-000000000099")
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)
        assert decoded["correlation_id"] == "01900000-0000-7000-0000-000000000099"
