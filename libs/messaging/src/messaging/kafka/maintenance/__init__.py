"""Maintenance workers for messaging infrastructure.

Currently exposes:

* :class:`ProcessedEventsCleanupWorker` — daily retention enforcement for the
  ``processed_events`` idempotency table written by ``BaseKafkaConsumer``.
* :class:`RetentionCleanupWorker` / :class:`RetentionPolicy` — generic
  age-based, batched, per-batch-committing pruner for unbounded append/log
  tables (outbox delivered rows, dedup/idempotency logs). Wired per-service
  via :func:`run_retention_loop` / :func:`build_retention_loop_coros`.
"""

from messaging.kafka.maintenance.processed_events_cleanup import (
    ProcessedEventsCleanupWorker,
)
from messaging.kafka.maintenance.table_retention import (
    RetentionCleanupWorker,
    RetentionPolicy,
    build_retention_loop_coros,
    run_retention_loop,
)

__all__ = [
    "ProcessedEventsCleanupWorker",
    "RetentionCleanupWorker",
    "RetentionPolicy",
    "build_retention_loop_coros",
    "run_retention_loop",
]
