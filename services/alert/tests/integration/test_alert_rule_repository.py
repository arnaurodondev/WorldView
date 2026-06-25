"""Integration tests for AlertRuleRepository round-trip (PLAN-0113 T-1-03).

Requires the testcontainer Postgres (skipped when Docker unavailable). Verifies
persistence, owner filtering, list-enabled-by-type, update, delete, and the
keying CHECK constraint.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from alert.domain.entities import AlertRule
from alert.domain.enums import AlertSeverity, RuleType
from alert.infrastructure.db.repositories.alert_rule import AlertRuleRepository
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def _price_rule(tenant, user, *, enabled=True):  # type: ignore[no-untyped-def]
    return AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="price rule",
        tenant_id=tenant,
        user_id=user,
        condition={"instrument_id": str(uuid4()), "operator": "above", "value": 100.0},
        entity_id=uuid4(),
        severity=AlertSeverity.HIGH,
        enabled=enabled,
    )


@pytest.mark.asyncio
async def test_repo_round_trip(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = AlertRuleRepository(db_session)
    tenant, user = uuid4(), uuid4()
    rule = _price_rule(tenant, user)

    await repo.save(rule)
    fetched = await repo.get_by_id(rule.rule_id, tenant, user)
    assert fetched is not None
    assert fetched.rule_type is RuleType.PRICE_CROSS
    assert fetched.severity is AlertSeverity.HIGH
    assert fetched.condition["value"] == 100.0


@pytest.mark.asyncio
async def test_repo_owner_filter(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = AlertRuleRepository(db_session)
    tenant, user = uuid4(), uuid4()
    rule = _price_rule(tenant, user)
    await repo.save(rule)
    # Wrong user → not found.
    assert await repo.get_by_id(rule.rule_id, tenant, uuid4()) is None
    rules = await repo.list_by_owner(tenant, user)
    assert len(rules) == 1


@pytest.mark.asyncio
async def test_repo_list_enabled_by_type(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = AlertRuleRepository(db_session)
    tenant, user = uuid4(), uuid4()
    await repo.save(_price_rule(tenant, user, enabled=True))
    await repo.save(_price_rule(tenant, user, enabled=False))
    # list_enabled_by_type is owner-agnostic (poller scan), so scope the assertion
    # to this test's owner to stay deterministic if other tests committed rows.
    enabled = [r for r in await repo.list_enabled_by_type(RuleType.PRICE_CROSS) if r.user_id == user]
    assert len(enabled) == 1
    assert enabled[0].enabled is True


@pytest.mark.asyncio
async def test_repo_update_and_delete(db_session) -> None:  # type: ignore[no-untyped-def]
    repo = AlertRuleRepository(db_session)
    tenant, user = uuid4(), uuid4()
    rule = _price_rule(tenant, user)
    await repo.save(rule)

    rule.enabled = False
    rule.last_state = {"was_above": True}
    assert await repo.update(rule) is True
    refetched = await repo.get_by_id(rule.rule_id, tenant, user)
    assert refetched is not None
    assert refetched.enabled is False
    assert refetched.last_state == {"was_above": True}

    assert await repo.delete(rule.rule_id, tenant, user) is True
    assert await repo.get_by_id(rule.rule_id, tenant, user) is None


@pytest.mark.asyncio
async def test_keying_check_rejects_kg_equal_nodes(db_session) -> None:  # type: ignore[no-untyped-def]
    """The DB CHECK rejects a KG rule with equal nodes even if the domain is bypassed."""
    from alert.infrastructure.db.models import AlertRuleModel

    node = uuid4()
    bad = AlertRuleModel(
        rule_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        rule_type="KG_CONNECTION",
        name="bad",
        entity_id=None,
        node_a_entity_id=node,
        node_b_entity_id=node,  # equal → violates ck_alert_rules_keying
        condition={},
        severity="medium",
        enabled=True,
        cooldown_seconds=0,
        notify_in_app=True,
        notify_email=False,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
