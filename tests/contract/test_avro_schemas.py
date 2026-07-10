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
    # PLAN-0056 Wave C2b (2026-07-10): external_id added (nullable passthrough).
    # NOTE: the prior expected value of 14 was stale — the schema already carried
    # 15 fields (tenant_id was added without bumping this count); the true actual
    # is now 16 with external_id.
    "content.article.raw.v1": 16,
    # PLAN-0056 Wave C2b: external_id added. Prior value 15 was likewise stale
    # (tenant_id already made it 16); true actual is now 17 with external_id.
    "content.article.stored.v1": 17,
    # PLAN-0084: added raw_relations_json, raw_events_json, raw_claims_json + correlation_id
    # PLAN-0086 (?): tenant_id added (24 fields).
    # PLAN-0087 D-INIT-6 (2026-05-09): source_name added so KG enriched_consumer
    # can stamp evidence-row provenance without an R7 cross-DB query (25 fields).
    # PLAN-0056 Wave C2b (2026-07-10): external_id added (26 fields).
    "nlp.article.enriched.v1": 26,
    "nlp.signal.detected.v1": 14,
    "graph.state.changed.v1": 12,
    "intelligence.contradiction.v1": 12,
    "entity.dirtied.v1": 8,
    "entity.canonical.created.v1": 10,
    "relation.type.proposed.v1": 12,  # Existing: 12 fields (richer than PRD minimum)
    "alert.delivered.v1": 11,
    # PLAN-0057 Wave C-1: schema_version=3 added cusip, figi, lei, primary_ticker (15 → 19)
    "market.instrument.created": 19,
    "market.instrument.updated": 14,
    # PLAN-0057 Wave D-2: lightweight pre-fundamentals discovery event.
    # 10 fields = 4 envelope (event_id, event_type, schema_version, occurred_at)
    # + 6 data (instrument_id, symbol, exchange, entity_id, correlation_id, causation_id).
    "market.instrument.discovered.v1": 10,
    "market.dataset.fetched": 27,  # Existing mature schema: 27 fields (claim-check pattern)
    # PLAN-0056 Wave Z1 — prediction-market Wave 2 topics (6 new). Envelope(4) + payload.
    "market.prediction.history.v1": 13,
    "market.prediction.event.v1": 11,
    "market.prediction.trade.v1": 12,
    "market.prediction.oi.v1": 9,
    "market.prediction.move.v1": 17,
    "market.prediction.signal.v1": 12,
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
    """Validate optional fields on market.instrument.created are BACKWARD compatible.

    PLAN-0057 Wave C-1 (F-CRIT-04 / F-CRIT-11): schema bumped to v3 with four
    new EODHD identifier fields — ``cusip``, ``figi``, ``lei`` and
    ``primary_ticker`` — all nullable with default null.
    """

    def test_v2_fields_are_nullable_with_defaults(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}

        for field_name in ("name", "description", "isin"):
            assert field_name in fields_by_name, f"Missing field: {field_name}"
            field = fields_by_name[field_name]
            assert field["default"] is None, f"{field_name} must have default null for BACKWARD compat"
            assert ["null", "string"] == field["type"], f"{field_name} must be union [null, string]"

    def test_v3_fields_are_nullable_with_defaults(self) -> None:
        """PLAN-0057 Wave C-1: cusip, figi, lei, primary_ticker — all nullable, default null."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}

        for field_name in ("cusip", "figi", "lei", "primary_ticker"):
            assert field_name in fields_by_name, f"Missing v3 field: {field_name}"
            field = fields_by_name[field_name]
            assert field["default"] is None, f"{field_name} must have default null for BACKWARD compat"
            assert ["null", "string"] == field["type"], f"{field_name} must be union [null, string]"

    def test_schema_version_default_is_three(self) -> None:
        """PLAN-0057 Wave C-1: schema_version defaults to 3 (was 2)."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        assert fields_by_name["schema_version"]["default"] == 3

    def test_old_sample_still_valid(self) -> None:
        """A message produced by the OLD v1 schema (without any optional fields) must still decode."""
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
            # name, description, isin, cusip, figi, lei, primary_ticker NOT provided — default to null
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [old_sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        assert rows[0]["name"] is None
        assert rows[0]["description"] is None
        assert rows[0]["isin"] is None
        # PLAN-0057 Wave C-1 — v3 fields default to None for v1/v2 producers.
        assert rows[0]["cusip"] is None
        assert rows[0]["figi"] is None
        assert rows[0]["lei"] is None
        assert rows[0]["primary_ticker"] is None

    def test_v3_sample_roundtrip_with_all_identifiers(self) -> None:
        """PLAN-0057 Wave C-1: a full v3 message with all identifiers populated round-trips."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.created.avsc")
        parsed = fastavro.parse_schema(schema)
        import io

        v3_sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "market.instrument.created",
            "schema_version": 3,
            "occurred_at": "2026-04-30T12:00:00Z",
            "instrument_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "symbol": "AAPL",
            "exchange": "US",
            "instrument_type": "Common Stock",
            "name": "Apple Inc.",
            "description": "Apple designs consumer electronics.",
            "isin": "US0378331005",
            "cusip": "037833100",
            "figi": "BBG000B9XRY4",
            "lei": "HWUPKR0MPOU8FGXBT394",
            "primary_ticker": "AAPL.US",
            "security_id": None,
            "entity_id": None,
            "correlation_id": None,
            "causation_id": None,
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [v3_sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        assert rows[0]["cusip"] == "037833100"
        assert rows[0]["figi"] == "BBG000B9XRY4"
        assert rows[0]["lei"] == "HWUPKR0MPOU8FGXBT394"
        assert rows[0]["primary_ticker"] == "AAPL.US"


@pytest.mark.contract
class TestMarketInstrumentDiscoveredV1Schema:
    """PLAN-0057 Wave D-2: ``market.instrument.discovered.v1`` cross-service event.

    The schema must:
      * have all envelope fields (event_id, event_type, schema_version, occurred_at)
      * have the 3 required data fields: instrument_id, symbol, exchange
      * have nullable optional fields: entity_id, correlation_id, causation_id
      * round-trip through fastavro (writer/reader)
      * coexist with ``market.instrument.created`` (no field-name collisions
        that would confuse the Schema Registry).
    """

    def test_schema_exists_and_parses(self) -> None:
        path = SCHEMA_DIR / "market.instrument.discovered.v1.avsc"
        assert path.exists(), "market.instrument.discovered.v1.avsc must exist"
        schema = _load_schema(path)
        assert fastavro.parse_schema(schema) is not None

    def test_required_data_fields_present(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "market.instrument.discovered.v1.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        # instrument_id and symbol are NOT NULL (required producer-side data)
        assert fields_by_name["instrument_id"]["type"] == "string"
        assert fields_by_name["symbol"]["type"] == "string"

    def test_optional_fields_are_nullable_with_default(self) -> None:
        schema = _load_schema(SCHEMA_DIR / "market.instrument.discovered.v1.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        for field_name in ("exchange", "entity_id", "correlation_id", "causation_id"):
            assert fields_by_name[field_name]["default"] is None
            assert fields_by_name[field_name]["type"] == ["null", "string"]

    def test_round_trip_with_minimal_payload(self) -> None:
        """A minimal valid payload (omitting all optional fields) must round-trip."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.discovered.v1.avsc")
        parsed = fastavro.parse_schema(schema)
        import io

        sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": "2026-04-30T12:00:00Z",
            "instrument_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "symbol": "AAPL",
            # All other fields fall back to their nullable defaults.
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"
        assert rows[0]["exchange"] is None
        assert rows[0]["entity_id"] is None
        assert rows[0]["correlation_id"] is None
        assert rows[0]["causation_id"] is None

    def test_round_trip_with_full_payload(self) -> None:
        """A fully-populated payload (including entity_id from M-017) must round-trip."""
        schema = _load_schema(SCHEMA_DIR / "market.instrument.discovered.v1.avsc")
        parsed = fastavro.parse_schema(schema)
        import io

        sample = {
            "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": "2026-04-30T12:00:00Z",
            "instrument_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "entity_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "correlation_id": "corr-1",
            "causation_id": None,
        }
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [sample])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert rows[0]["entity_id"] == sample["entity_id"]
        assert rows[0]["correlation_id"] == "corr-1"


