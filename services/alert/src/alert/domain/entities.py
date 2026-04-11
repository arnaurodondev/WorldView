"""Domain entities for the Alert service (S10).

All entities are plain dataclasses — no infrastructure imports.
IDs are UUIDv7 (``common.ids.new_uuid7``), timestamps UTC-only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from alert.domain.enums import AlertSeverity, AlertType, DeliveryChannel, DeliveryStatus, DLQStatus, OutboxStatus
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

# ---------------------------------------------------------------------------
# SeverityThresholds — value object for market_impact_score classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeverityThresholds:
    """Classifies a market_impact_score float into an AlertSeverity tier (PRD-0021 §6.5).

    Invariant: ``critical > high > medium >= 0.0``; raises ValueError otherwise.
    """

    critical: float = 0.85
    high: float = 0.65
    medium: float = 0.40

    def __post_init__(self) -> None:
        if self.medium < 0.0:
            raise ValueError(f"medium threshold must be >= 0.0, got {self.medium}")
        if not (self.critical > self.high > self.medium):
            raise ValueError(
                f"Thresholds must satisfy critical > high > medium; "
                f"got critical={self.critical}, high={self.high}, medium={self.medium}"
            )

    def classify(self, market_impact_score: float) -> AlertSeverity:
        """Return the severity tier for a given market_impact_score."""
        if market_impact_score >= self.critical:
            return AlertSeverity.CRITICAL
        if market_impact_score >= self.high:
            return AlertSeverity.HIGH
        if market_impact_score >= self.medium:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW


# ---------------------------------------------------------------------------
# Alert — the core entity persisted in ``alerts`` table
# ---------------------------------------------------------------------------


@dataclass
class Alert:
    """A materialised alert created when a signal affects a watched entity.

    ``dedup_key`` is ``sha256(entity_id + alert_type + window_bucket)``
    where ``window_bucket = created_at_epoch // dedup_window_seconds``.
    A UNIQUE constraint on ``dedup_key`` prevents duplicate noise (AD-9).
    """

    alert_id: UUID = field(default_factory=new_uuid7)
    entity_id: UUID = field(default_factory=new_uuid7)
    alert_type: AlertType = AlertType.SIGNAL
    severity: AlertSeverity = AlertSeverity.LOW
    source_event_id: UUID = field(default_factory=new_uuid7)
    source_topic: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    dedup_key: str = ""
    created_at: datetime = field(default_factory=utc_now)
    tenant_id: UUID | None = field(default=None)

    @staticmethod
    def compute_dedup_key(
        entity_id: UUID,
        alert_type: AlertType,
        created_at: datetime,
        window_seconds: int = 300,
    ) -> str:
        """Compute dedup key per AD-9: sha256(entity_id + alert_type + window_bucket).

        ``source_event_id`` is intentionally excluded so that multiple events
        about the same entity+type within one window are deduplicated.
        """
        epoch = int(created_at.replace(tzinfo=UTC).timestamp())
        window_bucket = epoch // window_seconds
        raw = f"{entity_id}:{alert_type}:{window_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# PendingAlert — per-user pending delivery row
# ---------------------------------------------------------------------------


@dataclass
class PendingAlert:
    """A pending alert awaiting acknowledgement by a user."""

    pending_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    alert_id: UUID = field(default_factory=new_uuid7)
    created_at: datetime = field(default_factory=utc_now)
    delivered_at: datetime | None = None


# ---------------------------------------------------------------------------
# AlertDelivery — tracks per-user delivery
# ---------------------------------------------------------------------------


@dataclass
class AlertDelivery:
    """Records that an alert was delivered to a user on a specific channel."""

    delivery_id: UUID = field(default_factory=new_uuid7)
    alert_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    channel: DeliveryChannel = DeliveryChannel.WEBSOCKET
    status: DeliveryStatus = DeliveryStatus.DELIVERED
    delivered_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# AlertSubscription — user→entity subscription
# ---------------------------------------------------------------------------


@dataclass
class AlertSubscription:
    """User subscription to alerts for a specific entity via a watchlist."""

    subscription_id: UUID = field(default_factory=new_uuid7)
    user_id: UUID = field(default_factory=new_uuid7)
    entity_id: UUID = field(default_factory=new_uuid7)
    watchlist_id: UUID = field(default_factory=new_uuid7)
    alert_types: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None


# ---------------------------------------------------------------------------
# OutboxEvent — transactional outbox row
# ---------------------------------------------------------------------------


@dataclass
class OutboxEvent:
    """Outbox event for reliable Kafka publishing."""

    event_id: UUID = field(default_factory=new_uuid7)
    topic: str = ""
    partition_key: str = ""
    payload_avro: bytes = b""
    status: OutboxStatus = OutboxStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    dispatched_at: datetime | None = None
    retry_count: int = 0
    failed_at: datetime | None = None


# ---------------------------------------------------------------------------
# DeadLetterEntry — DLQ row
# ---------------------------------------------------------------------------


@dataclass
class DeadLetterEntry:
    """Dead-letter queue entry for failed outbox dispatches."""

    dlq_id: UUID = field(default_factory=new_uuid7)
    original_event_id: UUID = field(default_factory=new_uuid7)
    topic: str = ""
    payload_avro: bytes = b""
    error_detail: str | None = None
    status: DLQStatus = DLQStatus.FAILED
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolution_note: str | None = None


# ---------------------------------------------------------------------------
# EmailPreference — user email notification settings (PRD-0016 §6.5)
# ---------------------------------------------------------------------------


@dataclass
class EmailPreference:
    """User preferences for the weekly portfolio risk email digest.

    ``send_day_of_week`` is 0=Monday to 6=Sunday.
    ``send_hour_utc`` is 0-23.
    ``email_address`` is nullable - falls back to the user's account email
    fetched from S1 ``GET /internal/v1/users/{user_id}`` at send time.
    """

    user_id: UUID = field(default_factory=new_uuid7)
    tenant_id: UUID = field(default_factory=new_uuid7)
    weekly_digest_enabled: bool = True
    send_day_of_week: int = 6  # Sunday
    send_hour_utc: int = 8
    email_address: str | None = None
    last_digest_sent_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not (0 <= self.send_day_of_week <= 6):
            raise ValueError(f"send_day_of_week must be 0-6, got {self.send_day_of_week}")
        if not (0 <= self.send_hour_utc <= 23):
            raise ValueError(f"send_hour_utc must be 0-23, got {self.send_hour_utc}")
