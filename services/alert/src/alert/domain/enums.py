"""Domain enumerations for the Alert service (S10)."""

from __future__ import annotations

from enum import StrEnum


class AlertSeverity(StrEnum):
    """Severity tier of an alert, derived from market_impact_score (PRD-0021 §6.5)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(StrEnum):
    """The three signal categories that trigger alerts (PRD §6.5.5)."""

    SIGNAL = "SIGNAL"
    GRAPH_CHANGE = "GRAPH_CHANGE"
    CONTRADICTION = "CONTRADICTION"


class OutboxStatus(StrEnum):
    """Lifecycle status of an outbox event row."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class DeliveryChannel(StrEnum):
    """Alert delivery channel."""

    WEBSOCKET = "websocket"


class DeliveryStatus(StrEnum):
    """Status of a single alert delivery to a user."""

    PENDING = "pending"
    DELIVERED = "delivered"


class DLQStatus(StrEnum):
    """Status of a dead-letter-queue entry."""

    FAILED = "failed"
    RESOLVED = "resolved"
