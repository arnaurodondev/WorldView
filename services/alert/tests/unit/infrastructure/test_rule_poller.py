"""Unit tests for the alert-rule poller cycle (PLAN-0113 T-1-06).

These exercise ``run_poll_cycle`` with a stubbed repository + a no-op async
session factory — no DB required. They verify the loop loads due rules and (with
the registry empty in Wave 1) no-ops without firing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from alert.config import Settings
from alert.domain.entities import AlertRule
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

    async def list_enabled_by_type(self, rule_type: RuleType) -> list[AlertRule]:
        return self._by_type.get(rule_type, [])


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


@pytest.mark.asyncio
async def test_poller_loads_due_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule with no prior check is due → counted; empty registry → no fire."""
    rule = _price_rule()
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    due = await poller_main.run_poll_cycle(_fake_session_factory(), _settings())
    assert due == 1


@pytest.mark.asyncio
async def test_poller_throttles_not_due_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rule checked seconds ago (cadence 60s) is not due → not counted."""
    rule = _price_rule(last_checked=utc_now())
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    due = await poller_main.run_poll_cycle(_fake_session_factory(), _settings())
    assert due == 0


@pytest.mark.asyncio
async def test_poller_due_after_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    rule = _price_rule(last_checked=utc_now() - timedelta(seconds=120))
    repo = _StubRepo({RuleType.PRICE_CROSS: [rule]})
    monkeypatch.setattr(poller_main, "AlertRuleRepository", lambda _s: repo)

    due = await poller_main.run_poll_cycle(_fake_session_factory(), _settings())
    assert due == 1
