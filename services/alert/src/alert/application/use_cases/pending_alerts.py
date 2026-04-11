"""Query/command use cases for alert pending-alert operations (S10).

Uses port interfaces (ABCs) from application.ports — never imports from
infrastructure directly (R25 / IG-LAYER-002 compliance).

Both use cases use constructor injection for their dependencies (R25).
The API layer must wire them via DI factories in ``dependencies.py``
(see Wave A-4 of PLAN-0021).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alert.domain.enums import AlertSeverity

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from alert.application.ports.repositories import AlertRepositoryPort, PendingAlertRepositoryPort
    from alert.domain.entities import Alert, PendingAlert

# Severity ranking used for min_severity filtering (lower index = lower severity)
_SEVERITY_RANK: dict[AlertSeverity, int] = {
    AlertSeverity.LOW: 0,
    AlertSeverity.MEDIUM: 1,
    AlertSeverity.HIGH: 2,
    AlertSeverity.CRITICAL: 3,
}


class GetPendingAlertsUseCase:
    """Return (pending, alert) pairs for a user's unacknowledged alerts.

    Args:
    ----
        pending_repo: Repository for pending alert reads.
        alert_repo: Repository for alert reads.

    """

    def __init__(
        self,
        pending_repo: PendingAlertRepositoryPort,
        alert_repo: AlertRepositoryPort,
    ) -> None:
        self._pending_repo = pending_repo
        self._alert_repo = alert_repo

    async def execute(
        self,
        user_id: UUID,
        limit: int,
        offset: int,
        min_severity: AlertSeverity | None = None,
    ) -> list[tuple[PendingAlert, Alert]]:
        """Return unacknowledged (pending, alert) pairs for the user.

        Args:
        ----
            user_id: The authenticated user whose pending alerts to fetch.
            limit: Maximum number of results.
            offset: Pagination offset.
            min_severity: If given, only return alerts at or above this tier.

        """
        # Push severity filter to SQL to avoid pagination-correctness bug (D-4):
        # Python-side filtering after OFFSET pagination skips valid rows when
        # filtered rows are present further in the dataset.
        min_severities: list[str] | None = None
        if min_severity is not None:
            min_rank = _SEVERITY_RANK.get(min_severity, 0)
            min_severities = [str(s) for s, r in _SEVERITY_RANK.items() if r >= min_rank]

        pendings = await self._pending_repo.list_by_user(
            user_id,
            limit=limit,
            offset=offset,
            min_severities=min_severities,
        )

        pairs: list[tuple[PendingAlert, Alert]] = []
        for p in pendings:
            alert = await self._alert_repo.get_by_id(p.alert_id)
            if alert is None:
                continue
            pairs.append((p, alert))

        return pairs


class AcknowledgeAlertUseCase:
    """Mark an alert as delivered for a specific user.

    Returns True when the acknowledgement succeeded, False when the alert
    does not exist or belongs to a different user.

    Args:
    ----
        pending_repo: Repository for pending alert mutations.
        session: Async DB session — committed by this use case on success (N-04).
            The DI factory manages the session lifecycle; the route must NOT
            call ``session.commit()`` after this use case.

    """

    def __init__(
        self,
        pending_repo: PendingAlertRepositoryPort,
        session: AsyncSession,
    ) -> None:
        self._pending_repo = pending_repo
        self._session = session

    async def execute(
        self,
        user_id: UUID,
        alert_id: UUID,
    ) -> bool:
        result = await self._pending_repo.acknowledge(user_id, alert_id)
        if result:
            await self._session.commit()
        return result
