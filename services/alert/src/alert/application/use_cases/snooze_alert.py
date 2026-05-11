"""SnoozeAlertUseCase — set snooze_until on an alert.

PLAN-0051 T-D-4-02. R25-compliant: uses AlertRepositoryPort (ABC) only.
Validates the requested snooze window (must be in the future, <= 30 days).

Outcomes mirror AcknowledgeAlertUseCase: ``ok | not_found | forbidden | invalid``.
The route layer maps them to HTTP status codes (200/404/403/422).
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Literal

from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from alert.application.ports.repositories import AlertRepositoryPort
    from alert.domain.entities import Alert


SnoozeOutcome = Literal["ok", "not_found", "forbidden", "invalid"]

# Maximum allowed snooze window. Anything beyond this is rejected as invalid
# so users can't permanently silence alerts; long-term silencing should use
# a rule-level mute instead (out of scope for this wave).
MAX_SNOOZE_DAYS = 30


class SnoozeAlertUseCase:
    """Snooze an alert until a future timestamp (max 30 days out)."""

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
        snooze_until: datetime,
        tenant_id: UUID,
    ) -> tuple[SnoozeOutcome, Alert | None]:
        """Set ``snooze_until`` on ``alert_id`` for ``tenant_id``.

        Validates that ``snooze_until`` is timezone-aware, in the future, and
        no more than ``MAX_SNOOZE_DAYS`` days from now. Tenant isolation is
        enforced before any write happens.
        """
        # Normalise to UTC. Naive datetimes are rejected so the API never
        # mis-stores a local time as UTC (BP-024 family — UTC-only).
        if snooze_until.tzinfo is None:
            return "invalid", None
        target = snooze_until.astimezone(UTC)

        now = utc_now()
        if target <= now:
            return "invalid", None
        if target > now + timedelta(days=MAX_SNOOZE_DAYS):
            return "invalid", None

        alert = await self._alert_repo.get_by_id(alert_id)
        if alert is None:
            return "not_found", None
        # QA-iter1 MAJ-1: NULL tenant_id is forbidden for mutations (symmetric
        # with the read path which excludes NULL-tenant rows from tenant-scoped
        # history queries). Allowing NULL through here was an isolation bypass.
        if alert.tenant_id is None or alert.tenant_id != tenant_id:
            return "forbidden", None

        await self._alert_repo.snooze(alert_id, target)
        await self._session.commit()
        refreshed = await self._alert_repo.get_by_id(alert_id)
        return "ok", refreshed
