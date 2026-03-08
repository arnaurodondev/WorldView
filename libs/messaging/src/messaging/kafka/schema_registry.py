"""Confluent Schema Registry client configuration and factory."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confluent_kafka.schema_registry import SchemaRegistryClient


@dataclasses.dataclass
class SchemaRegistryConfig:
    """Configuration for the Confluent Schema Registry client.

    Args:
        url: Schema Registry base URL (e.g. ``http://localhost:8081``).
        basic_auth_user_info: Optional ``user:password`` for basic auth.
        ssl_ca_location: Path to CA certificate file for TLS verification.
    """

    url: str
    basic_auth_user_info: str = ""
    ssl_ca_location: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return config dict accepted by :class:`SchemaRegistryClient`."""
        cfg: dict[str, str] = {"url": self.url}
        if self.basic_auth_user_info:
            cfg["basic.auth.user.info"] = self.basic_auth_user_info
        if self.ssl_ca_location:
            cfg["ssl.ca.location"] = self.ssl_ca_location
        return cfg


def build_schema_registry_client(config: SchemaRegistryConfig) -> SchemaRegistryClient:
    """Construct a :class:`SchemaRegistryClient` from *config*.

    Args:
        config: Populated :class:`SchemaRegistryConfig`.

    Returns:
        A ready-to-use Confluent Schema Registry client.
    """
    from confluent_kafka.schema_registry import SchemaRegistryClient

    return SchemaRegistryClient(config.to_dict())  # type: ignore[no-any-return]
