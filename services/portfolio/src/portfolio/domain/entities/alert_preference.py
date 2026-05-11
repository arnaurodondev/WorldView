"""AlertPreference and EntitySuppression domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from portfolio.domain.enums import AlertType


@dataclass(frozen=True)
class AlertPreference:
    """Per-user, per-alert-type toggle for receiving portfolio intelligence alerts."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    alert_type: AlertType
    enabled: bool
    updated_at: datetime


@dataclass(frozen=True)
class EntitySuppression:
    """Suppresses all alerts for a specific entity for a given user."""

    id: UUID
    tenant_id: UUID
    user_id: UUID
    entity_id: UUID
    suppressed_at: datetime
