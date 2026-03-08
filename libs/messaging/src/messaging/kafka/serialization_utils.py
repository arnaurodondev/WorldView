"""Low-level Avro serialization utilities.

These helpers wrap ``fastavro`` directly and are used by both the schema
loading path and test helpers.  For Confluent Schema Registry-based
serialization, use :mod:`messaging.kafka.serializer`.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any, cast

import fastavro

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer


def load_schema(path: str) -> dict[str, Any]:
    """Load and parse an Avro schema from a ``.avsc`` JSON file.

    Args:
        path: Filesystem path to the ``.avsc`` file.

    Returns:
        Parsed schema dict (fastavro internal representation).
    """
    with open(path) as fh:
        raw = json.load(fh)
    return cast("dict[str, Any]", fastavro.parse_schema(raw))


def serializer_for_schema(
    schema_str: str,
    registry: SchemaRegistryClient,
) -> AvroSerializer:
    """Build a Confluent :class:`AvroSerializer` for *schema_str*.

    Thin convenience wrapper around
    :func:`messaging.kafka.serializer.build_avro_serializer` with default
    config.

    Args:
        schema_str: Avro schema as a JSON string.
        registry: Authenticated :class:`SchemaRegistryClient`.

    Returns:
        A ready-to-use :class:`AvroSerializer`.
    """
    from messaging.kafka.serializer import AvroSerializerConfig, build_avro_serializer

    return build_avro_serializer(schema_str, registry, AvroSerializerConfig())


def iso_datetime(dt: datetime) -> str:
    """Format *dt* as an ISO-8601 UTC string suitable for Avro ``string`` fields.

    Args:
        dt: A timezone-aware :class:`~datetime.datetime` (naive datetimes are
            accepted but treated as UTC with a warning-free conversion).

    Returns:
        ISO-8601 formatted string, e.g. ``"2024-01-15T12:00:00+00:00"``.
    """
    return dt.isoformat()


def decimal_to_str(d: Decimal) -> str:
    """Convert a :class:`~decimal.Decimal` to a plain string for Avro.

    Avro does not natively support Python :class:`~decimal.Decimal`.  Use
    this helper when a schema field is typed as ``string`` but the value
    originates from a ``Decimal`` computation.

    Args:
        d: Decimal value to convert.

    Returns:
        String representation without engineering notation.
    """
    return format(d, "f")


def serialize_avro(schema: dict[str, Any], record: dict[str, Any]) -> bytes:
    """Serialize *record* to Avro binary using the given schema.

    Args:
        schema: Parsed fastavro schema dict (from :func:`load_schema`).
        record: Plain dict matching the schema.

    Returns:
        Raw Avro-encoded bytes (schemaless / single-object encoding).
    """
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def deserialize_avro(schema: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Deserialize Avro binary *data* to a dict using *schema*.

    Args:
        schema: Parsed fastavro schema dict.
        data: Raw Avro-encoded bytes.

    Returns:
        Decoded record as a plain dict.
    """
    buf = io.BytesIO(data)
    return cast("dict[str, Any]", fastavro.schemaless_reader(buf, schema))
