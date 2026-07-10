"""Unit tests for PredictionRuleEvaluator + PredictionCondition (PLAN-0056 Wave D3).

Covers: condition validation/registration, evaluator skip semantics (no client /
no signal / polarity-filtered), a positive observation, and the shared
AlertRule.should_fire PREDICTION branch (score floor + cooldown).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from alert.application.ports.signal_clients import IPredictionSignalClient
from alert.application.rules.prediction import PredictionRuleEvaluator
from alert.application.rules.registry import EvalContext, register_default_evaluators
from alert.domain.entities import AlertRule, EvalResult
from alert.domain.enums import RuleType
from alert.domain.rule_conditions import PredictionCondition, parse_condition

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit

_ENTITY = uuid4()
_TENANT = uuid4()
_USER = uuid4()


class _FakeClient(IPredictionSignalClient):
    def __init__(self, result: tuple[float, str] | None) -> None:
        self._result = result

    async def get_latest_impact(self, entity_id):  # type: ignore[no-untyped-def]
        return self._result


def _rule(condition: dict | None = None) -> AlertRule:
    return AlertRule.create(
        rule_type=RuleType.PREDICTION,
        name="ACME prediction watch",
        tenant_id=_TENANT,
        user_id=_USER,
        condition=condition or {"entity_id": str(_ENTITY)},
        entity_id=_ENTITY,
    )


# ── Condition ─────────────────────────────────────────────────────────────────


class TestPredictionCondition:
    @pytest.mark.unit
    def test_valid_condition(self) -> None:
        cond = parse_condition(RuleType.PREDICTION, {"entity_id": str(_ENTITY), "min_impact_score": 0.5})
        assert isinstance(cond, PredictionCondition)
        assert cond.min_impact_score == pytest.approx(0.5)

    @pytest.mark.unit
    def test_registered_in_map(self) -> None:
        cond = parse_condition(RuleType.PREDICTION, {"entity_id": str(_ENTITY)})
        assert cond.min_impact_score == 0.0  # default
        assert cond.polarities is None

    @pytest.mark.unit
    def test_rejects_out_of_range_score(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            parse_condition(RuleType.PREDICTION, {"entity_id": str(_ENTITY), "min_impact_score": 1.5})

    @pytest.mark.unit
    def test_rejects_unknown_field(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            parse_condition(RuleType.PREDICTION, {"entity_id": str(_ENTITY), "bogus": 1})


# ── Registry ──────────────────────────────────────────────────────────────────


class TestPredictionRegistration:
    @pytest.mark.unit
    def test_registered_as_event_evaluator(self) -> None:
        registry = register_default_evaluators()
        ev = registry[RuleType.PREDICTION]
        assert isinstance(ev, PredictionRuleEvaluator)
        assert ev.trigger == "event"
        assert ev.cadence_seconds is None
        assert "market.prediction.signal.v1" in ev.relevant_topics()


# ── Evaluator ─────────────────────────────────────────────────────────────────


class TestPredictionEvaluator:
    @pytest.mark.unit
    async def test_no_client_skips(self) -> None:
        ev = PredictionRuleEvaluator()
        assert await ev.evaluate(_rule(), EvalContext(clients={})) is None

    @pytest.mark.unit
    async def test_no_signal_skips(self) -> None:
        ev = PredictionRuleEvaluator()
        ctx = EvalContext(clients={"prediction": _FakeClient(None)})
        assert await ev.evaluate(_rule(), ctx) is None

    @pytest.mark.unit
    async def test_positive_observation_returns_score(self) -> None:
        ev = PredictionRuleEvaluator()
        ctx = EvalContext(clients={"prediction": _FakeClient((0.8, "bearish"))})
        result = await ev.evaluate(_rule(), ctx)
        assert result is not None
        assert result.value == pytest.approx(0.8)

    @pytest.mark.unit
    async def test_polarity_filter_skips_disallowed(self) -> None:
        ev = PredictionRuleEvaluator()
        ctx = EvalContext(clients={"prediction": _FakeClient((0.8, "bullish"))})
        rule = _rule({"entity_id": str(_ENTITY), "polarities": ["bearish"]})
        assert await ev.evaluate(rule, ctx) is None


# ── should_fire branch ────────────────────────────────────────────────────────


class TestPredictionShouldFire:
    @pytest.mark.unit
    def test_fires_when_score_clears_floor(self) -> None:
        rule = _rule({"entity_id": str(_ENTITY), "min_impact_score": 0.5})
        now = utc_now()
        assert rule.should_fire(EvalResult(observed_at=now, value=0.6), now) is True

    @pytest.mark.unit
    def test_no_fire_below_floor(self) -> None:
        rule = _rule({"entity_id": str(_ENTITY), "min_impact_score": 0.7})
        now = utc_now()
        assert rule.should_fire(EvalResult(observed_at=now, value=0.6), now) is False

    @pytest.mark.unit
    def test_cooldown_suppresses_refire(self) -> None:
        rule = _rule({"entity_id": str(_ENTITY), "min_impact_score": 0.0})
        now = utc_now()
        # Simulate a recent fire within the 1h default cooldown.
        rule.last_state = {"last_fired_at": (now - timedelta(minutes=5)).isoformat()}
        assert rule.should_fire(EvalResult(observed_at=now, value=0.9), now) is False

    @pytest.mark.unit
    def test_next_state_records_last_value(self) -> None:
        rule = _rule({"entity_id": str(_ENTITY)})
        now = utc_now()
        state = rule.next_state(EvalResult(observed_at=now, value=0.75), now, fired=True)
        assert state["last_value"] == pytest.approx(0.75)
        assert "last_fired_at" in state
