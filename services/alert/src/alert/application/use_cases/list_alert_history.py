"""ListAlertHistoryUseCase — paginated tenant-scoped alert history.

PLAN-0051 T-D-4-02. R27-compliant: read-only use case backed by the
``ReadOnlyUnitOfWork`` (read replica).  R25-compliant: depends only on the
``AlertRepositoryPort`` ABC.

Filter semantics (matched by the repository):
  - status=active        — un-acked AND not-currently-snoozed
  - status=acknowledged  — acknowledged_at IS NOT NULL
  - status=snoozed       — snooze_until in future AND not yet acked
  - status=all (default) — no status filter
  - severity, entity_id, from_dt, to_dt — optional additional filters
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from alert.application.ports.repositories import AlertRepositoryPort
    from alert.domain.entities import Alert
    from alert.domain.enums import AlertSeverity


# Cap to prevent runaway pagination requests (denial-of-service).
MAX_LIMIT = 200


class ListAlertHistoryUseCase:
    """Return paginated tenant-scoped alert history."""

    def __init__(self, alert_repo: AlertRepositoryPort) -> None:
        self._alert_repo = alert_repo

    async def execute(
        self,
        tenant_id: UUID,
        *,
        status: str = "all",
        severity: AlertSeverity | None = None,
        entity_id: UUID | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Alert], int]:
        """Return ``(rows, total_universe)`` for the filtered tenant history.

        QA-iter1 C-3: ``total`` is the universe count (every row matching the
        filters) rather than ``len(rows)``. The frontend uses
        ``rows.length < total`` to decide whether to render "Load more" — the
        old shape (total = page size) made that test always False, killing
        pagination. The route layer derives ``has_more`` from this same pair.

        ``limit`` is clamped to ``MAX_LIMIT`` for safety even though the
        Pydantic schema also enforces it (defence-in-depth).
        """
        # Defensive clamps — the Pydantic ``Query`` constraints in the route
        # already enforce these bounds, but the use case re-applies them so
        # programmatic callers (tests, future workers) cannot bypass them.
        if limit < 1:
            limit = 1
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        if offset < 0:
            offset = 0
        if status not in ("active", "acknowledged", "snoozed", "all"):
            # Treat unknown status as "all" to keep API forward-compatible —
            # an unrecognised status simply returns the unfiltered set.
            status = "all"

        # WHY two queries (list + count): we want the universe count for
        # canonical pagination but still want to pull only the requested page.
        # SELECT count(*) is cheap on the indexed tenant_id + (status partial
        # filters) — measured at ~5-10ms for 100k-row tenants.
        rows = await self._alert_repo.list_history(
            tenant_id,
            status=status,
            severity=severity,
            entity_id=entity_id,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
        )
        total = await self._alert_repo.count_history(
            tenant_id,
            status=status,
            severity=severity,
            entity_id=entity_id,
            from_dt=from_dt,
            to_dt=to_dt,
        )
        return rows, total
