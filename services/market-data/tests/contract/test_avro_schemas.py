"""Contract tests for Avro schemas consumed by market-data (M-005).

Validates that the ``market.dataset.fetched`` Avro schema (consumed by the
OHLCV, quotes, and fundamentals consumers) contains all required envelope
fields, payload fields, and that new optional fields carry defaults
(forward-compatibility guarantee).

Uses ``fastavro`` to parse and validate the schemas at the binary protocol
level, catching schema issues that JSON-only tests would miss.

No containers needed — these run against schema files on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import fastavro
import pytest

pytestmark = pytest.mark.contract

# Path to the schemas directory relative to this test file.
_SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent.parent / "infra" / "kafka" / "schemas"
_MARKET_DATASET_FETCHED = _SCHEMAS_DIR / "market.dataset.fetched.avsc"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_schema(path: Path) -> dict:
    assert path.exists(), f"Schema file not found: {path}"
    return json.loads(path.read_text())


def _field_map(schema: dict) -> dict[str, dict]:
    return {f["name"]: f for f in schema["fields"]}


# ── TestMarketDatasetFetchedSchema ────────────────────────────────────────────


class TestMarketDatasetFetchedSchema:
    """Structural and forward-compatibility tests for market.dataset.fetched."""

    def test_schema_file_is_valid_json(self) -> None:
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        assert schema["type"] == "record"
        assert schema["name"] == "MarketDatasetFetched"
        assert schema["namespace"] == "market.events"

    def test_schema_is_parseable_by_fastavro(self) -> None:
        """fastavro.parse_schema must not raise — validates the schema structure."""
        schema_dict = _load_schema(_MARKET_DATASET_FETCHED)
        parsed = fastavro.parse_schema(schema_dict)
        assert parsed is not None

    def test_envelope_fields_present(self) -> None:
        """All standard envelope fields must be present."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        field_names = {f["name"] for f in schema["fields"]}
        required_envelope = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
        }
        missing = required_envelope - field_names
        assert not missing, f"Missing envelope fields: {missing}"

    def test_optional_envelope_fields_have_defaults(self) -> None:
        """Optional envelope fields (correlation_id, causation_id) must have defaults for forward-compat."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        fields = _field_map(schema)
        # These fields are nullable union types with a default of null
        for field_name in ("correlation_id", "causation_id"):
            assert field_name in fields, f"Field missing: {field_name}"
            assert "default" in fields[field_name], f"Field '{field_name}' has no default (breaks forward-compat)"

    def test_dataset_type_field_present(self) -> None:
        """dataset_type field must be present (ohlcv / quotes / fundamentals consumers rely on it)."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        field_names = {f["name"] for f in schema["fields"]}
        assert "dataset_type" in field_names

    def test_claim_check_fields_present(self) -> None:
        """All claim-check reference fields must be present for consumer retrieval."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        field_names = {f["name"] for f in schema["fields"]}
        required_refs = {
            "bronze_ref_bucket",
            "bronze_ref_key",
            "bronze_ref_sha256",
            "bronze_ref_byte_length",
            "bronze_ref_mime_type",
            "canonical_ref_bucket",
            "canonical_ref_key",
            "canonical_ref_sha256",
            "canonical_ref_byte_length",
            "canonical_ref_mime_type",
        }
        missing = required_refs - field_names
        assert not missing, f"Missing claim-check fields: {missing}"

    def test_byte_length_fields_are_long_type(self) -> None:
        """Byte-length fields must be Avro ``long`` (64-bit) to avoid overflow on large files."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        fields = _field_map(schema)
        assert fields["bronze_ref_byte_length"]["type"] == "long"
        assert fields["canonical_ref_byte_length"]["type"] == "long"

    def test_optional_fields_have_null_default(self) -> None:
        """Optional union fields that allow null must default to null (forward-compat)."""
        schema = _load_schema(_MARKET_DATASET_FETCHED)
        fields = _field_map(schema)
        nullable_fields = ("exchange", "timeframe", "variant", "range_start", "range_end", "row_count")
        for name in nullable_fields:
            assert name in fields, f"Expected optional field '{name}' not found"
            field = fields[name]
            assert "default" in field, f"Nullable field '{name}' has no default (breaks forward-compat)"
            assert field["default"] is None, f"Nullable field '{name}' default is not null"

    def test_schema_roundtrip_with_fastavro(self) -> None:
        """A minimal valid record must serialise and deserialise without error."""
        import io

        schema_dict = _load_schema(_MARKET_DATASET_FETCHED)
        parsed = fastavro.parse_schema(schema_dict)

        record = {
            "event_id": "01906b14-3d4e-7000-8000-000000000001",
            "event_type": "market.dataset.fetched",
            "schema_version": 1,
            "occurred_at": "2024-01-15T10:00:00Z",
            "correlation_id": None,
            "causation_id": None,
            "task_id": "task-001",
            "provider": "eodhd",
            "dataset_type": "ohlcv",
            "symbol": "AAPL",
            "exchange": "US",
            "timeframe": "1d",
            "variant": None,
            "range_start": "2024-01-01",
            "range_end": "2024-01-15",
            "bronze_ref_bucket": "bronze",
            "bronze_ref_key": "aapl/ohlcv.json",
            "bronze_ref_sha256": "abc123",
            "bronze_ref_byte_length": 1024,
            "bronze_ref_mime_type": "application/json",
            "canonical_ref_bucket": "canonical",
            "canonical_ref_key": "aapl/ohlcv.jsonl",
            "canonical_ref_sha256": "def456",
            "canonical_ref_byte_length": 512,
            "canonical_ref_mime_type": "application/x-ndjson",
            "canonical_schema_version": 1,
            "row_count": 15,
        }

        buf = io.BytesIO()
        fastavro.writer(buf, parsed, [record])
        buf.seek(0)
        records = list(fastavro.reader(buf))
        assert len(records) == 1
        assert records[0]["event_id"] == record["event_id"]
        assert records[0]["dataset_type"] == "ohlcv"
