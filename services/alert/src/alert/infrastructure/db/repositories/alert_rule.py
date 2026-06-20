"""SQLAlchemy adapter for ``alert_rules`` persistence (PLAN-0113).

Implements ``IAlertRuleRepository`` (R25). All writes ``flush`` only — the
route/UoW owns the transaction boundary (commit). Reads are owner-scoped
(tenant_id + user_id) except ``list_enabled_by_type`` which the poller uses to
scan across owners.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from alert.application.ports.repositories import IAlertRuleRepository
from alert.domain.entities import AlertRule
from alert.domain.enums import AlertSeverity, RuleType
from alert.infrastructure.db.models import AlertRuleModel
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AlertRuleRepository(IAlertRuleRepository):
    """Manages ``alert_rules`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, rule: AlertRule) -> None:
        self._session.add(self._to_model(rule))
        await self._session.flush()

    async def get_by_id(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> AlertRule | None:
        stmt = select(AlertRuleModel).where(
            AlertRuleModel.rule_id == rule_id,
            AlertRuleModel.tenant_id == tenant_id,
            AlertRuleModel.user_id == user_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(row) if row is not None else None

    async def list_by_owner(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        enabled: bool | None = None,
        rule_type: RuleType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AlertRule]:
        stmt = select(AlertRuleModel).where(
            AlertRuleModel.tenant_id == tenant_id,
            AlertRuleModel.user_id == user_id,
        )
        if enabled is not None:
            stmt = stmt.where(AlertRuleModel.enabled.is_(enabled))
        if rule_type is not None:
            stmt = stmt.where(AlertRuleModel.rule_type == rule_type.value)
        stmt = stmt.order_by(AlertRuleModel.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    async def count_by_owner(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        enabled: bool | None = None,
        rule_type: RuleType | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AlertRuleModel).where(
            AlertRuleModel.tenant_id == tenant_id,
            AlertRuleModel.user_id == user_id,
        )
        if enabled is not None:
            stmt = stmt.where(AlertRuleModel.enabled.is_(enabled))
        if rule_type is not None:
            stmt = stmt.where(AlertRuleModel.rule_type == rule_type.value)
        return int((await self._session.execute(stmt)).scalar_one())

    async def update(self, rule: AlertRule) -> bool:
        stmt = (
            sa_update(AlertRuleModel)
            .where(
                AlertRuleModel.rule_id == rule.rule_id,
                AlertRuleModel.tenant_id == rule.tenant_id,
                AlertRuleModel.user_id == rule.user_id,
            )
            .values(
                name=rule.name,
                condition=rule.condition,
                entity_id=rule.entity_id,
                node_a_entity_id=rule.node_a_entity_id,
                node_b_entity_id=rule.node_b_entity_id,
                severity=rule.severity.value,
                enabled=rule.enabled,
                cooldown_seconds=rule.cooldown_seconds,
                notify_in_app=rule.notify_in_app,
                notify_email=rule.notify_email,
                last_state=rule.last_state,
                updated_at=utc_now(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    async def delete(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        stmt = sa_delete(AlertRuleModel).where(
            AlertRuleModel.rule_id == rule_id,
            AlertRuleModel.tenant_id == tenant_id,
            AlertRuleModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined,no-any-return]

    async def list_enabled_by_type(self, rule_type: RuleType) -> list[AlertRule]:
        stmt = select(AlertRuleModel).where(
            AlertRuleModel.rule_type == rule_type.value,
            AlertRuleModel.enabled.is_(True),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_entity(r) for r in rows]

    # ── Mapping ──────────────────────────────────────────────────────────────

    @staticmethod
    def _to_model(rule: AlertRule) -> AlertRuleModel:
        return AlertRuleModel(
            rule_id=rule.rule_id,
            tenant_id=rule.tenant_id,
            user_id=rule.user_id,
            rule_type=rule.rule_type.value,
            name=rule.name,
            entity_id=rule.entity_id,
            node_a_entity_id=rule.node_a_entity_id,
            node_b_entity_id=rule.node_b_entity_id,
            condition=rule.condition,
            severity=rule.severity.value,
            enabled=rule.enabled,
            cooldown_seconds=rule.cooldown_seconds,
            notify_in_app=rule.notify_in_app,
            notify_email=rule.notify_email,
            last_state=rule.last_state,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )

    @staticmethod
    def _to_entity(row: AlertRuleModel) -> AlertRule:
        return AlertRule(
            rule_id=row.rule_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            rule_type=RuleType(row.rule_type),
            name=row.name,
            entity_id=row.entity_id,
            node_a_entity_id=row.node_a_entity_id,
            node_b_entity_id=row.node_b_entity_id,
            condition=dict(row.condition),
            severity=AlertSeverity(row.severity),
            enabled=row.enabled,
            cooldown_seconds=row.cooldown_seconds,
            notify_in_app=row.notify_in_app,
            notify_email=row.notify_email,
            last_state=dict(row.last_state) if row.last_state is not None else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
