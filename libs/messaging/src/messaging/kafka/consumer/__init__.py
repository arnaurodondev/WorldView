"""Kafka consumer base class and error hierarchy."""

from messaging.kafka.consumer.backpressure import (
    BackpressurePolicy,
    LagCalculator,
)
from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin
from messaging.kafka.consumer.errors import (
    BusinessRuleViolationError,
    ConsumerError,
    DatabaseConnectionError,
    FatalError,
    MalformedDataError,
    MissingRequiredFieldError,
    NetworkTimeoutError,
    RateLimitedError,
    RetryableError,
    SchemaVersionError,
    ServiceUnavailableError,
    StorageUnavailableError,
)

__all__ = [
    "BackpressurePolicy",
    "BaseKafkaConsumer",
    "BusinessRuleViolationError",
    "ConsumerConfig",
    "ConsumerError",
    "DatabaseConnectionError",
    "FailureInfo",
    "FatalError",
    "LagCalculator",
    "MalformedDataError",
    "MissingRequiredFieldError",
    "NetworkTimeoutError",
    "RateLimitedError",
    "RetryableError",
    "SchemaVersionError",
    "ServiceUnavailableError",
    "StorageUnavailableError",
    "UnitOfWorkProtocol",
    "ValkeyDedupMixin",
]
