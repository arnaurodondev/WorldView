"""Tests for Avro schema utilities (T-032 / schemas.py)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

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
