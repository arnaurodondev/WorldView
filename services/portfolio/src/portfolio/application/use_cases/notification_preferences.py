"""Notification preferences use cases — get and update.

Design note:
  Preferences are tenant-scoped (one row per tenant_id). The get use case
  returns a defaults object when no row exists yet (upsert-on-read pattern),
  so the frontend always gets a valid payload without requiring an explicit
  provisioning step.

  The update use case uses an upsert to avoid TOCTOU races between concurrent
  PATCH calls from multiple browser tabs.

W1-BACKEND: added to resolve MED-022 / CRIT-004 in the frontend audit
issue registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.domain.entities.notification_preferences import NotificationPreferences

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Default factory ───────────────────────────────────────────────────────────


def _defaults(tenant_id: UUID) -> NotificationPreferences:
    """Return a defaults NotificationPreferences when no DB row exists.

    WHY defaults True everywhere: the product targets active traders who
    expect signal-rich notifications. Explicit opt-out is preferred over
    opt-in; users who want silence can toggle each category off.
    """
    return NotificationPreferences(
        tenant_id=tenant_id,
        price_alerts=True,
        news_alerts=True,
        movers_alerts=True,
        contradiction_alerts=True,
        updated_at=utc_now(),
    )


# ── GetNotificationPreferences ────────────────────────────────────────────────


class GetNotificationPreferencesUseCase:
    """Return the current notification preferences for a tenant.

    Returns defaults when no row has been written yet (the frontend never
    needs to check for null). R27: depends on ReadOnlyUnitOfWork.
    """

    async def execute(
        self,
        tenant_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> NotificationPreferences:
        stored = await uow.notification_preferences.get(tenant_id)
        if stored is None:
            # No row yet — return in-memory defaults. We do NOT write them
            # here (this is a read-only use case); the first PATCH call will
            # upsert the row.
            logger.debug(
                "notification_preferences_defaults",
                tenant_id=str(tenant_id),
            )
            return _defaults(tenant_id)
        return stored


# ── UpdateNotificationPreferences ─────────────────────────────────────────────


@dataclass
class UpdateNotificationPreferencesCommand:
    tenant_id: UUID
    # Each field is Optional — a PATCH call can update any subset.
    price_alerts: bool | None = None
    news_alerts: bool | None = None
    movers_alerts: bool | None = None
    contradiction_alerts: bool | None = None


class UpdateNotificationPreferencesUseCase:
    """Upsert notification preferences for a tenant.

    Merges the command fields over the existing values (or defaults when no
    row exists). Uses an upsert to keep the operation idempotent — multiple
    concurrent PATCH calls with the same payload are safe.
    """

    async def execute(
        self,
        cmd: UpdateNotificationPreferencesCommand,
        uow: UnitOfWork,
    ) -> NotificationPreferences:
        # Load existing row (or defaults) so we can merge the partial update.
        existing = await uow.notification_preferences.get(cmd.tenant_id)
        base = existing if existing is not None else _defaults(cmd.tenant_id)

        # WHY build a new frozen dataclass: entities are frozen (immutable by
        # design) — we never mutate in place. The merged result is the
        # authoritative state to persist.
        updated = NotificationPreferences(
            tenant_id=cmd.tenant_id,
            price_alerts=cmd.price_alerts if cmd.price_alerts is not None else base.price_alerts,
            news_alerts=cmd.news_alerts if cmd.news_alerts is not None else base.news_alerts,
            movers_alerts=cmd.movers_alerts if cmd.movers_alerts is not None else base.movers_alerts,
            contradiction_alerts=(
                cmd.contradiction_alerts if cmd.contradiction_alerts is not None else base.contradiction_alerts
            ),
            updated_at=utc_now(),
        )

        await uow.notification_preferences.upsert(updated)
        await uow.commit()

        logger.info(
            "notification_preferences_updated",
            tenant_id=str(cmd.tenant_id),
        )
        return updated
