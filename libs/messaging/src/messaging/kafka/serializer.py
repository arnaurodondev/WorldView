"""Avro serializer configuration, protocol, and factory.

The canonical :class:`AvroDictable` protocol lives here.  The ``schemas.py``
module provides lower-level fastavro helpers (``load_schema``,
``serialize_avro``, ``deserialize_avro``) and intentionally does **not**
re-define this protocol.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer


@runtime_checkable
class AvroDictable(Protocol):
    """Protocol for domain events that can be Avro-serialized.

    Implementors must expose:
    - ``event_type`` — a string property used for subject-name routing.
    - ``to_dict()`` — converts the event to a plain :class:`dict` for Avro.
    """

    @property
    def event_type(self) -> str:
        """Stable event-type identifier (e.g. ``market.dataset.fetched``)."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Return an Avro-compatible dictionary representation."""
        ...


def topic_event_type_subject_name_strategy(
    ctx: object,  # SerializationContext — kept as object to avoid hard dep at import
    record_name: str,
) -> str:
    """Subject name strategy: ``{topic}-{event_type}``.

    Confluent's default strategies use ``{topic}-key`` / ``{topic}-value``.
    This custom strategy encodes the event type so that multiple event types
    can share one Kafka topic while keeping their schemas separate in the
    registry.

    Args:
        ctx: :class:`confluent_kafka.serialization.SerializationContext` passed
            by the serialiser framework (accessed via attribute).
        record_name: The Avro record name (unused; event_type drives routing).

    Returns:
        Subject name string.
    """
    topic: str = ctx.topic  # type: ignore[attr-defined]
    # record_name is the Avro full name; event_type is encoded as record_name
    # by build_avro_serializer callers.
    return f"{topic}-{record_name}"


@dataclasses.dataclass
class AvroSerializerConfig:
    """Production-safe defaults for :class:`AvroSerializer`.

    ``auto_register_schemas=False`` prevents accidental schema registration
    in production.  All schemas must be registered in CI/CD pipelines.

    Args:
        auto_register_schemas: Allow automatic schema registration (dev only).
        use_latest_version: If True, fetch the latest schema version from the
            registry instead of the one provided at construction time.
        normalize_schemas: Normalize schema before registration/lookup.
    """

    auto_register_schemas: bool = False
    use_latest_version: bool = False
    normalize_schemas: bool = False

    def to_dict(self) -> dict[str, bool]:
        """Return config dict accepted by :class:`AvroSerializer`."""
        return {
            "auto.register.schemas": self.auto_register_schemas,
            "use.latest.version": self.use_latest_version,
            "normalize.schemas": self.normalize_schemas,
        }


def build_avro_serializer(
    schema_str: str,
    registry: SchemaRegistryClient,
    config: AvroSerializerConfig | None = None,
) -> AvroSerializer:
    """Build a Confluent :class:`AvroSerializer` for a given schema string.

    Args:
        schema_str: Avro schema JSON string.
        registry: Connected :class:`SchemaRegistryClient`.
        config: Serializer configuration; defaults to
            :class:`AvroSerializerConfig` (production-safe defaults).

    Returns:
        A configured :class:`AvroSerializer` instance.
    """
    from confluent_kafka.schema_registry.avro import AvroSerializer

    cfg = config or AvroSerializerConfig()
    return AvroSerializer(  # type: ignore[no-any-return]
        schema_registry_client=registry,
        schema_str=schema_str,
        to_dict=lambda obj, _ctx: obj.to_dict() if hasattr(obj, "to_dict") else obj,
        conf=cfg.to_dict(),
    )
