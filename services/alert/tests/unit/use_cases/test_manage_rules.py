"""Unit tests for the rule CRUD use cases (PLAN-0113 T-1-04).

Uses an in-memory fake ``IAlertRuleRepository`` + a fake session (commit/rollback
no-ops) so the use-case logic (owner scoping, cap, re-arm) is tested in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from alert.application.use_cases.manage_rules import (
    CreateRule,
    CreateRuleInput,
    DeleteRule,
    GetRule,
    ListRules,
    UpdateRule,
    UpdateRuleInput,
)
from alert.domain.enums import AlertSeverity, RuleType
from alert.domain.errors import RuleLimitExceededError, RuleNotFoundError

if TYPE_CHECKING:
    from alert.domain.entities import AlertRule


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _FakeRuleRepo:
    """Minimal in-memory IAlertRuleRepository, owner-scoped."""

    def __init__(self) -> None:
        self._rows: dict[UUID, AlertRule] = {}

    async def save(self, rule: AlertRule) -> None:
        self._rows[rule.rule_id] = rule

    async def get_by_id(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> AlertRule | None:
        r = self._rows.get(rule_id)
        if r is None or r.tenant_id != tenant_id or r.user_id != user_id:
            return None
        return r

    async def list_by_owner(self, tenant_id, user_id, *, enabled=None, rule_type=None, limit=50, offset=0):  # type: ignore[no-untyped-def]
        rows = [r for r in self._rows.values() if r.tenant_id == tenant_id and r.user_id == user_id]
        if enabled is not None:
            rows = [r for r in rows if r.enabled == enabled]
        if rule_type is not None:
            rows = [r for r in rows if r.rule_type == rule_type]
        return rows[offset : offset + limit]

    async def count_by_owner(self, tenant_id, user_id, *, enabled=None, rule_type=None):  # type: ignore[no-untyped-def]
        return len(await self.list_by_owner(tenant_id, user_id, enabled=enabled, rule_type=rule_type, limit=10**9))

    async def update(self, rule: AlertRule) -> bool:
        existing = await self.get_by_id(rule.rule_id, rule.tenant_id, rule.user_id)
        if existing is None:
            return False
        self._rows[rule.rule_id] = rule
        return True

    async def delete(self, rule_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        r = await self.get_by_id(rule_id, tenant_id, user_id)
        if r is None:
            return False
        del self._rows[rule_id]
        return True

    async def list_enabled_by_type(self, rule_type: RuleType) -> list[AlertRule]:
        return [r for r in self._rows.values() if r.rule_type == rule_type and r.enabled]


def _price_input(tenant: UUID, user: UUID, value: float = 100.0) -> CreateRuleInput:
    return CreateRuleInput(
        tenant_id=tenant,
        user_id=user,
        rule_type=RuleType.PRICE_CROSS,
        name="my rule",
        condition={"instrument_id": str(uuid4()), "operator": "above", "value": value},
        severity=AlertSeverity.MEDIUM,
        entity_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_crud_roundtrip() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()

    created = await CreateRule(repo, session).execute(_price_input(tenant, user))
    assert session.commits == 1

    fetched = await GetRule(repo).execute(created.rule_id, tenant, user)
    assert fetched.rule_id == created.rule_id

    rules, total = await ListRules(repo).execute(tenant, user)
    assert total == 1 and len(rules) == 1

    await DeleteRule(repo, session).execute(created.rule_id, tenant, user)
    with pytest.raises(RuleNotFoundError):
        await GetRule(repo).execute(created.rule_id, tenant, user)


@pytest.mark.asyncio
async def test_update_condition_resets_last_state() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()
    created = await CreateRule(repo, session).execute(_price_input(tenant, user))
    # Simulate accumulated edge memory.
    created.last_state = {"was_above": True, "last_fired_at": "2026-06-20T00:00:00+00:00"}
    await repo.update(created)

    new_iid = uuid4()
    patch = UpdateRuleInput(
        condition={"instrument_id": str(new_iid), "operator": "above", "value": 250.0},
        entity_id=new_iid,
    )
    updated = await UpdateRule(repo, session).execute(created.rule_id, tenant, user, patch)
    assert updated.last_state is None  # re-armed
    assert updated.condition["value"] == 250.0


@pytest.mark.asyncio
async def test_update_non_condition_keeps_last_state() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()
    created = await CreateRule(repo, session).execute(_price_input(tenant, user))
    created.last_state = {"was_above": True}
    await repo.update(created)

    updated = await UpdateRule(repo, session).execute(created.rule_id, tenant, user, UpdateRuleInput(enabled=False))
    assert updated.enabled is False
    assert updated.last_state == {"was_above": True}


@pytest.mark.asyncio
async def test_cross_owner_get_returns_not_found() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()
    created = await CreateRule(repo, session).execute(_price_input(tenant, user))

    other_user = uuid4()
    with pytest.raises(RuleNotFoundError):
        await GetRule(repo).execute(created.rule_id, tenant, other_user)


@pytest.mark.asyncio
async def test_cross_owner_delete_returns_not_found() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()
    created = await CreateRule(repo, session).execute(_price_input(tenant, user))
    with pytest.raises(RuleNotFoundError):
        await DeleteRule(repo, session).execute(created.rule_id, uuid4(), user)


@pytest.mark.asyncio
async def test_per_user_rule_cap_enforced() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant, user = uuid4(), uuid4()
    uc = CreateRule(repo, session, max_per_user=2)
    await uc.execute(_price_input(tenant, user))
    await uc.execute(_price_input(tenant, user))
    with pytest.raises(RuleLimitExceededError):
        await uc.execute(_price_input(tenant, user))


@pytest.mark.asyncio
async def test_list_filters_by_owner() -> None:
    repo, session = _FakeRuleRepo(), _FakeSession()
    tenant = uuid4()
    u1, u2 = uuid4(), uuid4()
    await CreateRule(repo, session).execute(_price_input(tenant, u1))
    await CreateRule(repo, session).execute(_price_input(tenant, u2))
    rules, total = await ListRules(repo).execute(tenant, u1)
    assert total == 1
