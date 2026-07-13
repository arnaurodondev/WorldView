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
    EODHD_TICKER_NEWS = "eodhd_ticker_news"
    SEC_EDGAR = "sec_edgar"
    FINNHUB = "finnhub"
    NEWSAPI = "newsapi"
    MANUAL = "manual"
    POLYMARKET = "polymarket"
    # PLAN-0056 Wave Z1 — deeper Polymarket streams (Gamma /events, CLOB /prices-history,
    # Data /trades, Data /oi). Routed directly in the S4 worker (not via ADAPTER_REGISTRY),
    # same as POLYMARKET.
    POLYMARKET_GAMMA_EVENTS = "polymarket_gamma_events"
    POLYMARKET_CLOB = "polymarket_clob"
    POLYMARKET_DATA_TRADES = "polymarket_data_trades"
    POLYMARKET_DATA_OI = "polymarket_data_oi"
    TENANT_UPLOAD = "tenant_upload"


class IngestionTaskStatus(StrEnum):
    """Task lifecycle states for the scheduler-worker ingestion pattern.

    State machine::

        PENDING → CLAIMED → RUNNING → SUCCEEDED
                                     ↘ RETRY → (back to PENDING/CLAIMED)
                                     ↘ FAILED  (terminal)

    ``CLAIMED`` is used by services with an explicit claim step (e.g. content-ingestion).
    Services that transition directly from PENDING to RUNNING (e.g. market-ingestion)
    simply skip the CLAIMED state.

    Used by: S2 (Market Ingestion), S4 (Content Ingestion).
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    FAILED = "failed"
