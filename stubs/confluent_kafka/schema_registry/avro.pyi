"""Stubs for confluent_kafka.schema_registry.avro."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.serialization import SerializationContext

class AvroSerializer:
    """Confluent Avro serializer backed by the Schema Registry."""

    def __init__(
        self,
        schema_registry_client: SchemaRegistryClient,
        schema_str: str,
        to_dict: Callable[[Any, SerializationContext | None], dict[str, Any]] | None = None,
        conf: dict[str, Any] | None = None,
    ) -> None: ...
    def __call__(
        self,
        obj: Any,
        ctx: SerializationContext | None = None,
    ) -> bytes | None: ...

class AvroDeserializer:
    """Confluent Avro deserializer backed by the Schema Registry."""

    def __init__(
        self,
        schema_registry_client: SchemaRegistryClient,
        schema_str: str | None = None,
        from_dict: Callable[[dict[str, Any], SerializationContext | None], Any] | None = None,
        return_record_name: bool = False,
    ) -> None: ...
    def __call__(
        self,
        data: bytes | None,
        ctx: SerializationContext | None = None,
    ) -> Any: ...
