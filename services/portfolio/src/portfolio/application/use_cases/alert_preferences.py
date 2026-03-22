"""Alert preference use cases — get, upsert, set/remove entity suppression.

Design note (Q2 — alert service preference access):
  Per gap analysis open question Q2, Option D was selected. The alert service (S10)
  fetches preferences from Portfolio's API on first alert attempt per user (or session)
  and caches them locally with a short TTL (~60 s). Portfolio does NOT emit a Kafka topic
  for preference changes in this implementation; that can be deferred as a future enhancement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.entities.alert_preference import AlertPreference, EntitySuppression
from portfolio.domain.enums import AlertType
from portfolio.domain.errors import AlertPreferenceNotFoundError, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork


# ── GetAlertPreferencesUseCase ─────────────────────────────────────────────────


class GetAlertPreferencesUseCase:
    """Return all alert preferences for a user, filling defaults (enabled=True) for missing types."""

    async def execute(
        self,
        user_id: UUID,
        tenant_id: UUID,
        uow: UnitOfWork,
    ) -> tuple[list[AlertPreference], list[EntitySuppression]]:
        existing = await uow.alert_preferences.get_by_user(user_id, tenant_id)
        suppressions = await uow.entity_suppressions.list_by_user(user_id, tenant_id)

        existing_map = {pref.alert_type: pref for pref in existing}
        preferences: list[AlertPreference] = []
        for alert_type in AlertType:
            if alert_type in existing_map:
                preferences.append(existing_map[alert_type])
            else:
                # Default: alert enabled=True — do not treat a missing row as disabled.
                preferences.append(
                    AlertPreference(
                        id=new_uuid(),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        alert_type=alert_type,
                        enabled=True,
                        updated_at=utc_now(),
                    )
                )
        return preferences, suppressions


# ── UpsertAlertPreferenceUseCase ───────────────────────────────────────────────


@dataclass
class UpsertAlertPreferenceCommand:
    user_id: UUID
    tenant_id: UUID
    alert_type: str
    enabled: bool


class UpsertAlertPreferenceUseCase:
    async def execute(self, cmd: UpsertAlertPreferenceCommand, uow: UnitOfWork) -> AlertPreference:
        try:
            alert_type = AlertType(cmd.alert_type)
        except ValueError as err:
            raise ValidationError(f"Invalid alert_type: {cmd.alert_type!r}") from err

        pref = AlertPreference(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            alert_type=alert_type,
            enabled=cmd.enabled,
            updated_at=utc_now(),
        )
        await uow.alert_preferences.upsert(pref)
        return pref


# ── SetEntitySuppressionUseCase ────────────────────────────────────────────────


@dataclass
class SetEntitySuppressionCommand:
    user_id: UUID
    tenant_id: UUID
    entity_id: UUID


class SetEntitySuppressionUseCase:
    async def execute(self, cmd: SetEntitySuppressionCommand, uow: UnitOfWork) -> EntitySuppression:
        suppression = EntitySuppression(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            entity_id=cmd.entity_id,
            suppressed_at=utc_now(),
        )
        await uow.entity_suppressions.save(suppression)
        return suppression


# ── RemoveEntitySuppressionUseCase ─────────────────────────────────────────────


@dataclass
class RemoveEntitySuppressionCommand:
    user_id: UUID
    tenant_id: UUID
    entity_id: UUID


class RemoveEntitySuppressionUseCase:
    async def execute(self, cmd: RemoveEntitySuppressionCommand, uow: UnitOfWork) -> None:
        existing = await uow.entity_suppressions.get(cmd.user_id, cmd.entity_id)
        if existing is None:
            raise AlertPreferenceNotFoundError(
                f"No suppression found for entity {cmd.entity_id} and user {cmd.user_id}"
            )
        await uow.entity_suppressions.delete(cmd.user_id, cmd.entity_id)
