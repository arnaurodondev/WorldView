"""Unit tests for the discriminated-union condition value objects (PLAN-0113 T-1-01)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from alert.domain.enums import RuleType
from alert.domain.rule_conditions import (
    FundamentalCrossCondition,
    KgConnectionCondition,
    NewsCountCondition,
    NewsMomentumCondition,
    PriceCrossCondition,
    parse_condition,
)
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def test_condition_discriminated_union_validation_each_type_valid() -> None:
    """Each rule type's canonical payload validates + round-trips."""
    iid = str(uuid4())
    eid = str(uuid4())
    eid2 = str(uuid4())

    price = parse_condition(RuleType.PRICE_CROSS, {"instrument_id": iid, "operator": "above", "value": 200.0})
    assert isinstance(price, PriceCrossCondition)

    count = parse_condition(RuleType.NEWS_COUNT, {"entity_id": eid, "window": "7d", "threshold": 5})
    assert isinstance(count, NewsCountCondition)

    momentum = parse_condition(RuleType.NEWS_MOMENTUM, {"entity_id": eid, "window_hours": 24, "delta_pct": 50.0})
    assert isinstance(momentum, NewsMomentumCondition)
    assert momentum.min_count == 2  # default

    kg = parse_condition(RuleType.KG_CONNECTION, {"source_entity_id": eid, "target_entity_id": eid2, "max_hops": 2})
    assert isinstance(kg, KgConnectionCondition)

    fund = parse_condition(
        RuleType.FUNDAMENTAL_CROSS,
        {"instrument_id": iid, "metric_key": "pe_ratio", "operator": "below", "value": 15.0},
    )
    assert isinstance(fund, FundamentalCrossCondition)


def test_condition_rejects_unknown_fields() -> None:
    """extra='forbid' — a typo'd field fails loudly rather than silently dropping."""
    with pytest.raises(ValidationError):
        parse_condition(
            RuleType.PRICE_CROSS,
            {"instrument_id": str(uuid4()), "operator": "above", "value": 1.0, "bogus": 1},
        )


def test_price_cross_value_positive() -> None:
    with pytest.raises(ValidationError):
        parse_condition(RuleType.PRICE_CROSS, {"instrument_id": str(uuid4()), "operator": "above", "value": 0})
    with pytest.raises(ValidationError):
        parse_condition(RuleType.PRICE_CROSS, {"instrument_id": str(uuid4()), "operator": "above", "value": -5})


def test_price_cross_operator_allowlist() -> None:
    with pytest.raises(ValidationError):
        parse_condition(RuleType.PRICE_CROSS, {"instrument_id": str(uuid4()), "operator": "equals", "value": 1.0})


def test_news_count_window_allowlist() -> None:
    """Only the v1 windows are accepted; 30d is rejected."""
    ok = parse_condition(RuleType.NEWS_COUNT, {"entity_id": str(uuid4()), "window": "24h", "threshold": 3})
    assert isinstance(ok, NewsCountCondition)
    with pytest.raises(ValidationError):
        parse_condition(RuleType.NEWS_COUNT, {"entity_id": str(uuid4()), "window": "30d", "threshold": 3})


def test_news_count_threshold_min() -> None:
    with pytest.raises(ValidationError):
        parse_condition(RuleType.NEWS_COUNT, {"entity_id": str(uuid4()), "window": "7d", "threshold": 0})


def test_news_momentum_window_hours_allowlist() -> None:
    with pytest.raises(ValidationError):
        parse_condition(RuleType.NEWS_MOMENTUM, {"entity_id": str(uuid4()), "window_hours": 12, "delta_pct": 10.0})


def test_kg_max_hops_range() -> None:
    with pytest.raises(ValidationError):
        parse_condition(
            RuleType.KG_CONNECTION,
            {"source_entity_id": str(uuid4()), "target_entity_id": str(uuid4()), "max_hops": 4},
        )
    with pytest.raises(ValidationError):
        parse_condition(
            RuleType.KG_CONNECTION,
            {"source_entity_id": str(uuid4()), "target_entity_id": str(uuid4()), "max_hops": 0},
        )


def test_fundamental_metric_key_non_empty() -> None:
    with pytest.raises(ValidationError):
        parse_condition(
            RuleType.FUNDAMENTAL_CROSS,
            {"instrument_id": str(uuid4()), "metric_key": "", "operator": "above", "value": 1.0},
        )


def test_condition_json_round_trip() -> None:
    """model_dump(mode='json') produces a serialisable dict that re-validates."""
    iid = str(uuid4())
    cond = parse_condition(RuleType.PRICE_CROSS, {"instrument_id": iid, "operator": "below", "value": 99.5})
    dumped = cond.model_dump(mode="json")
    again = parse_condition(RuleType.PRICE_CROSS, dumped)
    assert again == cond
