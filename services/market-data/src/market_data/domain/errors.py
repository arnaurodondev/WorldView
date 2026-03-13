"""Domain error hierarchy for the market-data service.

All errors inherit from ``MarketDataError`` so callers can catch the entire
domain at once.  ``ParseError`` additionally inherits from ``FatalError``
(messaging lib) so that Kafka consumer error-routing code treats parse
failures as non-retryable dead-letter candidates without needing to know
about the domain-specific type.
"""

from __future__ import annotations

from messaging import FatalError  # type: ignore[import-untyped]


class MarketDataError(Exception):
    """Base exception for all market-data domain errors."""


class InstrumentNotFoundError(MarketDataError):
    """Raised when a requested instrument does not exist in the database."""


class SecurityNotFoundError(MarketDataError):
    """Raised when a requested security does not exist in the database."""


class DuplicateEventError(MarketDataError):
    """Raised when an event with the same ``event_id`` has already been processed.

    Used as the idempotency guard in the ingestion pipeline.
    """


class IngestionError(MarketDataError):
    """Raised when data ingestion fails for a non-transient reason.

    Distinct from ``ParseError`` — use this for business-rule failures during
    ingestion (e.g. unknown instrument, referential-integrity violation) where
    the payload itself is valid but cannot be applied.
    """


class ParseError(MarketDataError, FatalError):
    """Raised when an ingested payload cannot be parsed into canonical form.

    Inherits from both ``MarketDataError`` (domain hierarchy) and
    ``FatalError`` (messaging lib) so the Kafka consumer dead-letters the
    message immediately without scheduling a retry.
    """


class StaleDataError(MarketDataError):
    """Raised when incoming data is older than what is already persisted.

    Triggered by the provider-priority check: if the arriving data has a
    lower priority than the stored record, the upsert is skipped and this
    error is raised to signal the caller.
    """
