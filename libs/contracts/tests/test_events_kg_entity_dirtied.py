"""Contract tests for ``CanonicalEntityDirtied`` ↔ ``entity.dirtied.v1.avsc``.

PLAN-0062 QA-iter1 audit follow-up (ARCH-008).  Mirrors the alignment style of
``test_events_kg_entity_canonical_created.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.kg.entity_dirtied import CanonicalEntityDirtied

pytestmark = pytest.mark.contract

_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "entity.dirtied.v1.avsc"


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalEntityDirtied:
    base = {
        "event_id": "01900000-0000-7000-0000-000000000010",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "entity_id": "01234567-89ab-7def-8012-345678901234",
        "dirty_reason": "new_evidence",
    }
    base.update(overrides)
    return CanonicalEntityDirtied(**base)  # type: ignore[arg-type]


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

    def test_source_doc_id_is_nullable(self) -> None:
        schema = _load_schema()
        for f in schema["fields"]:
            if f["name"] == "source_doc_id":
                assert isinstance(f["type"], list) and "null" in f["type"]
                assert f.get("default", "MISSING") is None
                return
        pytest.fail("source_doc_id missing from schema")

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
                assert f.get("default") == "entity.dirtied"
                return
        pytest.fail("event_type missing from schema")

    def test_dirty_reason_field_exists(self) -> None:
        schema = _load_schema()
        field_names = {f["name"] for f in schema["fields"]}
        assert "dirty_reason" in field_names


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            source_doc_id="01234567-89ab-7def-8012-aaaaaaaaaaaa",
            correlation_id="01234567-89ab-7def-8012-bbbbbbbbbbbb",
        )
        round_tripped = CanonicalEntityDirtied.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_handles_optional_nulls(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000010",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "entity_id": "01234567-89ab-7def-8012-345678901234",
            "dirty_reason": "profile_updated",
            "source_doc_id": None,
            "correlation_id": None,
        }
        model = CanonicalEntityDirtied.from_dict(d)
        assert model.source_doc_id is None
        assert model.correlation_id is None
        assert model.event_type == "entity.dirtied"
        assert model.schema_version == 1

    def test_from_dict_accepts_all_dirty_reason_values(self) -> None:
        for reason in ("new_evidence", "new_relation", "alias_added", "profile_updated"):
            model = CanonicalEntityDirtied.from_dict(
                {
                    "event_id": "01900000-0000-7000-0000-000000000010",
                    "occurred_at": "2026-05-03T12:00:00+00:00",
                    "entity_id": "01234567-89ab-7def-8012-345678901234",
                    "dirty_reason": reason,
                }
            )
            assert model.dirty_reason == reason


# ---------------------------------------------------------------------------
# Avro round-trip via fastavro
# ---------------------------------------------------------------------------


class TestAvroSerialization:
    def test_to_dict_serializes_with_fastavro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample(dirty_reason="new_evidence", source_doc_id="01234567-89ab-7def-8012-aaaaaaaaaaaa")
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["entity_id"] == sample.entity_id
        assert decoded["dirty_reason"] == sample.dirty_reason
        assert decoded["source_doc_id"] == sample.source_doc_id
        assert decoded["correlation_id"] is None

    def test_nullable_fields_serialize_as_none_with_fastavro(self) -> None:
        import io

        import fastavro

        schema = fastavro.parse_schema(_load_schema())
        sample = _sample()  # source_doc_id and correlation_id are None
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["source_doc_id"] is None
        assert decoded["correlation_id"] is None
