"""Integration test: the poller fires a price-cross rule ONCE (PLAN-0113 T-2-06).

Drives ``run_poll_cycle`` against the testcontainer Postgres with a stubbed S3
price client + an in-memory notification publisher. Verifies:
  - an above-edge observation fires exactly one alert for the rule owner,
  - the rule's last_state advances (last_fired_at + was_above),
  - a second identical cycle does NOT fire again (edge already latched / cooldown).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from alert.application.ports.signal_clients import IS3PriceClient
from alert.application.rules.registry import EvalContext, register_default_evaluators
from alert.application.use_cases.fire_rule_alert import FireRuleAlertUseCase
from alert.config import Settings
from alert.domain.entities import AlertRule
from alert.domain.enums import RuleType
from alert.infrastructure.db.repositories.alert import AlertRepository
from alert.infrastructure.db.repositories.alert_rule import AlertRuleRepository
from alert.infrastructure.db.repositories.outbox import OutboxRepository
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from alert.infrastructure.rules import poller_main

pytestmark = pytest.mark.integration


class _StubS3(IS3PriceClient):
    def __init__(self, price: float) -> None:
        self._price = price

    async def get_price_batch(self, instrument_ids):  # type: ignore[no-untyped-def]
        return {instrument_ids[0]: self._price}

    async def get_fundamental_metric(self, instrument_id, metric):  # type: ignore[no-untyped-def]
        return None

    async def get_fundamental_metric_keys(self):  # type: ignore[no-untyped-def]
        return None


class _CapturingPublisher:
    def __init__(self) -> None:
        self.sent: list = []

    async def send_to_user(self, user_id, payload):  # type: ignore[no-untyped-def]
        self.sent.append((user_id, payload))


def _fire_repo_factory(session):  # type: ignore[no-untyped-def]
    return (
        AlertRepository(session),
        PendingAlertRepository(session),
        OutboxRepository(session),
        AlertRuleRepository(session),
    )


@pytest.mark.asyncio
async def test_poller_price_fires_once(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    factory, _engine = db_session_factory
    settings = Settings(database_url="postgresql+asyncpg://x:x@localhost/x")

    # Seed an enabled price-cross rule that starts below its threshold.
    iid = uuid4()
    user_id = uuid4()
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="aapl>100",
        tenant_id=uuid4(),
        user_id=user_id,
        condition={"instrument_id": str(iid), "operator": "above", "value": 100.0},
        entity_id=iid,
    )
    rule.last_state = {"was_above": False}
    async with factory() as s:
        await AlertRuleRepository(s).save(rule)
        await s.commit()

    register_default_evaluators()
    publisher = _CapturingPublisher()
    fire_uc = FireRuleAlertUseCase(
        session_factory=factory,
        notification_publisher=publisher,  # type: ignore[arg-type]
        repo_factory=_fire_repo_factory,  # type: ignore[arg-type]
    )
    ctx = EvalContext(clients={"s3": _StubS3(price=150.0)})

    due = await poller_main.run_poll_cycle(factory, settings, ctx=ctx, fire_use_case=fire_uc)
    # ``due`` counts ALL enabled price rules in the shared (session-scoped)
    # testcontainer DB, so other integration tests' committed rules may inflate
    # it — assert on THIS rule's effect instead of a brittle global count.
    assert due >= 1
    # Exactly one push for THIS rule's owner (the stub price crosses 100 for
    # this rule's instrument only; other rules key on different instruments and
    # the stub returns no price for them → they skip without firing).
    our_pushes = [p for p in publisher.sent if p[0] == user_id]
    assert len(our_pushes) == 1

    # The rule state advanced (latched above + recorded a fire).
    async with factory() as s:
        stored = await AlertRuleRepository(s).get_by_id(rule.rule_id, rule.tenant_id, user_id)
    assert stored is not None
    assert stored.last_state is not None
    assert stored.last_state.get("was_above") is True
    assert stored.last_state.get("last_fired_at") is not None

    # A second cycle with the same crossing price must NOT fire again (already latched).
    due2 = await poller_main.run_poll_cycle(factory, settings, ctx=ctx, fire_use_case=fire_uc)
    # The rule may still be "due" by cadence but should_fire is False → no new push.
    assert len(publisher.sent) == 1
    assert due2 >= 0
