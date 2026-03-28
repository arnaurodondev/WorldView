"""Domain entities for the Alert service (S10).

All entities are plain dataclasses — no infrastructure imports.
IDs are UUIDv7 (``common.ids.new_uuid7``), timestamps UTC-only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from alert.domain.enums import AlertType, DeliveryChannel, DeliveryStatus, DLQStatus, OutboxStatus
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

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
    source_event_id: UUID = field(default_factory=new_uuid7)
    source_topic: str = ""
    payload: dict[str, object] = field(default_factory=dict)
    dedup_key: str = ""
    created_at: datetime = field(default_factory=utc_now)

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
