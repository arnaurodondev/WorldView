"""GetActiveAlertFlagUseCase — PLAN-0089 Wave L-5a (T-WL5A-02).

Returns whether ANY user is currently watching ``instrument_id`` with an
active alert. Used by the screener S3-side sync worker (Wave L-5b) to
materialise ``instrument_intelligence_snapshot.has_active_alert``.

Definition of "active" (audit §8.a — option (a)):
  - exists at least one ``alerts`` row where ``entity_id == instrument_id``
    AND ``acknowledged_at IS NULL``
    AND (``snooze_until IS NULL`` OR ``snooze_until < now()``).

Rationale: this is the per-entity "someone is watching" signal that the
screener cares about — independent of any individual user. Per-user alert
preferences remain user-scoped at the API surface; only the aggregated
cross-user count is exposed here. We use the existing
``idx_alerts_unack_unsnoozed`` partial index so the count is cheap.

R9: reads only from ``alert_db`` (S10's own DB).
R25: API → use case only.
R27: caller wires a ``ReadDbSessionDep``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ActiveAlertFlag:
    """Small JSON-friendly DTO returned by the use case."""

    has_active_alert: bool
    active_alert_count: int


class GetActiveAlertFlagUseCase:
    """Count active alerts for a given entity across all users."""

    async def execute(
        self,
        session: AsyncSession,
        instrument_id: UUID,
    ) -> ActiveAlertFlag:
        """Return active-alert count + bool flag for ``instrument_id``."""
        sql = text(
            """
            SELECT COUNT(*) AS active_count
            FROM alerts
            WHERE entity_id = :entity_id
              AND acknowledged_at IS NULL
              AND (snooze_until IS NULL OR snooze_until < now())
            """,
        )
        result = await session.execute(sql, {"entity_id": str(instrument_id)})
        row = result.fetchone()
        count = int(row[0]) if row is not None and row[0] is not None else 0
        return ActiveAlertFlag(
            has_active_alert=count > 0,
            active_alert_count=count,
        )
