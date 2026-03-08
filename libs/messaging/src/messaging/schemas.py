"""Avro schema utilities and the AvroDictable protocol."""

from __future__ import annotations

import io
import json
from typing import Any, Protocol, cast, runtime_checkable

import fastavro


@runtime_checkable
class AvroDictable(Protocol):
    """Protocol for objects that can be serialized to/from Avro-compatible dicts."""

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AvroDictable: ...


def load_schema(path: str) -> dict[str, Any]:
    """Load an Avro schema from a ``.avsc`` JSON file."""
    with open(path) as f:
        schema = json.load(f)
    parsed = cast(dict[str, Any], fastavro.parse_schema(schema))
    return parsed


def serialize_avro(schema: dict[str, Any], record: dict[str, Any]) -> bytes:
    """Serialize a dict to Avro binary using the given schema."""
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def deserialize_avro(schema: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Deserialize Avro binary to a dict using the given schema."""
    buf = io.BytesIO(data)
    return cast(dict[str, Any], fastavro.schemaless_reader(buf, schema))
