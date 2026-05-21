"""Lease-based transactional outbox dispatcher."""

from messaging.kafka.dispatcher.base import (
    OUTBOX_NOTIFY_CHANNEL,
    BaseOutboxDispatcher,
    DeliveryResult,
    DispatcherConfig,
    OutboxRecordProtocol,
    OutboxRepositoryProtocol,
    UnitOfWorkWithOutboxProtocol,
    run_dispatcher,
)

__all__ = [
    "OUTBOX_NOTIFY_CHANNEL",
    "BaseOutboxDispatcher",
    "DeliveryResult",
    "DispatcherConfig",
    "OutboxRecordProtocol",
    "OutboxRepositoryProtocol",
    "UnitOfWorkWithOutboxProtocol",
    "run_dispatcher",
]
