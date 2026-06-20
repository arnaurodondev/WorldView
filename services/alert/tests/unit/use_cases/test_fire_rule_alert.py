"""Unit tests for FireRuleAlertUseCase (PLAN-0113 T-2-01).

Covers (with mocked session + repos):
  - fire targets the owner only (pending row written for rule.user_id, not a fan-out)
  - dedup_key includes rule_id (two rules / same entity → distinct keys)
  - last_state advances (last_fired_at set) only on commit (rollback → no advance)
  - two rules on the same entity do not collide
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alert.application.use_cases.fire_rule_alert import (
    FireRuleAlertUseCase,
    _transition_signature,
)
from alert.domain.entities import AlertRule, EvalResult
from alert.domain.enums import RuleType
from alert.domain.errors import DuplicateAlertError

from common.time import utc_now  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


def _rule(*, user_id=None, tenant_id=None, instrument_id=None) -> AlertRule:
    iid = instrument_id or uuid4()
    return AlertRule.create(
        rule_type=RuleType.PRICE_CROSS,
        name="px",
        tenant_id=tenant_id or uuid4(),
        user_id=user_id or uuid4(),
        entity_id=iid,
        condition={"instrument_id": str(iid), "operator": "above", "value": 100.0},
    )


def _build(save_raises: Exception | None = None):
    """Return (use_case, mocks-dict) with a mocked session + repos."""
    alert_repo = AsyncMock()
    alert_repo.save = AsyncMock(side_effect=save_raises) if save_raises else AsyncMock()
    pending_repo = AsyncMock()
    outbox_repo = AsyncMock()
    rule_repo = AsyncMock()

    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock(return_value=session)

    ws = AsyncMock()
    ws.send_to_user = AsyncMock()

    def _factory(_s):  # type: ignore[no-untyped-def]
        return alert_repo, pending_repo, outbox_repo, rule_repo

    uc = FireRuleAlertUseCase(
        session_factory=sf,
        notification_publisher=ws,
        repo_factory=_factory,  # type: ignore[arg-type]
    )
    return uc, {
        "alert_repo": alert_repo,
        "pending_repo": pending_repo,
        "outbox_repo": outbox_repo,
        "rule_repo": rule_repo,
        "session": session,
        "ws": ws,
    }


async def test_fire_targets_owner_not_watchlist() -> None:
    user_id = uuid4()
    rule = _rule(user_id=user_id)
    uc, m = _build()
    result = await uc.execute(rule, EvalResult(observed_at=utc_now(), value=150.0))

    assert result.fired is True
    # exactly one pending row, for the rule owner
    m["pending_repo"].save.assert_awaited_once()
    pending = m["pending_repo"].save.call_args.args[0]
    assert pending.user_id == user_id
    # outbox used (R8) + websocket pushed to the owner
    m["outbox_repo"].append.assert_awaited_once()
    m["ws"].send_to_user.assert_awaited_once()
    assert m["ws"].send_to_user.call_args.args[0] == user_id


async def test_outbox_and_commit_happen() -> None:
    rule = _rule()
    uc, m = _build()
    await uc.execute(rule, EvalResult(observed_at=utc_now(), value=150.0))
    m["alert_repo"].save.assert_awaited_once()
    m["session"].commit.assert_awaited_once()


async def test_dedup_key_includes_rule_id() -> None:
    """Two distinct rules / same entity / same observation → distinct dedup keys."""
    iid = uuid4()
    now = utc_now()
    result = EvalResult(observed_at=now, value=150.0)
    rule_a = _rule(instrument_id=iid)
    rule_b = _rule(instrument_id=iid)

    sig_a = _transition_signature(rule_a, result, now)
    sig_b = _transition_signature(rule_b, result, now)
    key_a = hashlib.sha256(f"{rule_a.rule_id}:{sig_a}".encode()).hexdigest()
    key_b = hashlib.sha256(f"{rule_b.rule_id}:{sig_b}".encode()).hexdigest()
    assert key_a != key_b


async def test_two_rules_same_entity_no_collision() -> None:
    iid = uuid4()
    uc_a, m_a = _build()
    uc_b, m_b = _build()
    rule_a = _rule(instrument_id=iid)
    rule_b = _rule(instrument_id=iid)
    await uc_a.execute(rule_a, EvalResult(observed_at=utc_now(), value=150.0))
    await uc_b.execute(rule_b, EvalResult(observed_at=utc_now(), value=150.0))
    alert_a = m_a["alert_repo"].save.call_args.args[0]
    alert_b = m_b["alert_repo"].save.call_args.args[0]
    assert alert_a.dedup_key != alert_b.dedup_key


async def test_last_state_persists_only_on_commit() -> None:
    """A duplicate (rolled-back) fire must NOT advance last_fired_at."""
    rule = _rule()
    assert rule.last_state is None
    uc, m = _build(save_raises=DuplicateAlertError("dup"))
    result = await uc.execute(rule, EvalResult(observed_at=utc_now(), value=150.0))

    assert result.suppressed is True
    assert result.suppression_reason == "dedup"
    m["session"].rollback.assert_awaited_once()
    m["session"].commit.assert_not_awaited()
    # rule.update never called → last_state unchanged (no last_fired_at)
    m["rule_repo"].update.assert_not_awaited()
    assert rule.last_state is None


async def test_fired_advances_last_fired_at() -> None:
    rule = _rule()
    uc, m = _build()
    await uc.execute(rule, EvalResult(observed_at=utc_now(), value=150.0))
    # last_state advanced in-place with last_fired_at + the rule row updated
    m["rule_repo"].update.assert_awaited_once()
    assert rule.last_state is not None
    assert "last_fired_at" in rule.last_state


async def test_payload_carries_rule_context() -> None:
    rule = _rule()
    uc, m = _build()
    await uc.execute(rule, EvalResult(observed_at=utc_now(), value=150.0))
    alert = m["alert_repo"].save.call_args.args[0]
    assert alert.payload["rule_id"] == str(rule.rule_id)
    assert alert.payload["rule_type"] == str(rule.rule_type)
    assert alert.payload["observed"] == 150.0
    assert alert.payload["condition_snapshot"] == rule.condition
    assert str(alert.alert_type) == "user_rule"
