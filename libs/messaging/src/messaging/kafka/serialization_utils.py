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


# PLAN-0062 F-020: registry of known schema IDs per topic.  Consumers that
# wish to opt into Confluent Schema Registry compatibility checks pass
# ``expected_schema_ids=KNOWN_TOPIC_SCHEMA_IDS[topic]`` to
# :func:`deserialize_confluent_avro`.  Empty by default — populate at startup
# from the registry, or leave empty to keep current behaviour (no check).
KNOWN_TOPIC_SCHEMA_IDS: dict[str, set[int]] = {}


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
    return cast("dict[str, Any]", fastavro.schemaless_reader(buf, schema, None))


def serialize_confluent_avro(
    schema_path: str,
    record: dict[str, Any],
    schema_id: int = 0,
) -> bytes:
    """Serialize *record* to Confluent Schema Registry wire-format bytes.

    The Confluent wire format prefixes a 5-byte header (``0x00`` magic byte +
    4-byte big-endian schema ID) before the raw Avro payload.  This helper
    keeps producer-side serialization aligned with
    :func:`deserialize_confluent_avro` so consumers and producers stay in sync.

    Args:
        schema_path: Filesystem path to the ``.avsc`` schema file.
        record: Plain dict matching the schema.
        schema_id: Confluent Schema Registry schema ID.  Defaults to 0 because
            the consumer does not validate the ID — it strips the header and
            decodes against its locally-loaded schema.  Producers that DO want
            to honour the registry can pass the real ID here.

    Returns:
        5-byte Confluent header + Avro-encoded payload bytes.
    """
    schema = load_schema(schema_path)
    avro_bytes = serialize_avro(schema, record)
    header = b"\x00" + schema_id.to_bytes(4, byteorder="big", signed=False)
    return header + avro_bytes


def deserialize_confluent_avro(
    schema_path: str,
    data: bytes,
    *,
    expected_schema_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Deserialize a Confluent Schema Registry wire-format Avro message.

    Confluent producers prefix messages with a 5-byte header:
    ``0x00`` (magic byte) + 4-byte big-endian schema ID.  This function
    strips those 5 bytes and then delegates to :func:`deserialize_avro`
    with the schema loaded from *schema_path*.

    PLAN-0062 F-020: when *expected_schema_ids* is provided, the schema-id
    embedded in the header is validated against that set BEFORE the schema
    is loaded.  This catches drift between the consumer's local schema and
    the registry-published one.  Pass ``None`` (the default) to preserve
    legacy behaviour where the schema id is ignored.

    Args:
        schema_path: Filesystem path to the ``.avsc`` schema file.
        data: Raw Avro bytes from a Confluent Kafka message (including header).
        expected_schema_ids: Optional allow-list of acceptable schema IDs.

    Returns:
        Decoded record as a plain dict.

    Raises:
        ValueError: If *data* does not start with the expected magic byte, or
            if *expected_schema_ids* is provided and the header's schema id is
            not in the set.
    """
    confluent_magic = b"\x00"
    header_size = 5  # 1 magic byte + 4 schema-id bytes

    if len(data) < header_size or data[0:1] != confluent_magic:
        raise ValueError(
            f"Expected Confluent Avro magic byte 0x00 at position 0, got 0x{data[0]:02x}" if data else "Empty payload"
        )
    # PLAN-0062 F-020: optional schema-id allow-list check.  Performed BEFORE
    # the (potentially expensive) schema load so a mismatch fails fast.
    if expected_schema_ids is not None:
        schema_id = int.from_bytes(data[1:5], byteorder="big", signed=False)
        if schema_id not in expected_schema_ids:
            raise ValueError(
                f"Unexpected schema-id {schema_id}, expected one of {sorted(expected_schema_ids)}",
            )
    schema = load_schema(schema_path)
    return deserialize_avro(schema, data[header_size:])
