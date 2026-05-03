"""Contract tests for ``CanonicalEntityProvisionalQueued`` ↔ ``entity.provisional.queued.v1.avsc``.

PLAN-0062 Avro enforcement.  Mirrors the alignment style of
``test_avro_alignment.py`` but scoped to the new event model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.kg.provisional_queued import CanonicalEntityProvisionalQueued

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "entity.provisional.queued.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Field alignment
# ---------------------------------------------------------------------------


class TestSchemaAlignment:
    def test_avro_schema_field_set_matches_to_dict(self) -> None:
        """Every field in the Avro schema is produced by ``to_dict``."""
        schema = _load_schema()
        avro_fields = {f["name"] for f in schema["fields"]}

        sample = CanonicalEntityProvisionalQueued(
            event_id="01900000-0000-7000-0000-000000000001",
            occurred_at="2026-05-03T12:00:00+00:00",
            queue_id="01234567-89ab-7def-8012-000000000099",
            normalized_surface="apple inc.",
            mention_class="financial_instrument",
        )
        emitted = set(sample.to_dict().keys())

        assert avro_fields == emitted, (
            f"Avro schema fields and to_dict() output diverge.\n"
            f"  In Avro only: {avro_fields - emitted}\n"
            f"  In to_dict only: {emitted - avro_fields}"
        )

    def test_nullable_fields_have_null_default(self) -> None:
        """``source_doc_id`` and ``correlation_id`` must be nullable in the Avro schema."""
        schema = _load_schema()
        nullable = {"source_doc_id", "correlation_id"}
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
                assert f.get("default") == "entity.provisional.queued"
                return
        pytest.fail("Avro schema is missing the event_type field")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = CanonicalEntityProvisionalQueued(
            event_id="01900000-0000-7000-0000-000000000001",
            occurred_at="2026-05-03T12:00:00+00:00",
            queue_id="01234567-89ab-7def-8012-000000000099",
            normalized_surface="apple inc.",
            mention_class="financial_instrument",
            source_doc_id="01234567-89ab-7def-8012-aaaaaaaaaaaa",
            correlation_id="01234567-89ab-7def-8012-bbbbbbbbbbbb",
        )

        round_tripped = CanonicalEntityProvisionalQueued.from_dict(original.to_dict())

        assert round_tripped == original

    def test_from_dict_handles_optional_nulls(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000001",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "queue_id": "01234567-89ab-7def-8012-000000000099",
            "normalized_surface": "apple inc.",
            "mention_class": "financial_instrument",
            "source_doc_id": None,
            "correlation_id": None,
        }

        model = CanonicalEntityProvisionalQueued.from_dict(d)

        assert model.source_doc_id is None
        assert model.correlation_id is None
        # defaults baked in
        assert model.event_type == "entity.provisional.queued"
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
        sample = CanonicalEntityProvisionalQueued(
            event_id="01900000-0000-7000-0000-000000000001",
            occurred_at="2026-05-03T12:00:00+00:00",
            queue_id="01234567-89ab-7def-8012-000000000099",
            normalized_surface="apple inc.",
            mention_class="financial_instrument",
        )

        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        # Round-trip back
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["event_id"] == sample.event_id
        assert decoded["queue_id"] == sample.queue_id
        assert decoded["normalized_surface"] == sample.normalized_surface
        assert decoded["mention_class"] == sample.mention_class
