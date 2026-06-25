"""Unit tests for KgConnectionEventHandler (PLAN-0113 T-3-02 — consumer KG branch).

The handler is the consumer-side driver: on each ``graph.state.changed.v1`` event it
loads enabled KG_CONNECTION rules, cheaply pre-filters to the ones the event touches,
confirms the connection via the evaluator (S7, fail-closed), and fires owner-targeted
alerts via the shared ``FireRuleAlertUseCase`` (latching once).

All collaborators are stubbed so these are pure unit tests (no DB/HTTP/Kafka).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from alert.application.rules.registry import EvalContext
from alert.application.use_cases.fire_rule_alert import FireResult
from alert.application.use_cases.kg_connection_handler import KgConnectionEventHandler
from alert.domain.entities import AlertRule, EvalResult
from alert.domain.enums import RuleType

from common.time import utc_now

pytestmark = pytest.mark.unit


def _kg_rule(node_a: UUID, node_b: UUID, *, last_state: dict[str, object] | None = None) -> AlertRule:
    rule = AlertRule.create(
        rule_type=RuleType.KG_CONNECTION,
        name="A↔B",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition={"source_entity_id": str(node_a), "target_entity_id": str(node_b), "max_hops": 3},
        node_a_entity_id=node_a,
        node_b_entity_id=node_b,
    )
    rule.last_state = last_state
    return rule


def _make_handler(
    *,
    rules: list[AlertRule],
    connected: bool = True,
    fire_result: FireResult | None = None,
) -> tuple[KgConnectionEventHandler, AsyncMock, AsyncMock]:
    # Evaluator stub: returns EvalResult{connected} (skip when result is None handled by caller).
    evaluator = MagicMock()
    evaluator.evaluate = AsyncMock(return_value=EvalResult(observed_at=utc_now(), connected=connected))

    fire = MagicMock()
    fire.execute = AsyncMock(return_value=fire_result or FireResult(fired=True, alert_id=uuid4()))

    load = AsyncMock(return_value=rules)

    # write_session_factory: async-context-manager session stub for no-fire persistence.
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _sf() -> Any:
        yield session

    repo = MagicMock()
    repo.update = AsyncMock(return_value=True)
    repo_factory = MagicMock(return_value=repo)

    handler = KgConnectionEventHandler(
        evaluator=evaluator,
        eval_ctx=EvalContext(clients={"s7": object()}),
        fire_use_case=fire,
        load_enabled_rules=load,
        write_session_factory=_sf,  # type: ignore[arg-type]
        rule_repo_factory=repo_factory,
    )
    return handler, evaluator, fire


async def test_both_nodes_touched_confirm_and_fire() -> None:
    """Event touching both nodes → confirm → owner-targeted fire."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, fire = _make_handler(rules=[rule], connected=True)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 1
    evaluator.evaluate.assert_awaited_once()
    fire.execute.assert_awaited_once()


async def test_single_node_touched_still_evaluates() -> None:
    """A single new edge touching ONE endpoint can complete a multi-hop path → evaluate."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, _ = _make_handler(rules=[rule], connected=True)
    # Only node_a appears (plus primary); node_b is not in the event.
    event = {"event_id": str(uuid4()), "primary_entity_id": str(a), "affected_entity_ids": [], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 1
    evaluator.evaluate.assert_awaited_once()


async def test_prefilter_skips_unrelated_event() -> None:
    """An event touching neither node never confirms (no S7 call, no fire)."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, fire = _make_handler(rules=[rule], connected=True)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(uuid4())], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 0
    evaluator.evaluate.assert_not_awaited()
    fire.execute.assert_not_awaited()


async def test_backfill_suppressed() -> None:
    """A backfill replay must not retro-fire (AD-10) — no rules even loaded."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, fire = _make_handler(rules=[rule], connected=True)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": True}

    fired = await handler.handle(event)

    assert fired == 0
    evaluator.evaluate.assert_not_awaited()
    fire.execute.assert_not_awaited()


async def test_latch_fires_once() -> None:
    """Once ``connected`` is latched in last_state, a re-delivered event does not re-fire."""
    a, b = uuid4(), uuid4()
    # Already latched: last_state.connected == True → should_fire returns False.
    rule = _kg_rule(a, b, last_state={"connected": True})
    handler, _evaluator, fire = _make_handler(rules=[rule], connected=True)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 0
    fire.execute.assert_not_awaited()


async def test_not_connected_persists_no_fire_state() -> None:
    """connected=false → no fire, but the no-fire state is persisted (edge memory advances)."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, _evaluator, fire = _make_handler(rules=[rule], connected=False)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 0
    fire.execute.assert_not_awaited()
    # last_state advanced with connected=False (no latch).
    assert rule.last_state is not None
    assert rule.last_state.get("connected") is False


async def test_evaluator_skip_leaves_state_untouched() -> None:
    """evaluate() returning None (transient skip) does not fire nor mutate last_state."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, fire = _make_handler(rules=[rule], connected=True)
    evaluator.evaluate = AsyncMock(return_value=None)
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    fired = await handler.handle(event)

    assert fired == 0
    fire.execute.assert_not_awaited()
    assert rule.last_state is None


async def test_per_rule_failure_is_fail_soft() -> None:
    """A rule that raises is logged + skipped; the handler never propagates (protects fan-out)."""
    a, b = uuid4(), uuid4()
    rule = _kg_rule(a, b)
    handler, evaluator, fire = _make_handler(rules=[rule], connected=True)
    evaluator.evaluate = AsyncMock(side_effect=RuntimeError("S7 exploded"))
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    fired = await handler.handle(event)  # must not raise

    assert fired == 0
    fire.execute.assert_not_awaited()


async def test_load_rules_failure_returns_zero() -> None:
    """A failure loading enabled rules degrades to zero fires, never raises."""
    a, b = uuid4(), uuid4()
    handler, _evaluator, _fire = _make_handler(rules=[_kg_rule(a, b)], connected=True)
    handler._load_enabled_rules = AsyncMock(side_effect=RuntimeError("db down"))  # type: ignore[method-assign]
    event = {"event_id": str(uuid4()), "affected_entity_ids": [str(a), str(b)], "is_backfill": False}

    assert await handler.handle(event) == 0
