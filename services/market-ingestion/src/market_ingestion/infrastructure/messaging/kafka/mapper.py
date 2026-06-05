"""Avro event mapper for market-ingestion domain events.

``MarketDatasetFetchedMapper`` converts a ``MarketDatasetFetched`` domain event
into the flat 27-field Avro-compatible dict that matches the
``market.dataset.fetched`` schema in ``infra/kafka/schemas/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_ingestion.domain.events import MarketDatasetFetched


class MarketDatasetFetchedMapper:
    """Maps ``MarketDatasetFetched`` domain events to Avro wire dicts.

    The mapper flattens ``ObjectRef`` value objects (``bronze_ref`` and
    ``canonical_ref``) into individual scalar fields using the
    ``{ref_name}_ref_{field}`` naming convention required by the Avro schema.
    """

    @staticmethod
    def to_avro_dict(event: MarketDatasetFetched) -> dict:
        """Convert *event* to a flat 27-field Avro-compatible dict.

        All 27 schema fields are present; nullable fields may be ``None``
        (which Avro maps to ``null``).
        """
        return {
            # Envelope (6)
            "event_id": event.event_id,
            "event_type": event.EVENT_TYPE,
            "schema_version": event.SCHEMA_VERSION,
            "occurred_at": event.occurred_at,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            # Task + dataset identity (7)
            "task_id": event.task_id,
            "provider": event.provider,
            "dataset_type": event.dataset_type,
            "symbol": event.symbol,
            "exchange": event.exchange,
            "timeframe": event.timeframe,
            "variant": event.variant,
            # Date range (2)
            "range_start": event.range_start or None,
            "range_end": event.range_end or None,
            # Bronze ref — ObjectRef flattened (5)
            "bronze_ref_bucket": event.bronze_ref.bucket,
            "bronze_ref_key": event.bronze_ref.key,
            "bronze_ref_sha256": event.bronze_ref.sha256,
            "bronze_ref_byte_length": event.bronze_ref.byte_length,
            "bronze_ref_mime_type": event.bronze_ref.mime_type,
            # Canonical ref — ObjectRef flattened (5)
            "canonical_ref_bucket": event.canonical_ref.bucket,
            "canonical_ref_key": event.canonical_ref.key,
            "canonical_ref_sha256": event.canonical_ref.sha256,
            "canonical_ref_byte_length": event.canonical_ref.byte_length,
            "canonical_ref_mime_type": event.canonical_ref.mime_type,
            # Metadata (2)
            "canonical_schema_version": event.canonical_schema_version,
            "row_count": event.row_count if event.row_count else None,
        }

    @staticmethod
    def to_kafka_key(event: MarketDatasetFetched) -> str:
        """Return the Kafka message key: ``{provider}:{symbol}``."""
        return f"{event.provider}:{event.symbol}"
