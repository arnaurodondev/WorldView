"""Avro schema utilities (fastavro-based helpers).

The canonical :class:`~messaging.kafka.serializer.AvroDictable` protocol is
defined in :mod:`messaging.kafka.serializer`.  This module re-exports the
most common fastavro helpers for convenience.
"""

from messaging.kafka.serialization_utils import (
    deserialize_avro,
    iso_datetime,
    load_schema,
    serialize_avro,
)

__all__ = [
    "deserialize_avro",
    "iso_datetime",
    "load_schema",
    "serialize_avro",
]
