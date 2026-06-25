"""Unit tests for the AlertRule aggregate edge-trigger + cooldown logic (PLAN-0113 T-1-02)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from alert.domain.entities import DEFAULT_COOLDOWN_SECONDS, AlertRule, EvalResult
from alert.domain.enums import AlertSeverity, RuleType

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _price_rule(operator: str = "above", value: float = 200.0, cooldown: int | None = None) -> AlertRule:
    return AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"instrument_id": str(uuid4()), "operator": operator, "value": value},
        entity_id=uuid4(),
        cooldown_seconds=cooldown,
    )


def test_price_cross_edge_below_to_above() -> None:
    """Fires only on the no→yes transition; not while already above."""
    rule = _price_rule()
    now = utc_now()
    # First observation below threshold → no fire, records was_above=False.
    r1 = EvalResult(observed_at=now, value=150.0)
    assert rule.should_fire(r1, now) is False
    rule.last_state = rule.next_state(r1, now, fired=False)

    # Crosses above → fire (edge).
    r2 = EvalResult(observed_at=now, value=210.0)
    assert rule.should_fire(r2, now) is True
    rule.last_state = rule.next_state(r2, now, fired=True)

    # Still above → no re-fire (no new edge).
    r3 = EvalResult(observed_at=now + timedelta(hours=5), value=215.0)
    assert rule.should_fire(r3, now + timedelta(hours=5)) is False


def test_price_cross_below_operator() -> None:
    rule = _price_rule(operator="below", value=100.0)
    now = utc_now()
    r1 = EvalResult(observed_at=now, value=120.0)
    rule.last_state = rule.next_state(r1, now, fired=False)
    r2 = EvalResult(observed_at=now, value=90.0)
    assert rule.should_fire(r2, now) is True


def test_cooldown_suppresses_refire() -> None:
    """A fresh edge within the cooldown window does not fire."""
    rule = _price_rule(cooldown=3600)
    now = utc_now()
    rule.last_state = {"was_above": True, "last_fired_at": now.isoformat()}
    # Re-arm below then cross above again, but within cooldown.
    r_below = EvalResult(observed_at=now, value=150.0)
    rule.last_state = rule.next_state(r_below, now, fired=False)
    rule.last_state["last_fired_at"] = now.isoformat()  # keep recent fire
    r_above = EvalResult(observed_at=now + timedelta(minutes=10), value=210.0)
    assert rule.should_fire(r_above, now + timedelta(minutes=10)) is False
    # After cooldown elapses, the same edge fires.
    later = now + timedelta(hours=2)
    assert rule.should_fire(EvalResult(observed_at=later, value=210.0), later) is True


def test_news_count_rearm_below_threshold() -> None:
    rule = AlertRule.create(
        rule_type=RuleType.NEWS_COUNT,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"entity_id": str(uuid4()), "window": "7d", "threshold": 5},
        entity_id=uuid4(),
        cooldown_seconds=0,
    )
    now = utc_now()
    # First reaches threshold → fire.
    r1 = EvalResult(observed_at=now, count=6)
    assert rule.should_fire(r1, now) is True
    rule.last_state = rule.next_state(r1, now, fired=True)
    # Still above → no re-fire.
    r2 = EvalResult(observed_at=now, count=7)
    assert rule.should_fire(r2, now) is False
    rule.last_state = rule.next_state(r2, now, fired=False)
    # Drops below → re-arm.
    r3 = EvalResult(observed_at=now, count=2)
    rule.last_state = rule.next_state(r3, now, fired=False)
    # Crosses again → fire.
    r4 = EvalResult(observed_at=now, count=8)
    assert rule.should_fire(r4, now) is True


def test_news_momentum_min_count_gate() -> None:
    rule = AlertRule.create(
        rule_type=RuleType.NEWS_MOMENTUM,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"entity_id": str(uuid4()), "window_hours": 24, "delta_pct": 50.0, "min_count": 3},
        entity_id=uuid4(),
        cooldown_seconds=0,
    )
    now = utc_now()
    # delta high but count below min_count → no fire (noise suppressed).
    assert rule.should_fire(EvalResult(observed_at=now, delta_pct=80.0, count=2), now) is False
    # delta + count both satisfied → fire.
    assert rule.should_fire(EvalResult(observed_at=now, delta_pct=80.0, count=5), now) is True


def test_kg_connection_latches_once() -> None:
    a, b = uuid4(), uuid4()
    rule = AlertRule.create(
        rule_type=RuleType.KG_CONNECTION,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"source_entity_id": str(a), "target_entity_id": str(b), "max_hops": 3},
        node_a_entity_id=a,
        node_b_entity_id=b,
    )
    now = utc_now()
    r_connected = EvalResult(observed_at=now, connected=True)
    assert rule.should_fire(r_connected, now) is True
    rule.last_state = rule.next_state(r_connected, now, fired=True)
    # Latched — already connected → never fires again.
    assert rule.should_fire(EvalResult(observed_at=now, connected=True), now) is False


def test_fundamental_cross_uses_last_value() -> None:
    rule = AlertRule.create(
        rule_type=RuleType.FUNDAMENTAL_CROSS,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"instrument_id": str(uuid4()), "metric_key": "pe_ratio", "operator": "above", "value": 30.0},
        entity_id=uuid4(),
        cooldown_seconds=0,
    )
    now = utc_now()
    rule.last_state = rule.next_state(EvalResult(observed_at=now, value=25.0), now, fired=False)
    assert rule.should_fire(EvalResult(observed_at=now, value=35.0), now) is True


def test_rule_keying_invariant_kg_requires_distinct_nodes() -> None:
    a = uuid4()
    with pytest.raises(ValueError, match="differ"):
        AlertRule.create(
            rule_type=RuleType.KG_CONNECTION,
            name="t",
            tenant_id=uuid4(),
            user_id=uuid4(),
            condition={},
            node_a_entity_id=a,
            node_b_entity_id=a,
        )


def test_rule_keying_invariant_non_kg_requires_entity() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        AlertRule.create(
            rule_type=RuleType.PRICE_CROSS,
            name="t",
            tenant_id=uuid4(),
            user_id=uuid4(),
            condition={},
        )


def test_per_type_cooldown_default_applied() -> None:
    rule = _price_rule()
    assert rule.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS[RuleType.PRICE_CROSS] == 3600


def test_is_due_throttles_by_cadence() -> None:
    rule = _price_rule()
    now = utc_now()
    # No state → due immediately.
    assert rule.is_due(now, 60) is True
    rule.last_state = {"last_checked_at": now.isoformat()}
    # Just checked → not due for 60s.
    assert rule.is_due(now + timedelta(seconds=30), 60) is False
    # Cadence elapsed → due.
    assert rule.is_due(now + timedelta(seconds=90), 60) is True


def test_severity_persisted_on_rule() -> None:
    rule = AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="t",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={},
        entity_id=uuid4(),
        severity=AlertSeverity.HIGH,
    )
    assert rule.severity is AlertSeverity.HIGH