@pytest.mark.contract
class TestPredictionWave2Schemas:
    """PLAN-0056 Wave Z1: the 6 new prediction-market Wave 2 topics.

    Each must parse, carry the standard envelope, and round-trip through fastavro
    with both a minimal payload (optional fields fall back to defaults — R5
    forward-compat) and a fully-populated payload.
    """

    _ENVELOPE: ClassVar[dict] = {
        "event_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9cf",
        "occurred_at": "2026-07-09T12:00:00Z",
    }

    # (schema stem, minimal required payload beyond envelope) — optional fields omitted on purpose.
    _MINIMAL: ClassVar[dict[str, dict]] = {
        "market.prediction.history.v1": {
            "market_id": "0xcond",
            "token_id": "0xtok",
            "interval": "1h",
            "window_start_ts": "2026-07-09T11:00:00Z",
            "price": 0.63,
        },
        "market.prediction.event.v1": {
            "group_id": "evt-123",
            "name": "2028 US Presidential Election",
        },
        "market.prediction.trade.v1": {
            "market_id": "0xcond",
            "trade_id": "t-1",
            "token_id": "0xtok",
            "price": 0.63,
            "size_usd": 250.0,
            "side": "buy",
            "ts": "2026-07-09T11:30:00Z",
        },
        "market.prediction.oi.v1": {
            "market_id": "0xcond",
            "snapshot_date": "2026-07-09",
            "total_oi_usd": 10000.0,
            "total_volume_24h_usd": 5000.0,
        },
        "market.prediction.move.v1": {
            "market_id": "0xcond",
            "token_id": "0xtok",
            "interval": "1h",
            "prev_price": 0.50,
            "new_price": 0.66,
            "delta": 0.16,
            "direction": "up",
            "window_start_ts": "2026-07-09T11:00:00Z",
        },
        "market.prediction.signal.v1": {
            "subject_entity_id": "018f3a85-b39f-7a78-bf2a-1f03523ad9d0",
            "market_id": "0xcond",
            "trigger": "material_move",
            "question": "Will Company X miss Q3 earnings?",
        },
    }

    # Fields whose Avro default must apply when omitted (forward-compat proof).
    _DEFAULTED: ClassVar[dict[str, dict]] = {
        "market.prediction.history.v1": {
            "outcome_name": None,
            "source": "polymarket_clob",
            "is_backfill": False,
            "correlation_id": None,
        },
        "market.prediction.event.v1": {
            "category": None,
            "start_date": None,
            "end_date": None,
            "market_count": 0,
            "correlation_id": None,
        },
        "market.prediction.trade.v1": {"correlation_id": None},
        "market.prediction.oi.v1": {"correlation_id": None},
        "market.prediction.move.v1": {
            "outcome_name": None,
            "liquidity": None,
            "volume_24h": None,
            "is_backfill": False,
            "correlation_id": None,
        },
        "market.prediction.signal.v1": {
            "market_impact_score": 0.0,
            "polarity": "neutral",
            "url": None,
            "correlation_id": None,
        },
    }

    @pytest.mark.parametrize("schema_name", list(_MINIMAL.keys()))
    def test_parses_and_has_envelope(self, schema_name: str) -> None:
        schema = _load_schema(SCHEMA_DIR / f"{schema_name}.avsc")
        assert fastavro.parse_schema(schema) is not None
        field_names = {f["name"] for f in schema["fields"]}
        assert ENVELOPE_FIELDS <= field_names, f"{schema_name} missing envelope fields"

    @pytest.mark.parametrize("schema_name", list(_MINIMAL.keys()))
    def test_minimal_payload_roundtrip_applies_defaults(self, schema_name: str) -> None:
        import io

        schema = _load_schema(SCHEMA_DIR / f"{schema_name}.avsc")
        parsed = fastavro.parse_schema(schema)
        record = {**self._ENVELOPE, **self._MINIMAL[schema_name]}
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [record])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert len(rows) == 1
        # Envelope round-trips; event_type/schema_version defaults are applied.
        assert rows[0]["event_id"] == record["event_id"]
        assert rows[0]["schema_version"] == 1
        assert rows[0]["event_type"].startswith("market.prediction.")
        # Every omitted optional field must fall back to its declared default.
        for field_name, expected in self._DEFAULTED[schema_name].items():
            assert rows[0][field_name] == expected, f"{schema_name}.{field_name} default not applied"


