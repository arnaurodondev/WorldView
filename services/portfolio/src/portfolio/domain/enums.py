"""Domain enumerations for the Portfolio service."""

from __future__ import annotations

from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"


class PortfolioStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class TransactionType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FEE = "FEE"


class TransactionDirection(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class IdempotencyState(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WatchlistStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class AlertType(StrEnum):
    SIGNAL = "signal"
    CONTRADICTION = "contradiction"
    CONFIDENCE_DROP = "confidence_drop"
    NEW_EVENT = "new_event"
