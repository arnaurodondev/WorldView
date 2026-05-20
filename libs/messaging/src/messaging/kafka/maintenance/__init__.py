"""Maintenance workers for messaging infrastructure.

Currently exposes:

* :class:`ProcessedEventsCleanupWorker` — daily retention enforcement for the
  ``processed_events`` idempotency table written by ``BaseKafkaConsumer``.
"""

from messaging.kafka.maintenance.processed_events_cleanup import (
    ProcessedEventsCleanupWorker,
)

__all__ = ["ProcessedEventsCleanupWorker"]
