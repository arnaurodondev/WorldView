"""Contract tests for ``CanonicalEntityCanonicalCreated`` ↔ ``entity.canonical.created.v1.avsc``.

PLAN-0062 Wave A.  Mirrors the alignment style of
``test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.kg.entity_canonical_created import CanonicalEntityCanonicalCreated

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "entity.canonical.created.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalEntityCanonicalCreated:
    base = {
        "event_id": "01900000-0000-7000-0000-000000000010",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "entity_id": "01234567-89ab-7def-8012-345678901234",
        "canonical_name": "Apple Inc.",
        "entity_type": "financial_instrument",
        "provisional_queue_id": "01234567-89ab-7def-8012-000000000099",
        "alias_texts": ("apple", "AAPL"),
    }
    base.update(overrides)
    return CanonicalEntityCanonicalCreated(**base)  # type: ignore[arg-type]


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
                assert f.get("default") == "entity.canonical.created"
                return
        pytest.fail("event_type missing from schema")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(correlation_id="01234567-89ab-7def-8012-bbbbbbbbbbbb")
        round_tripped = CanonicalEntityCanonicalCreated.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_handles_optional_nulls_and_empty_aliases(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000010",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "entity_id": "01234567-89ab-7def-8012-345678901234",
            "canonical_name": "Acme Corp",
            "entity_type": "organization",
            "provisional_queue_id": "01234567-89ab-7def-8012-000000000099",
            "alias_texts": [],
            "correlation_id": None,
        }
        model = CanonicalEntityCanonicalCreated.from_dict(d)
        assert model.alias_texts == ()
        assert model.correlation_id is None
        assert model.event_type == "entity.canonical.created"
        assert model.schema_version == 1


# ---------------------------------------------------------------------------
# Avro round-trip via fastavro
# ---------------------------------------------------------------------------


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

        assert decoded["entity_id"] == sample.entity_id
        assert decoded["canonical_name"] == sample.canonical_name
        assert decoded["entity_type"] == sample.entity_type
        assert decoded["provisional_queue_id"] == sample.provisional_queue_id
        assert list(decoded["alias_texts"]) == list(sample.alias_texts)
