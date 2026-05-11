"""Contract tests for ``CanonicalIntelligenceContradiction`` ↔ ``intelligence.contradiction.v1.avsc``.

PLAN-0062 Wave C.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.intelligence.contradiction import CanonicalIntelligenceContradiction

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "intelligence.contradiction.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalIntelligenceContradiction:
    base = {
        "event_id": "01900000-0000-7000-0000-000000000030",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "subject_entity_id": "01234567-89ab-7def-8012-345678901234",
        "claim_type": "analyst_rating",
        "new_claim_id": "01234567-89ab-7def-8012-aaaaaaaaaaaa",
        "contradicting_claim_id": "01234567-89ab-7def-8012-bbbbbbbbbbbb",
        "contradiction_strength": 0.6,
        "affected_relation_ids": ("01234567-89ab-7def-8012-cccccccccccc",),
        "is_backfill": False,
    }
    base.update(overrides)
    return CanonicalIntelligenceContradiction(**base)  # type: ignore[arg-type]


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
                assert f.get("default", "MISSING") is None
                return
        pytest.fail("correlation_id missing from schema")

    def test_event_type_default_matches_constant(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "event_type":
                assert f.get("default") == "intelligence.contradiction"
                return
        pytest.fail("event_type missing from schema")


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(correlation_id="01234567-89ab-7def-8012-dddddddddddd")
        round_tripped = CanonicalIntelligenceContradiction.from_dict(original.to_dict())
        assert round_tripped == original


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample()
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["subject_entity_id"] == sample.subject_entity_id
        assert decoded["claim_type"] == "analyst_rating"
        assert decoded["contradiction_strength"] == pytest.approx(0.6)
        assert list(decoded["affected_relation_ids"]) == list(sample.affected_relation_ids)
