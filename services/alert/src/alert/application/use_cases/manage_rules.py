"""CRUD use cases for standing alert rules (PLAN-0113 T-1-04).

R25: each use case depends only on the ``IAlertRuleRepository`` ABC — the
concrete repository + session are wired by the DI factory layer.

R27 read/write split:
  - ``ListRules`` / ``GetRule`` read the read-replica session (via a repo built
    on ``ReadDbSessionDep``).
  - ``CreateRule`` / ``UpdateRule`` / ``DeleteRule`` use the write session and
    commit it.

Owner scoping: every operation is bound to ``(tenant_id, user_id)`` from the
JWT. A cross-owner ``GetRule`` returns None (mapped to 404); a cross-owner
update/delete returns False.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from alert.domain.entities import AlertRule
from alert.domain.errors import RuleLimitExceededError, RuleNotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from alert.application.ports.repositories import IAlertRuleRepository
    from alert.domain.enums import AlertSeverity, RuleType


# Default per-user rule cap (PRD §9 / config ``ALERT_RULE_MAX_PER_USER``).
DEFAULT_MAX_RULES_PER_USER = 200


@dataclass
class CreateRuleInput:
    """Validated, owner-scoped input for rule creation.

    ``condition`` is the already-validated discriminated-union dict; keying
    fields (entity_id / node_a / node_b) are derived by the API layer from the
    condition so the use case stays transport-agnostic.
    """

    tenant_id: UUID
    user_id: UUID
    rule_type: RuleType
    name: str
    condition: dict[str, object]
    severity: AlertSeverity
    enabled: bool = True
    cooldown_seconds: int | None = None
    notify_in_app: bool = True
    notify_email: bool = False
    entity_id: UUID | None = None
    node_a_entity_id: UUID | None = None
    node_b_entity_id: UUID | None = None


class CreateRule:
    """Create a standing rule (write path — commits)."""

    def __init__(
        self,
        repo: IAlertRuleRepository,
        session: AsyncSession,
        *,
        max_per_user: int = DEFAULT_MAX_RULES_PER_USER,
    ) -> None:
        self._repo = repo
        self._session = session
        self._max_per_user = max_per_user

    async def execute(self, data: CreateRuleInput) -> AlertRule:
        # Per-user cap (PRD §9): count existing rules before inserting.
        existing = await self._repo.count_by_owner(data.tenant_id, data.user_id)
        if existing >= self._max_per_user:
            raise RuleLimitExceededError(f"User has reached the maximum of {self._max_per_user} alert rules")

        # ``AlertRule.create`` enforces the keying invariant (raises ValueError
        # for KG with missing/equal nodes, or non-KG with no entity_id).
        rule = AlertRule.create(
            rule_type=data.rule_type,
            name=data.name,
            tenant_id=data.tenant_id,
            user_id=data.user_id,
            condition=data.condition,
            entity_id=data.entity_id,
            node_a_entity_id=data.node_a_entity_id,
            node_b_entity_id=data.node_b_entity_id,
            severity=data.severity,
            enabled=data.enabled,
            cooldown_seconds=data.cooldown_seconds,
            notify_in_app=data.notify_in_app,
            notify_email=data.notify_email,
        )
        await self._repo.save(rule)
        await self._session.commit()
        return rule


class ListRules:
    """List the caller's rules (read path)."""

    def __init__(self, repo: IAlertRuleRepository) -> None:
        self._repo = repo

    async def execute(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        enabled: bool | None = None,
        rule_type: RuleType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AlertRule], int]:
        rules = await self._repo.list_by_owner(
            tenant_id,
            user_id,
            enabled=enabled,
            rule_type=rule_type,
            limit=limit,
            offset=offset,
        )
        total = await self._repo.count_by_owner(tenant_id, user_id, enabled=enabled, rule_type=rule_type)
        return rules, total


class GetRule:
    """Fetch a single owned rule (read path)."""

    def __init__(self, repo: IAlertRuleRepository) -> None:
        self._repo = repo

    async def execute(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> AlertRule:
        rule = await self._repo.get_by_id(rule_id, tenant_id, user_id)
        if rule is None:
            raise RuleNotFoundError(str(rule_id))
        return rule


@dataclass
class UpdateRuleInput:
    """Partial-update fields. ``None`` means "leave unchanged"."""

    name: str | None = None
    condition: dict[str, object] | None = None
    severity: AlertSeverity | None = None
    enabled: bool | None = None
    cooldown_seconds: int | None = None
    notify_in_app: bool | None = None
    notify_email: bool | None = None
    # Derived keying fields when ``condition`` changes (set by the API layer).
    entity_id: UUID | None = None
    node_a_entity_id: UUID | None = None
    node_b_entity_id: UUID | None = None


class UpdateRule:
    """Patch an owned rule (write path — commits).

    Changing ``condition`` resets ``last_state`` to None so the edge-trigger
    re-arms against the new threshold (PRD §6.2).
    """

    def __init__(self, repo: IAlertRuleRepository, session: AsyncSession) -> None:
        self._repo = repo
        self._session = session

    async def execute(self, rule_id: UUID, tenant_id: UUID, user_id: UUID, patch: UpdateRuleInput) -> AlertRule:
        rule = await self._repo.get_by_id(rule_id, tenant_id, user_id)
        if rule is None:
            raise RuleNotFoundError(str(rule_id))

        if patch.name is not None:
            rule.name = patch.name
        if patch.severity is not None:
            rule.severity = patch.severity
        if patch.enabled is not None:
            rule.enabled = patch.enabled
        if patch.cooldown_seconds is not None:
            if patch.cooldown_seconds < 0:
                raise ValueError("cooldown_seconds must be >= 0")
            rule.cooldown_seconds = patch.cooldown_seconds
        if patch.notify_in_app is not None:
            rule.notify_in_app = patch.notify_in_app
        if patch.notify_email is not None:
            rule.notify_email = patch.notify_email

        if patch.condition is not None:
            rule.condition = patch.condition
            # Keying fields ride along with a condition change.
            rule.entity_id = patch.entity_id
            rule.node_a_entity_id = patch.node_a_entity_id
            rule.node_b_entity_id = patch.node_b_entity_id
            # Re-arm: a new threshold must not inherit stale edge memory.
            rule.last_state = None

        await self._repo.update(rule)
        await self._session.commit()
        return rule


class DeleteRule:
    """Delete an owned rule (write path — commits)."""

    def __init__(self, repo: IAlertRuleRepository, session: AsyncSession) -> None:
        self._repo = repo
        self._session = session

    async def execute(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> None:
        deleted = await self._repo.delete(rule_id, tenant_id, user_id)
        if not deleted:
            raise RuleNotFoundError(str(rule_id))
        await self._session.commit()
