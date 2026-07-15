"""Tests for Avro schema utilities (T-032 / schemas.py)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

import fastavro
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from datetime import UTC

from messaging.kafka.serialization_utils import (
    decimal_to_str,
    deserialize_avro,
    iso_datetime,
    load_schema,
    serialize_avro,
)

_SIMPLE_SCHEMA: dict = {
    "type": "record",
    "name": "TestRecord",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "value", "type": "double"},
    ],
}

_PARSED_SCHEMA = fastavro.parse_schema(_SIMPLE_SCHEMA)


class TestLoadSchema:
    def test_loads_valid_avsc(self, tmp_path: Path) -> None:
        schema_file = tmp_path / "test.avsc"
        schema_file.write_text(json.dumps(_SIMPLE_SCHEMA))
        result = load_schema(str(schema_file))
        assert isinstance(result, dict)

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_schema("/nonexistent/path/schema.avsc")

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:  # type: ignore[type-arg]
        bad_file = tmp_path / "bad.avsc"
        bad_file.write_text("{ not valid json }")
        with pytest.raises(json.JSONDecodeError):
            load_schema(str(bad_file))


class TestSerializeDeserializeAvro:
    def test_roundtrip(self) -> None:
        record = {"id": "test-id", "value": 42.5}
        serialized = serialize_avro(_PARSED_SCHEMA, record)
        assert isinstance(serialized, bytes)
        deserialized = deserialize_avro(_PARSED_SCHEMA, serialized)
        assert deserialized["id"] == "test-id"
        assert deserialized["value"] == pytest.approx(42.5)

    def test_serialize_returns_bytes(self) -> None:
        record = {"id": "abc", "value": 1.0}
        result = serialize_avro(_PARSED_SCHEMA, record)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_deserialize_empty_bytes_raises(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            deserialize_avro(_PARSED_SCHEMA, b"")

    def test_schema_validation_on_missing_required_field(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            serialize_avro(_PARSED_SCHEMA, {"id": "only-id"})


class TestIsoDatetime:
    def test_naive_datetime(self) -> None:
        from datetime import datetime

        dt = datetime(2024, 1, 15, 12, 0, 0)  # noqa: DTZ001
        result = iso_datetime(dt)
        assert "2024-01-15" in result
        assert "12:00:00" in result

    def test_aware_datetime(self) -> None:
        from datetime import datetime

        dt = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
        result = iso_datetime(dt)
        assert "+00:00" in result or "Z" in result or "2024-06-01" in result

    def test_returns_string(self) -> None:
        from datetime import datetime

        dt = datetime(2025, 3, 8, tzinfo=UTC)
        assert isinstance(iso_datetime(dt), str)


class TestDecimalToStr:
    def test_whole_number(self) -> None:
        assert decimal_to_str(Decimal("100")) == "100"

    def test_fractional(self) -> None:
        result = decimal_to_str(Decimal("123.456"))
        assert result == "123.456"

    def test_no_engineering_notation(self) -> None:
        # Decimal("1E+3") should not produce "1E+3"
        result = decimal_to_str(Decimal("1E+3"))
        assert "E" not in result
        assert result == "1000"

    def test_negative(self) -> None:
        assert decimal_to_str(Decimal("-99.99")) == "-99.99"


class TestConfluentAvroDeserialization:
    """Tests for deserialize_confluent_avro (Confluent wire-format: 0x00 + 4-byte schema_id)."""

    _SCHEMA: ClassVar[dict] = {
        "type": "record",
        "name": "TestEvent",
        "fields": [
            {"name": "event_id", "type": "string"},
            {"name": "value", "type": "int"},
        ],
    }

    def _build_confluent_bytes(self, schema_path: str, record: dict, schema_id: int = 1) -> bytes:
        """Build a Confluent-encoded Avro message: header + schemaless payload."""
        import io

        import fastavro

        parsed = fastavro.parse_schema(self._SCHEMA)
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed, record)
        payload = buf.getvalue()
        header = b"\x00" + schema_id.to_bytes(4, "big")
        return header + payload

    def test_confluent_roundtrip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Confluent wire format: header stripped, payload decoded correctly."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        record = {"event_id": "abc-123", "value": 42}
        confluent_bytes = self._build_confluent_bytes(str(schema_file), record, schema_id=7)

        result = deserialize_confluent_avro(str(schema_file), confluent_bytes)
        assert result["event_id"] == "abc-123"
        assert result["value"] == 42

    def test_missing_magic_byte_raises_value_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Data not starting with 0x00 raises ValueError with a clear message."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        # JSON bytes — first byte is b"{" (0x7B), not 0x00
        raw_json = b'{"event_id": "x", "value": 1}'
        with pytest.raises(ValueError, match="magic byte"):
            deserialize_confluent_avro(str(schema_file), raw_json)

    def test_empty_payload_raises_value_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Empty bytes raises ValueError."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        with pytest.raises(ValueError):
            deserialize_confluent_avro(str(schema_file), b"")

    def test_schema_id_in_header_is_ignored(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The 4-byte schema_id in the header is stripped but not validated.

        We load the schema from disk, not the registry — any schema_id is fine.
        """
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        # schema_id=999 — not a real registry ID, but header structure is valid
        confluent_bytes = self._build_confluent_bytes(str(schema_file), {"event_id": "y", "value": 7}, schema_id=999)
        result = deserialize_confluent_avro(str(schema_file), confluent_bytes)
        assert result["event_id"] == "y"

    # ── PLAN-0062 F-020: expected_schema_ids parameter ────────────────────

    def test_no_expected_schema_ids_skips_validation(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Default behaviour (``expected_schema_ids=None``) skips the check."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        confluent_bytes = self._build_confluent_bytes(str(schema_file), {"event_id": "z", "value": 1}, schema_id=12345)
        # No allow-list passed → no error even though schema_id is bogus.
        result = deserialize_confluent_avro(str(schema_file), confluent_bytes)
        assert result["event_id"] == "z"

    def test_matching_expected_schema_id_succeeds(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """When the header's schema_id is in the allow-list, decode succeeds."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        confluent_bytes = self._build_confluent_bytes(str(schema_file), {"event_id": "ok", "value": 2}, schema_id=42)
        result = deserialize_confluent_avro(
            str(schema_file),
            confluent_bytes,
            expected_schema_ids={42, 43},
        )
        assert result["event_id"] == "ok"

    def test_mismatched_expected_schema_id_raises(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """When the header's schema_id is NOT in the allow-list, raise ValueError."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        confluent_bytes = self._build_confluent_bytes(str(schema_file), {"event_id": "x", "value": 3}, schema_id=99)
        with pytest.raises(ValueError, match="Unexpected schema-id 99"):
            deserialize_confluent_avro(
                str(schema_file),
                confluent_bytes,
                expected_schema_ids={1, 2, 3},
            )

    def test_short_payload_with_expected_schema_ids_raises_magic_byte_error_first(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
    ) -> None:
        """A < 5-byte payload fails the magic-byte check BEFORE the schema-id check."""
        import json

        from messaging.kafka.serialization_utils import deserialize_confluent_avro

        schema_file = tmp_path / "test_event.avsc"
        schema_file.write_text(json.dumps(self._SCHEMA))

        # Valid magic byte but truncated header (< 5 bytes total).
        truncated = b"\x00\x00\x00"
        with pytest.raises(ValueError, match="magic byte"):
            deserialize_confluent_avro(
                str(schema_file),
                truncated,
                expected_schema_ids={1},
            )


class TestSchemasModuleReexports:
    """schemas.py must re-export the utils without breaking."""

    def test_load_schema_importable_from_schemas(self) -> None:
        from messaging.schemas import load_schema as _ls  # noqa: F401

    def test_serialize_avro_importable(self) -> None:
        from messaging.schemas import serialize_avro as _sa  # noqa: F401

    def test_deserialize_avro_importable(self) -> None:
        from messaging.schemas import deserialize_avro as _da  # noqa: F401

    def test_iso_datetime_importable(self) -> None:
        from messaging.schemas import iso_datetime as _id  # noqa: F401


class TestTrailingFieldSkewRecovery:
    """New-reader/old-writer trailing-field skew (BP-720 follow-up).

    A consumer deployed with a schema that APPENDED trailing optional fields,
    before the producer was redeployed to emit them, must not dead-letter every
    message. ``deserialize_avro`` recovers by resolving the missing trailing
    defaulted fields to their declared defaults.
    """

    _WRITER: ClassVar[dict] = {
        "type": "record",
        "name": "ArticleStored",
        "fields": [
            {"name": "doc_id", "type": "string"},
            {"name": "tenant_id", "type": ["null", "string"], "default": None},
        ],
    }
    # Reader (new deploy) appended a trailing optional ``external_id``.
    _READER: ClassVar[dict] = {
        "type": "record",
        "name": "ArticleStored",
        "fields": [
            {"name": "doc_id", "type": "string"},
            {"name": "tenant_id", "type": ["null", "string"], "default": None},
            {"name": "external_id", "type": ["null", "string"], "default": None},
        ],
    }

    def _encode(self, schema: dict, record: dict) -> bytes:
        import io

        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, schema, record)
        return buf.getvalue()

    def test_recovers_missing_trailing_defaulted_field(self) -> None:
        # Producer wrote OLD (2-field) bytes; consumer decodes with NEW schema.
        data = self._encode(self._WRITER, {"doc_id": "d1", "tenant_id": None})
        decoded = deserialize_avro(self._READER, data)
        assert decoded == {"doc_id": "d1", "tenant_id": None, "external_id": None}

    def test_normal_full_record_still_decodes(self) -> None:
        # No skew: writer == reader. The fast path must be unchanged.
        data = self._encode(
            self._READER,
            {"doc_id": "d2", "tenant_id": None, "external_id": "polymarket:abc"},
        )
        decoded = deserialize_avro(self._READER, data)
        assert decoded["external_id"] == "polymarket:abc"

    def test_missing_non_defaulted_trailing_field_still_raises(self) -> None:
        # A trailing field WITHOUT a default cannot be silently defaulted — the
        # payload is genuinely malformed and must still surface as EOFError.
        reader_required_tail = {
            "type": "record",
            "name": "ArticleStored",
            "fields": [
                {"name": "doc_id", "type": "string"},
                {"name": "must_have", "type": "string"},
            ],
        }
        data = self._encode(
            {
                "type": "record",
                "name": "ArticleStored",
                "fields": [{"name": "doc_id", "type": "string"}],
            },
            {"doc_id": "d3"},
        )
        with pytest.raises(EOFError):
            deserialize_avro(reader_required_tail, data)
