"""AcknowledgeAlertUseCase — sets acknowledged_at + acknowledged_by_user_id.

PLAN-0051 T-D-4-02. R25-compliant: uses only AlertRepositoryPort (ABC) and a
raw AsyncSession for commit. The route layer must NOT call session.commit().

Behaviour:
  - If the alert is missing: returns ``("not_found", None)``.
  - If the alert belongs to a different tenant: returns ``("forbidden", None)``.
  - If already acknowledged: returns ``("already", existing_alert)`` — idempotent
    (existing acknowledged_at + acknowledged_by_user_id are preserved).
  - On successful first ack: returns ``("ok", updated_alert)``.

The route layer maps these outcomes to HTTP status codes (404/403/200/200).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from alert.application.ports.repositories import AlertRepositoryPort
    from alert.domain.entities import Alert


# Outcome tag returned to the route layer. Strings (not enums) so the API
# router can match without importing application internals.
AckOutcome = Literal["ok", "already", "not_found", "forbidden"]


class AcknowledgeAlertUseCase:
    """Acknowledge an alert on behalf of a user (idempotent)."""

    def __init__(
        self,
        alert_repo: AlertRepositoryPort,
        session: AsyncSession,
    ) -> None:
        self._alert_repo = alert_repo
        self._session = session

    async def execute(
        self,
        alert_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> tuple[AckOutcome, Alert | None]:
        """Acknowledge ``alert_id`` for ``(user_id, tenant_id)``.

        Returns a (outcome, alert) tuple. See module docstring for outcome
        semantics. The session is committed when a write actually happens
        (outcome == "ok"); for idempotent paths no commit is needed because
        no rows changed.
        """
        alert = await self._alert_repo.get_by_id(alert_id)
        if alert is None:
            return "not_found", None

        # Tenant isolation: don't leak that the alert exists if it's not theirs.
        # We still return "forbidden" (rather than "not_found") so the API can
        # distinguish — the route may choose to collapse them into 404.
        # QA-iter1 MAJ-1: NULL ``tenant_id`` is also forbidden for mutations.
        # The list-history endpoint already filters NULL-tenant rows out of
        # tenant-scoped queries, so allowing NULL-tenant ACK was a tenant
        # isolation bypass for legacy rows. The fix is symmetric: any caller
        # that knows the alert_id of a NULL-tenant alert cannot mutate it.
        if alert.tenant_id is None or alert.tenant_id != tenant_id:
            return "forbidden", None

        # Idempotency: if already acked, return the persisted state unchanged.
        if alert.acknowledged_at is not None:
            return "already", alert

        # First-time ack: write + commit. The repo's UPDATE is guarded by
        # ``acknowledged_at IS NULL`` so concurrent acks remain idempotent —
        # only one writer wins, and a False return here means another request
        # already acknowledged it (treat as idempotent success on the re-read).
        updated = await self._alert_repo.acknowledge(alert_id, user_id)
        if not updated:
            # Race: someone else acked between our read and write.
            refreshed = await self._alert_repo.get_by_id(alert_id)
            return "already", refreshed

        await self._session.commit()
        # Re-read so the response carries the canonical persisted timestamps.
        refreshed = await self._alert_repo.get_by_id(alert_id)
        return "ok", refreshed
