"""Query/command use cases for alert pending-alert operations (S10).

All infrastructure imports are encapsulated here so that api/routes.py imports
only from the application layer (R25 / IG-LAYER-002 compliance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.infrastructure.db.repositories.alert import AlertRepository
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from alert.domain.entities import Alert, PendingAlert


class GetPendingAlertsUseCase:
    """Return (pending, alert) pairs for a user's unacknowledged alerts."""

    async def execute(
        self,
        session: AsyncSession,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[tuple[PendingAlert, Alert]]:
        pending_repo = PendingAlertRepository(session)
        alert_repo = AlertRepository(session)

        pendings = await pending_repo.list_by_user(user_id, limit=limit, offset=offset)

        pairs: list[tuple[PendingAlert, Alert]] = []
        for p in pendings:
            alert = await alert_repo.get_by_id(p.alert_id)
            if alert is None:
                continue
            pairs.append((p, alert))
        return pairs


class AcknowledgeAlertUseCase:
    """Mark an alert as delivered for a specific user.

    Returns True when the acknowledgement succeeded, False when the alert
    does not exist or belongs to a different user.
    """

    async def execute(
        self,
        session: AsyncSession,
        user_id: UUID,
        alert_id: UUID,
    ) -> bool:
        pending_repo = PendingAlertRepository(session)
        return await pending_repo.acknowledge(user_id, alert_id)
