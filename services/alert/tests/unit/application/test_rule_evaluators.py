"""Unit tests for the poll RuleEvaluators (PLAN-0113 W2 T-2-02..05).

Each evaluator is exercised against a lightweight stub client (no DB / no HTTP)
plus the shared ``AlertRule.should_fire`` edge logic so the tests cover the full
observe → decide path:
  - price/fundamental: edge below→above, above→below, no-fire-while-held, missing.
  - news-count: crosses threshold once, re-arms below, window allow-list.
  - news-momentum: delta threshold fire, min_count gate suppresses noise.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from alert.application.ports.signal_clients import IS3PriceClient, IS6NewsClient
from alert.application.rules.fundamental_cross import FundamentalCrossEvaluator
from alert.application.rules.news_count import NewsCountEvaluator
from alert.application.rules.news_momentum import NewsMomentumEvaluator
from alert.application.rules.price_cross import PriceCrossEvaluator
from alert.application.rules.registry import EvalContext
from alert.domain.entities import AlertRule
from alert.domain.enums import RuleType

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ── Stub clients ────────────────────────────────────────────────────────────


class _StubS3(IS3PriceClient):
    def __init__(self, price: float | None = None, metric: float | None = None) -> None:
        self._price = price
        self._metric = metric
        self.calls: list[tuple] = []

    async def get_price_batch(self, instrument_ids):  # type: ignore[no-untyped-def]
        self.calls.append(("price", tuple(instrument_ids)))
        if self._price is None:
            return {}
        return {instrument_ids[0]: self._price}

    async def get_fundamental_metric(self, instrument_id, metric):  # type: ignore[no-untyped-def]
        self.calls.append(("metric", instrument_id, metric))
        return self._metric


class _StubS6(IS6NewsClient):
    def __init__(
        self,
        count_7d: int | None = None,
        trending_count: int | None = None,
        momentum: tuple[float, int] | None = None,
    ) -> None:
        self._count_7d = count_7d
        self._trending_count = trending_count
        self._momentum = momentum

    async def get_news_count_7d(self, instrument_id):  # type: ignore[no-untyped-def]
        return self._count_7d

    async def get_trending_count(self, entity_id, window_hours):  # type: ignore[no-untyped-def]
        return self._trending_count

    async def get_trending_momentum(self, entity_id, window_hours):  # type: ignore[no-untyped-def]
        return self._momentum


# ── Rule factories ──────────────────────────────────────────────────────────


def _price_rule(instrument_id, value=100.0, operator="above", last_state=None) -> AlertRule:
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="px",
        tenant_id=uuid4(),
        user_id=uuid4(),
        entity_id=instrument_id,
        condition={"instrument_id": str(instrument_id), "operator": operator, "value": value},
    )
    rule.last_state = last_state
    return rule


def _news_count_rule(entity_id, threshold=5, window="7d", last_state=None) -> AlertRule:
    rule = AlertRule.create(
        rule_type=RuleType.NEWS_COUNT,
        name="nc",
        tenant_id=uuid4(),
        user_id=uuid4(),
        entity_id=entity_id,
        condition={"entity_id": str(entity_id), "window": window, "threshold": threshold},
    )
    rule.last_state = last_state
    return rule


def _momentum_rule(entity_id, delta_pct=50.0, min_count=2, last_state=None) -> AlertRule:
    rule = AlertRule.create(
        rule_type=RuleType.NEWS_MOMENTUM,
        name="nm",
        tenant_id=uuid4(),
        user_id=uuid4(),
        entity_id=entity_id,
        condition={
            "entity_id": str(entity_id),
            "window_hours": 24,
            "delta_pct": delta_pct,
            "min_count": min_count,
        },
    )
    rule.last_state = last_state
    return rule


# ── PriceCrossEvaluator ──────────────────────────────────────────────────────


class TestPriceCrossEvaluator:
    async def test_edge_below_to_above_fires(self) -> None:
        iid = uuid4()
        rule = _price_rule(iid, value=100.0, operator="above", last_state={"was_above": False})
        ctx = EvalContext(clients={"s3": _StubS3(price=150.0)})
        result = await PriceCrossEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert result.value == 150.0
        assert rule.should_fire(result, utc_now()) is True

    async def test_above_to_below_does_not_fire(self) -> None:
        iid = uuid4()
        # operator below: was already below (was_above True means "on fired side")
        rule = _price_rule(iid, value=100.0, operator="below", last_state={"was_above": True})
        ctx = EvalContext(clients={"s3": _StubS3(price=50.0)})
        result = await PriceCrossEvaluator().evaluate(rule, ctx)
        assert result is not None
        # already on fired side → not a new edge
        assert rule.should_fire(result, utc_now()) is False

    async def test_no_fire_while_held(self) -> None:
        iid = uuid4()
        rule = _price_rule(iid, value=100.0, operator="above", last_state={"was_above": True})
        ctx = EvalContext(clients={"s3": _StubS3(price=150.0)})
        result = await PriceCrossEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is False

    async def test_missing_price_skips(self) -> None:
        iid = uuid4()
        rule = _price_rule(iid, last_state=None)
        ctx = EvalContext(clients={"s3": _StubS3(price=None)})
        result = await PriceCrossEvaluator().evaluate(rule, ctx)
        assert result is None

    async def test_no_client_returns_none(self) -> None:
        rule = _price_rule(uuid4())
        result = await PriceCrossEvaluator().evaluate(rule, EvalContext(clients={}))
        assert result is None


# ── FundamentalCrossEvaluator ────────────────────────────────────────────────


class TestFundamentalCrossEvaluator:
    def _rule(self, iid, metric_key="pe_ratio", value=20.0, operator="above", last_state=None):
        rule = AlertRule.create(
            rule_type=RuleType.FUNDAMENTAL_CROSS,
            name="f",
            tenant_id=uuid4(),
            user_id=uuid4(),
            entity_id=iid,
            condition={
                "instrument_id": str(iid),
                "metric_key": metric_key,
                "operator": operator,
                "value": value,
            },
        )
        rule.last_state = last_state
        return rule

    async def test_edge_cross_fires(self) -> None:
        iid = uuid4()
        rule = self._rule(iid, value=20.0, operator="above", last_state={"was_above": False})
        ctx = EvalContext(clients={"s3": _StubS3(metric=30.0)})
        result = await FundamentalCrossEvaluator().evaluate(rule, ctx)
        assert result is not None and result.value == 30.0
        assert rule.should_fire(result, utc_now()) is True

    async def test_uses_last_value_no_refire(self) -> None:
        iid = uuid4()
        rule = self._rule(iid, value=20.0, operator="above", last_state={"was_above": True})
        ctx = EvalContext(clients={"s3": _StubS3(metric=30.0)})
        result = await FundamentalCrossEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is False

    async def test_missing_metric_skips(self) -> None:
        iid = uuid4()
        rule = self._rule(iid)
        ctx = EvalContext(clients={"s3": _StubS3(metric=None)})
        assert await FundamentalCrossEvaluator().evaluate(rule, ctx) is None

    async def test_cadence_is_six_hours(self) -> None:
        assert FundamentalCrossEvaluator().cadence_seconds == 21600


# ── NewsCountEvaluator ───────────────────────────────────────────────────────


class TestNewsCountEvaluator:
    async def test_crosses_threshold_once(self) -> None:
        eid = uuid4()
        rule = _news_count_rule(eid, threshold=5, window="7d", last_state={"last_count": 2})
        ctx = EvalContext(clients={"s6": _StubS6(count_7d=7)})
        result = await NewsCountEvaluator().evaluate(rule, ctx)
        assert result is not None and result.count == 7
        assert rule.should_fire(result, utc_now()) is True

    async def test_no_refire_while_held(self) -> None:
        eid = uuid4()
        rule = _news_count_rule(eid, threshold=5, window="7d", last_state={"last_count": 8})
        ctx = EvalContext(clients={"s6": _StubS6(count_7d=9)})
        result = await NewsCountEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is False

    async def test_rearm_below_threshold(self) -> None:
        eid = uuid4()
        # drops below then crosses again
        rule = _news_count_rule(eid, threshold=5, window="7d", last_state={"last_count": 2})
        ctx = EvalContext(clients={"s6": _StubS6(count_7d=6)})
        result = await NewsCountEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is True

    async def test_short_window_uses_trending(self) -> None:
        eid = uuid4()
        rule = _news_count_rule(eid, threshold=3, window="24h", last_state=None)
        ctx = EvalContext(clients={"s6": _StubS6(trending_count=4)})
        result = await NewsCountEvaluator().evaluate(rule, ctx)
        assert result is not None and result.count == 4

    async def test_none_count_skips(self) -> None:
        eid = uuid4()
        rule = _news_count_rule(eid, window="7d")
        ctx = EvalContext(clients={"s6": _StubS6(count_7d=None)})
        assert await NewsCountEvaluator().evaluate(rule, ctx) is None


# ── NewsMomentumEvaluator ────────────────────────────────────────────────────


class TestNewsMomentumEvaluator:
    async def test_delta_threshold_fires(self) -> None:
        eid = uuid4()
        rule = _momentum_rule(eid, delta_pct=50.0, min_count=2, last_state={"was_above": False})
        ctx = EvalContext(clients={"s6": _StubS6(momentum=(80.0, 5))})
        result = await NewsMomentumEvaluator().evaluate(rule, ctx)
        assert result is not None and result.delta_pct == 80.0 and result.count == 5
        assert rule.should_fire(result, utc_now()) is True

    async def test_min_count_gate_suppresses_noise(self) -> None:
        eid = uuid4()
        rule = _momentum_rule(eid, delta_pct=50.0, min_count=5, last_state={"was_above": False})
        # huge delta but only 2 articles → gated
        ctx = EvalContext(clients={"s6": _StubS6(momentum=(100.0, 2))})
        result = await NewsMomentumEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is False

    async def test_below_delta_no_fire(self) -> None:
        eid = uuid4()
        rule = _momentum_rule(eid, delta_pct=50.0, min_count=2, last_state={"was_above": False})
        ctx = EvalContext(clients={"s6": _StubS6(momentum=(10.0, 9))})
        result = await NewsMomentumEvaluator().evaluate(rule, ctx)
        assert result is not None
        assert rule.should_fire(result, utc_now()) is False

    async def test_absent_entity_skips(self) -> None:
        eid = uuid4()
        rule = _momentum_rule(eid)
        ctx = EvalContext(clients={"s6": _StubS6(momentum=None)})
        assert await NewsMomentumEvaluator().evaluate(rule, ctx) is None


# ── is_due cadence throttling (cross-evaluator) ──────────────────────────────


class TestCadenceThrottle:
    def test_is_due_throttles_recent_check(self) -> None:
        rule = _price_rule(uuid4())
        rule.last_state = {"last_checked_at": utc_now().isoformat()}
        # checked just now → not due for a 60s cadence
        assert rule.is_due(utc_now(), 60) is False

    def test_is_due_after_cadence_elapsed(self) -> None:
        rule = _price_rule(uuid4())
        rule.last_state = {"last_checked_at": (utc_now() - timedelta(seconds=120)).isoformat()}
        assert rule.is_due(utc_now(), 60) is True
