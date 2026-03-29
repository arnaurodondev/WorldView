"""Domain error hierarchy for the market-data service.

All errors inherit from ``MarketDataError`` so callers can catch the entire
domain at once.  The domain layer has zero infrastructure imports (R12).

Consumer infrastructure code that needs to dead-letter parse failures should
catch ``ParseError`` and re-raise as ``messaging.kafka.consumer.errors.FatalError``.
In practice, the existing consumers raise ``MalformedDataError`` directly for
parse failures, so no mapping is currently required.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base exception for all market-data domain errors (R21 canonical name)."""


class MarketDataError(DomainError):
    """Descriptive alias preserved for readability within this service."""


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


class ParseError(MarketDataError):
    """Raised when an ingested payload cannot be parsed into canonical form.

    Pure domain exception — no dependency on infrastructure libs (R12).
    Consumer infrastructure code that needs Kafka dead-lettering should catch
    this and re-raise as ``FatalError`` from ``messaging.kafka.consumer.errors``.
    """


class StaleDataError(MarketDataError):
    """Raised when incoming data is older than what is already persisted.

    Triggered by the provider-priority check: if the arriving data has a
    lower priority than the stored record, the upsert is skipped and this
    error is raised to signal the caller.
    """
