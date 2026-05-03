"""Contract tests for ``CanonicalRelationTypeProposed`` ↔ ``relation.type.proposed.v1.avsc``.

PLAN-0062 audit follow-up F-006.  Mirrors the alignment style of
``test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.kg.relation_type_proposed import CanonicalRelationTypeProposed

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "relation.type.proposed.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalRelationTypeProposed:
    base: dict[str, object] = {
        "event_id": "01900000-0000-7000-0000-000000000020",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "proposed_type": "invented_by",
        "semantic_mode": "TEMPORAL_CLAIM",
    }
    base.update(overrides)
    return CanonicalRelationTypeProposed(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Field alignment
# ---------------------------------------------------------------------------


class TestSchemaAlignment:
    def test_avro_schema_field_set_matches_to_dict(self) -> None:
        """Every field in the Avro schema is produced by ``to_dict``."""
        schema = _load_schema()
        avro_fields = {f["name"] for f in schema["fields"]}
        emitted = set(_sample().to_dict().keys())

        assert avro_fields == emitted, (
            f"Avro schema fields and to_dict() output diverge.\n"
            f"  In Avro only: {avro_fields - emitted}\n"
            f"  In to_dict only: {emitted - avro_fields}"
        )

    def test_nullable_fields_have_null_default(self) -> None:
        """All optional fields in the Avro schema are nullable unions w/ default null."""
        schema = _load_schema()
        nullable = {
            "suggested_decay_class",
            "example_subject_entity_id",
            "example_object_entity_id",
            "example_evidence_text",
            "source_doc_id",
            "correlation_id",
        }
        for f in schema["fields"]:
            if f["name"] in nullable:
                assert (
                    isinstance(f["type"], list) and "null" in f["type"]
                ), f"{f['name']} must be a Avro union including 'null'"
                assert f.get("default", "MISSING") is None, f"{f['name']} must default to null"

    def test_event_type_default_matches_constant(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "event_type":
                assert f.get("default") == "relation.type.proposed"
                return
        pytest.fail("Avro schema is missing the event_type field")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            suggested_decay_class="permanent",
            example_subject_entity_id="01234567-89ab-7def-8012-aaaaaaaaaaaa",
            example_object_entity_id="01234567-89ab-7def-8012-bbbbbbbbbbbb",
            example_evidence_text="Acme invented the widget.",
            source_doc_id="01234567-89ab-7def-8012-cccccccccccc",
            correlation_id="01234567-89ab-7def-8012-dddddddddddd",
        )
        round_tripped = CanonicalRelationTypeProposed.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_handles_optional_nulls(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000020",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "proposed_type": "invented_by",
            "semantic_mode": "TEMPORAL_CLAIM",
            "suggested_decay_class": None,
            "example_subject_entity_id": None,
            "example_object_entity_id": None,
            "example_evidence_text": None,
            "source_doc_id": None,
            "correlation_id": None,
        }
        model = CanonicalRelationTypeProposed.from_dict(d)
        assert model.suggested_decay_class is None
        assert model.example_subject_entity_id is None
        assert model.source_doc_id is None
        assert model.correlation_id is None
        # defaults baked in
        assert model.event_type == "relation.type.proposed"
        assert model.schema_version == 1


# ---------------------------------------------------------------------------
# Avro schema validity (round-trip via fastavro)
# ---------------------------------------------------------------------------


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        """to_dict() output is acceptable to fastavro.schemaless_writer."""
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(
            suggested_decay_class="permanent",
            example_subject_entity_id="01234567-89ab-7def-8012-aaaaaaaaaaaa",
            example_object_entity_id="01234567-89ab-7def-8012-bbbbbbbbbbbb",
            example_evidence_text="Acme invented the widget.",
        )

        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["proposed_type"] == sample.proposed_type
        assert decoded["semantic_mode"] == sample.semantic_mode
        assert decoded["example_subject_entity_id"] == sample.example_subject_entity_id
        assert decoded["example_evidence_text"] == sample.example_evidence_text