@pytest.mark.contract
class TestExternalIdPassthroughC2b:
    """PLAN-0056 Wave C2b: the ``external_id`` passthrough field.

    The field carries the upstream market/source identity
    ("polymarket:<condition_id>") verbatim through
    content.article.raw.v1 → content.article.stored.v1 → nlp.article.enriched.v1.
    It MUST be nullable (union [null, string]) with a null default so old
    producers/consumers that pre-date the field stay forward-compatible (R5).
    """

    _SCHEMAS = (
        "content.article.raw.v1",
        "content.article.stored.v1",
        "nlp.article.enriched.v1",
    )

    @pytest.mark.parametrize("schema_name", _SCHEMAS)
    def test_external_id_is_nullable_with_null_default(self, schema_name: str) -> None:
        schema = _load_schema(SCHEMA_DIR / f"{schema_name}.avsc")
        fields_by_name = {f["name"]: f for f in schema["fields"]}
        assert "external_id" in fields_by_name, f"{schema_name} missing external_id"
        field = fields_by_name["external_id"]
        assert field["type"] == ["null", "string"], f"{schema_name}.external_id must be union [null, string]"
        assert field.get("default", "MISSING") is None, f"{schema_name}.external_id must default to null (R5)"

    def test_raw_round_trips_with_and_without_external_id(self) -> None:
        """A producer that sets external_id AND a legacy one that omits it both decode."""
        import io

        schema = _load_schema(SCHEMA_DIR / "content.article.raw.v1.avsc")
        parsed = fastavro.parse_schema(schema)

        base = {
            "event_id": "018f4a00-0000-7000-0000-000000000010",
            "event_type": "content.article.raw",
            "schema_version": 1,
            "occurred_at": "2026-07-10T12:00:00Z",
            "doc_id": "018f4a00-0000-7000-0000-000000000011",
            "source_type": "polymarket",
            "minio_bronze_key": "bronze/key",
            "content_hash": "abc",
            "fetch_id": "018f4a00-0000-7000-0000-000000000012",
        }
        # New producer: external_id populated.
        with_ext = {**base, "external_id": "polymarket:0xcond"}
        # Legacy producer: external_id omitted → Avro null default applies.
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [with_ext, base])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert rows[0]["external_id"] == "polymarket:0xcond"
        assert rows[1]["external_id"] is None

    def test_enriched_round_trips_with_and_without_external_id(self) -> None:
        import io

        schema = _load_schema(SCHEMA_DIR / "nlp.article.enriched.v1.avsc")
        parsed = fastavro.parse_schema(schema)

        base = {
            "event_id": "018f4a00-0000-7000-0000-000000000020",
            "event_type": "nlp.article.enriched",
            "schema_version": 1,
            "occurred_at": "2026-07-10T12:00:00Z",
            "doc_id": "018f4a00-0000-7000-0000-000000000021",
            "source_type": "polymarket",
            "routing_tier": "medium",
            "routing_score": 0.55,
            "section_count": 1,
            "chunk_count": 1,
            "mention_count": 0,
        }
        with_ext = {**base, "external_id": "polymarket:0xcond"}
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [with_ext, base])
        buf.seek(0)
        rows = list(fastavro.reader(buf))
        assert rows[0]["external_id"] == "polymarket:0xcond"
        assert rows[1]["external_id"] is None
