"""Shared enums for cross-service event discriminators.

These enums represent values that appear in Kafka events exchanged between
services. Placing them here ensures producers and consumers agree on valid values.
"""

from __future__ import annotations

from enum import StrEnum


class ContentSourceType(StrEnum):
    """Content source types for the ingestion pipeline.

    Used in ``content.article.raw.v1`` and ``content.article.stored.v1``
    Avro events as the ``source_type`` field discriminator.

    Used by: S4 (Content Ingestion) as producer, S5 (Content Store) as consumer.
    """

    EODHD = "eodhd"
    SEC_EDGAR = "sec_edgar"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    MANUAL = "manual"
