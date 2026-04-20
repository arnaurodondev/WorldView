"""Contract tests: validate all Avro schemas parse correctly, have required envelope fields,
and match expected field counts per PRD-0001 §6.3.2.

These tests run without any infrastructure — just schema files on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import fastavro
import pytest

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "infra" / "kafka" / "schemas"

# Envelope fields required by every event schema (AGENTS.md §9)
ENVELOPE_FIELDS = {"event_id", "event_type", "schema_version", "occurred_at"}

# Expected field counts per schema (from PRD-0001 §6.3.2)
EXPECTED_FIELD_COUNTS: dict[str, int] = {
    "content.article.raw.v1": 14,
    "content.article.stored.v1": 15,
    "nlp.article.enriched.v1": 20,
    "nlp.signal.detected.v1": 14,
    "graph.state.changed.v1": 12,
    "intelligence.contradiction.v1": 12,
    "entity.dirtied.v1": 8,
    "entity.canonical.created.v1": 10,
    "relation.type.proposed.v1": 12,  # Existing: 12 fields (richer than PRD minimum)
    "alert.delivered.v1": 11,
    "market.instrument.created": 15,  # Enhanced with name, description, isin, security_id, entity_id, causation_id
    "market.instrument.updated": 14,
    "market.dataset.fetched": 27,  # Existing mature schema: 27 fields (claim-check pattern)
    "portfolio.events.v1": 10,  # 10 record types in multi-record schema file
    "portfolio.watchlist.updated.v1": 9,
    "watchlist.item_added": 13,
    "watchlist.item_deleted": 13,
}


def _all_avsc_files() -> list[Path]:
    """Collect all .avsc files in the schema directory."""
    return sorted(SCHEMA_DIR.glob("*.avsc"))


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_name(path: Path) -> str:
    return path.stem


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestAllAvroSchemasValid:
    """Every .avsc file must parse as valid Avro."""

    @pytest.mark.parametrize("schema_path", _all_avsc_files(), ids=_schema_name)
    def test_schema_parses(self, schema_path: Path) -> None:
        schema = _load_schema(schema_path)
        parsed = fastavro.parse_schema(schema)
        assert parsed is not None


@pytest.mark.contract
class TestEnvelopeFieldsPresent:
    """All event schemas must include the standard envelope fields."""

    @pytest.mark.parametrize("schema_path", _all_avsc_files(), ids=_schema_name)
    def test_envelope_fields(self, schema_path: Path) -> None:
        schema = _load_schema(schema_path)
        # Multi-record schemas (array of record definitions) — validate each record.
        records = schema if isinstance(schema, list) else [schema]
        for record in records:
            field_names = {f["name"] for f in record.get("fields", [])}
            missing = ENVELOPE_FIELDS - field_names
            record_name = record.get("name", schema_path.name)
            assert not missing, f"{schema_path.name} record '{record_name}' missing envelope fields: {missing}"


@pytest.mark.contract
class TestSchemaFieldCounts:
    """Each schema has the expected number of fields per PRD-0001 §6.3.2."""

    @pytest.mark.parametrize(
        ("schema_name", "expected_count"),
        EXPECTED_FIELD_COUNTS.items(),
        ids=list(EXPECTED_FIELD_COUNTS.keys()),
    )
    def test_field_count(self, schema_name: str, expected_count: int) -> None:
        schema_path = SCHEMA_DIR / f"{schema_name}.avsc"
        if not schema_path.exists():
            pytest.skip(f"Schema {schema_name}.avsc not found")
        schema = _load_schema(schema_path)
        # Multi-record schemas: count the number of record types in the array.
        if isinstance(schema, list):
            actual = len(schema)
            assert actual == expected_count, (
                f"{schema_name}: expected {expected_count} record types, got {actual}. "
                f"Records: {[r.get('name') for r in schema]}"
            )
        else:
            actual = len(schema.get("fields", []))
            assert actual == expected_count, (
                f"{schema_name}: expected {expected_count} fields, got {actual}. "
                f"Fields: {[f['name'] for f in schema.get('fields', [])]}"
            )


@pytest.mark.contract
class TestEntityCanonicalCreatedSchema:
    """Specific validation for the new entity.canonical.created.v1 schema."""

    def test_schema_exists(self) -> None:
        path = SCHEMA_DIR / "entity.canonical.created.v1.avsc"
        assert path.exists(), "entity.canonical.created.v1.avsc must exist"

    def test_has_alias_texts_array(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "entity.canonical.created.v1.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        assert "alias_texts" in fields_by_name
        field = fields_by_name["alias_texts"]
        assert field["type"]["type"] == "array"
        assert field["type"]["items"] == "string"

    def test_has_provisional_queue_id(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "entity.canonical.created.v1.avsc")
        field_names = {f["name"] for f in schema["fields"]}
        assert "provisional_queue_id" in field_names

    def test_valid_sample_roundtrip(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "entity.canonical.created.v1.avsc")
        parsed = fastavro.parse_schema(schema)
        import io

        sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "entity.canonical.created",
            "schema_version": 1,
            "occurred_at": "2026-03-25T12:00:00Z",
            "entity_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "canonical_name": "Apple Inc",
            "entity_type": "organization",
            "provisional_queue_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d1",
            "alias_texts": ["Apple", "AAPL", "Apple Computer"],
            "correlation_id": None,
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        assert rows[0]["alias_texts"] == ["Apple", "AAPL", "Apple Computer"]


@pytest.mark.contract
class TestConfluentWireFormatRoundtrip:
    """Validate the Confluent wire-format path: serialize → prepend header → deserialize."""

    # Minimal valid sample records keyed by schema stem name.
    # Only schemas whose full mandatory fields are known here are tested; the
    # parametrize list can be extended as schemas evolve.
    _SAMPLES: ClassVar[dict[str, dict]] = {
        "content.article.stored.v1": {
            "event_id": "018f4a00-0000-7000-0000-000000000001",
            "event_type": "content.article.stored",
            "schema_version": 1,
            "occurred_at": "2026-04-08T12:00:00Z",
            "doc_id": "018f4a00-0000-7000-0000-000000000002",
            "content_hash": "abc123",
            "normalized_hash": "def456",
            "dedup_result": "unique",
            "minio_silver_key": "silver/bucket/key",
            "source_type": "eodhd",
            "title": None,
            "word_count": None,
            "published_at": None,
            "is_backfill": False,
            "correlation_id": None,
        },
        "nlp.article.enriched.v1": {
            "event_id": "018f4a00-0000-7000-0000-000000000003",
            "event_type": "nlp.article.enriched",
            "schema_version": 1,
            "occurred_at": "2026-04-08T12:00:00Z",
            "doc_id": "018f4a00-0000-7000-0000-000000000004",
            "source_type": "eodhd",
            "published_at": None,
            "is_backfill": False,
            "routing_tier": "medium",
            "routing_score": 0.55,
            "section_count": 3,
            "chunk_count": 9,
            "mention_count": 5,
            "resolved_entity_ids": [],
            "relation_count": 0,
            "claim_count": 0,
            "event_count": 0,
            "provisional_entity_count": 2,
            "extraction_model_id": None,
            "correlation_id": None,
        },
    }

    @pytest.mark.parametrize("schema_name", list(_SAMPLES.keys()))
    def test_confluent_roundtrip(self, schema_name: str) -> None:
        """Schema can serialize a sample record, prepend Confluent header, and decode."""
        import io
        import struct

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_path = SCHEMA_DIR / f"{schema_name}.avsc"
        if not schema_path.exists():
            pytest.skip(f"{schema_name}.avsc not found")

        schema_dict = _load_schema(schema_path)
        parsed = fastavro.parse_schema(schema_dict)
        record = self._SAMPLES[schema_name]

        # Schemaless encode
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed, record)
        payload = buf.getvalue()

        # Prepend Confluent header: 0x00 (magic) + 4-byte big-endian schema_id
        schema_id = 1
        header = b"\x00" + struct.pack(">I", schema_id)
        confluent_bytes = header + payload

        decoded = deserialize_confluent_avro(str(schema_path), confluent_bytes)
        assert decoded["event_id"] == record["event_id"]
        assert decoded["event_type"] == record["event_type"]


@pytest.mark.contract
class TestMarketInstrumentCreatedEnhancement:
    """Validate the 3 new optional fields on market.instrument.created are BACKWARD compatible."""

    def test_new_fields_are_nullable_with_defaults(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}

        for field_name in ("name", "description", "isin"):
            assert field_name in fields_by_name, f"Missing field: {field_name}"
            field = fields_by_name[field_name]
            assert field["default"] is None, f"{field_name} must have default null for BACKWARD compat"
            assert ["null", "string"] == field["type"], f"{field_name} must be union [null, string]"

    def test_old_sample_still_valid(self) -> None:
        """A message produced by the OLD schema (without name/description/isin) must still decode."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        parsed = fastavro.parse_schema(schema)
        import io

        old_sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "market.instrument.created",
            "schema_version": 1,
            "occurred_at": "2026-03-25T12:00:00Z",
            "instrument_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "symbol": "AAPL",
            "exchange": "US",
            "instrument_type": "Common Stock",
            "correlation_id": None,
            # name, description, isin NOT provided — defaults to null
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [old_sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        assert rows[0]["name"] is None
        assert rows[0]["description"] is None
        assert rows[0]["isin"] is None
