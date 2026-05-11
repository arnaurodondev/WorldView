"""Contract tests for ``CanonicalGraphStateChanged`` ↔ ``graph.state.changed.v1.avsc``.

PLAN-0062 audit follow-up F-006.  Mirrors the alignment style of
``test_events_kg_provisional_queued.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.events.kg.graph_state_changed import CanonicalGraphStateChanged

pytestmark = pytest.mark.contract

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "graph.state.changed.v1.avsc"
)


def _load_schema() -> dict:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample(**overrides: object) -> CanonicalGraphStateChanged:
    base: dict[str, object] = {
        "event_id": "01900000-0000-7000-0000-000000000030",
        "occurred_at": "2026-05-03T12:00:00+00:00",
        "primary_entity_id": "01234567-89ab-7def-8012-000000000001",
        "affected_entity_ids": (
            "01234567-89ab-7def-8012-000000000001",
            "01234567-89ab-7def-8012-000000000002",
        ),
        "change_type": "new_evidence",
    }
    base.update(overrides)
    return CanonicalGraphStateChanged(**base)  # type: ignore[arg-type]


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

    def test_optional_fields_have_null_default(self) -> None:
        """Nullable string fields must be Avro unions w/ default null."""
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
                assert f.get("default") == "graph.state.changed"
                return
        pytest.fail("Avro schema is missing the event_type field")

    def test_array_fields_default_empty_list(self) -> None:
        """relation_ids and canonical_types must default to empty arrays."""
        schema = _load_schema()
        defaulted = {"relation_ids", "canonical_types"}
        for f in schema["fields"]:
            if f["name"] in defaulted:
                assert f.get("default") == [], f"{f['name']} must default to []"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_from_dict_to_dict_preserves_payload(self) -> None:
        original = _sample(
            relation_ids=("01234567-89ab-7def-8012-aaaaaaaaaaaa",),
            canonical_types=("acquired", "produces"),
            source_doc_id="01234567-89ab-7def-8012-cccccccccccc",
            is_backfill=True,
            correlation_id="01234567-89ab-7def-8012-dddddddddddd",
        )
        round_tripped = CanonicalGraphStateChanged.from_dict(original.to_dict())
        assert round_tripped == original

    def test_from_dict_handles_optional_nulls_and_empty_arrays(self) -> None:
        d = {
            "event_id": "01900000-0000-7000-0000-000000000030",
            "occurred_at": "2026-05-03T12:00:00+00:00",
            "primary_entity_id": "01234567-89ab-7def-8012-000000000001",
            "affected_entity_ids": [],
            "change_type": "confidence_update",
            "relation_ids": [],
            "canonical_types": [],
            "source_doc_id": None,
            "is_backfill": False,
            "correlation_id": None,
        }
        model = CanonicalGraphStateChanged.from_dict(d)
        assert model.affected_entity_ids == ()
        assert model.relation_ids == ()
        assert model.canonical_types == ()
        assert model.source_doc_id is None
        assert model.is_backfill is False
        assert model.correlation_id is None
        # defaults baked in
        assert model.event_type == "graph.state.changed"
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
            relation_ids=("01234567-89ab-7def-8012-aaaaaaaaaaaa",),
            canonical_types=("acquired", "produces"),
            source_doc_id="01234567-89ab-7def-8012-cccccccccccc",
            is_backfill=True,
        )
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, sample.to_dict())
        buf.seek(0)
        decoded = fastavro.schemaless_reader(buf, schema, None)

        assert decoded["primary_entity_id"] == sample.primary_entity_id
        assert list(decoded["affected_entity_ids"]) == list(sample.affected_entity_ids)
        assert list(decoded["relation_ids"]) == list(sample.relation_ids)
        assert list(decoded["canonical_types"]) == list(sample.canonical_types)
        assert decoded["change_type"] == sample.change_type
        assert decoded["is_backfill"] is True
