"""Stubs for confluent_kafka.schema_registry."""

from __future__ import annotations

from typing import Any

class Schema:
    """Represents an Avro/JSON schema registered in the Schema Registry."""

    def __init__(
        self,
        schema_str: str,
        schema_type: str,
        references: list[Any] | None = None,
    ) -> None: ...
    @property
    def schema_str(self) -> str: ...
    @property
    def schema_type(self) -> str: ...

class RegisteredSchema:
    schema_id: int
    schema: Schema
    subject: str
    version: int

class SchemaRegistryClient:
    """Client for the Confluent Schema Registry REST API."""

    def __init__(self, conf: dict[str, str]) -> None: ...
    def register_schema(
        self,
        subject_name: str,
        schema: Schema,
        normalize_schemas: bool = False,
    ) -> int: ...
    def get_latest_version(self, subject_name: str) -> RegisteredSchema: ...
    def get_schema(self, schema_id: int) -> Schema: ...
    def delete_subject(self, subject_name: str, permanent: bool = False) -> list[int]: ...
    def delete_version(self, subject_name: str, version: int, permanent: bool = False) -> int: ...
