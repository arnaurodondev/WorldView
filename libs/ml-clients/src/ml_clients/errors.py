"""Error types for ml-clients — re-exported from messaging."""

from messaging.kafka.consumer.errors import FatalError, RetryableError

__all__ = ["FatalError", "RetryableError"]
