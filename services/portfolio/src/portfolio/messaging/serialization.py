"""Build per-event-type Avro serializers and Kafka headers for the outbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).parent / "schemas"

_AVSC_MAP: dict[str, str] = {
    "tenant.created": "tenant.created.avsc",
    "tenant.status_changed": "tenant.created.avsc",  # fallback to created schema
    "user.created": "user.created.avsc",
    "user.status_changed": "user.created.avsc",
    "portfolio.created": "portfolio.created.avsc",
    "portfolio.renamed": "portfolio.renamed.avsc",
    "portfolio.archived": "portfolio.archived.avsc",
    "transaction.recorded": "transaction.recorded.avsc",
    "holding.changed": "holding.changed.avsc",
    "instrument_ref.created": "instrument_ref.created.avsc",
    "watchlist.item_added": "watchlist.item_added.avsc",
    "watchlist.item_removed": "watchlist.item_removed.avsc",
}


def headers_for_event(event_type: str) -> list[tuple[str, bytes]]:
    """Return Kafka message headers for *event_type*."""
    return [
        ("content-type", b"application/avro"),
        ("event-type", event_type.encode()),
    ]


def build_outbox_event_serializers(
    schema_registry_client: Any,
) -> dict[str, Any]:
    """Build a mapping of event_type → AvroSerializer.

    Args:
        schema_registry_client: Confluent SchemaRegistryClient instance.

    Returns:
        dict mapping event_type strings to AvroSerializer callables.
    """
    from confluent_kafka.schema_registry.avro import AvroSerializer  # type: ignore[import-untyped]

    serializers: dict[str, Any] = {}
    for event_type, avsc_file in _AVSC_MAP.items():
        schema_path = _SCHEMA_DIR / avsc_file
        schema_str = schema_path.read_text()
        serializer = AvroSerializer(
            schema_registry_client=schema_registry_client,
            schema_str=schema_str,
        )
        serializers[event_type] = serializer
    return serializers
