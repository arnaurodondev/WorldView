"""Stubs for confluent_kafka.serialization."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

class MessageField(IntEnum):
    """Identifies which field of a Kafka message is being serialized."""

    NONE = 0
    KEY = 1
    VALUE = 2

class SerializationContext:
    """Metadata for a serialization/deserialization operation.

    Args:
        topic: Kafka topic name.
        field: Which message field is being (de)serialized.
        headers: Optional message headers.
    """

    topic: str
    field: MessageField
    headers: list[tuple[str, bytes]] | None

    def __init__(
        self,
        topic: str,
        field: MessageField,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None: ...

class Serializer:
    """Base serializer interface."""

    def __call__(self, obj: Any, ctx: SerializationContext | None = None) -> bytes | None: ...

class Deserializer:
    """Base deserializer interface."""

    def __call__(self, data: bytes | None, ctx: SerializationContext | None = None) -> Any: ...

class StringSerializer(Serializer):
    def __init__(self, codec: str = "utf_8") -> None: ...

class StringDeserializer(Deserializer):
    def __init__(self, codec: str = "utf_8") -> None: ...
