"""Unit tests for the alert-rule poller cycle (PLAN-0113 T-1-06 + T-2-06).

These exercise ``run_poll_cycle`` with a stubbed repository + a no-op async
session factory — no DB required. They verify the loop loads due rules, throttles
by per-type cadence, and (Wave 2) drives the evaluator → should_fire → fire path.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alert.application.rules.registry import EvalContext
from alert.config import Settings
from alert.domain.entities import AlertRule, EvalResult
from alert.domain.enums import RuleType
from alert.infrastructure.rules import poller_main

from common.time import utc_now  # type: ignore[import-untyped]


def _settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://x:x@localhost/x")


def _fake_session_factory():  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def _cm():  # type: ignore[no-untyped-def]
        yield object()

    return _cm


class _StubRepo:
    """In-memory repo: returns the rules it was seeded with, keyed by type."""

    def __init__(self, by_type: dict[RuleType, list[AlertRule]]) -> None:
        self._by_type = by_type
        self.updated: list[AlertRule] = []

    async def list_enabled_by_type(self, rule_type: RuleType) -> list[AlertRule]:
        return self._by_type.get(rule_type, [])

    async def update(self, rule: AlertRule) -> bool:
        self.updated.append(rule)
        return True


def _price_rule(last_checked=None) -> AlertRule:  # type: ignore[no-untyped-def]
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"instrument_id": str(uuid4()), "operator": "above", "value": 1.0},
        entity_id=uuid4(),
    )
    if last_checked is not None:
        rule.last_state = {"last_checked_at": last_checked.isoformat()}
    return rule


def _empty_ctx() -> EvalContext:
    """A context with no clients → every evaluator returns None (skip)."""
    return EvalContext(clients={})


def _noop_fire() -> AsyncMock:
    fire = AsyncMock()
    fire.execute = AsyncMock()
    return fire


@pytest.mark.asyncio
async def test_poller_loads_due_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule with no prior check is due → counted (no client → skipped, no fire)."""
    rule = _price_rule()
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    fire = _noop_fire()
    due = await poller_main.run_poll_cycle(_fake_session_factory(), _settings(), ctx=_empty_ctx(), fire_use_case=fire)
    assert due == 1
    fire.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_poller_throttles_not_due_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule checked seconds ago (cadence 60s) is not due → not counted."""
    rule = _price_rule(last_checked=utc_now())
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    due = await poller_main.run_poll_cycle(
        _fake_session_factory(), _settings(), ctx=_empty_ctx(), fire_use_case=_noop_fire()
    )
    assert due == 0


@pytest.mark.asyncio
async def test_poller_due_after_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = _price_rule(last_checked=utc_now() - timedelta(seconds=120))
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    due = await poller_main.run_poll_cycle(
        _fake_session_factory(), _settings(), ctx=_empty_ctx(), fire_use_case=_noop_fire()
    )
    assert due == 1


@pytest.mark.asyncio
async def test_poller_fires_once_on_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """A price-cross rule whose evaluator observes an above-edge fires exactly once."""

    iid = uuid4()
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="fire",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"instrument_id": str(iid), "operator": "above", "value": 100.0},
        entity_id=iid,
    )
    rule.last_state = {"was_above": False}
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    # Register the real evaluator + a stub S3 client returning a crossing price.
    poller_main.register_default_evaluators()

    from alert.application.ports.signal_clients import IS3PriceClient

    class _StubS3(IS3PriceClient):
        async def get_price_batch(self, ids):  # type: ignore[no-untyped-def]
            return {ids[0]: 150.0}

        async def get_fundamental_metric(self, *_a, **_k):  # type: ignore[no-untyped-def]
            return None

        async def get_fundamental_metric_keys(self):  # type: ignore[no-untyped-def]
            return None

    ctx = EvalContext(clients={"s3": _StubS3()})
    fire = _noop_fire()
    due = await poller_main.run_poll_cycle(_fake_session_factory(), _settings(), ctx=ctx, fire_use_case=fire)
    assert due == 1
    fire.execute.assert_awaited_once()
    fired_rule, fired_result = fire.execute.call_args.args
    assert fired_rule is rule
    assert isinstance(fired_result, EvalResult)
    assert fired_result.value == 150.0


@pytest.mark.asyncio
async def test_poller_persists_no_fire_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A below-threshold observation does not fire but advances last_state."""
    iid = uuid4()
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="nofire",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"instrument_id": str(iid), "operator": "above", "value": 100.0},
        entity_id=iid,
    )
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)
    poller_main.register_default_evaluators()

    from alert.application.ports.signal_clients import IS3PriceClient

    class _StubS3(IS3PriceClient):
        async def get_price_batch(self, ids):  # type: ignore[no-untyped-def]
            return {ids[0]: 50.0}  # below threshold

        async def get_fundamental_metric(self, *_a, **_k):  # type: ignore[no-untyped-def]
            return None

        async def get_fundamental_metric_keys(self):  # type: ignore[no-untyped-def]
            return None

    ctx = EvalContext(clients={"s3": _StubS3()})
    fire = _noop_fire()
    await poller_main.run_poll_cycle(_fake_session_factory(), _settings(), ctx=ctx, fire_use_case=fire)
    fire.execute.assert_not_awaited()
    # no-fire path updates the rule (last_checked_at advanced)
    assert any(r is rule for r in repo.updated)
    assert rule.last_state is not None
    assert rule.last_state.get("last_fired_at") is None
