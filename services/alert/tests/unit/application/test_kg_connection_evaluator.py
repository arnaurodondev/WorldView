"""Unit tests for KgConnectionEvaluator (PLAN-0113 T-3-02 — event-driven KG rule).

The evaluator translates one KG_CONNECTION rule into a single S7 ``confirm_connection``
probe and returns an ``EvalResult{connected}`` (or ``None`` to skip without a state
change). The S7 client is stubbed via the ``IS7GraphClient`` ABC so these tests are
pure unit tests with no HTTP.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from alert.application.ports.graph_clients import IS7GraphClient
from alert.application.rules.kg_connection import KgConnectionEvaluator
from alert.application.rules.registry import EvalContext
from alert.domain.entities import AlertRule
from alert.domain.enums import RuleType

pytestmark = pytest.mark.unit


class _StubS7(IS7GraphClient):
    """Records the confirm_connection args and returns a canned bool."""

    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID, int, str | None]] = []

    async def confirm_connection(
        self,
        source_entity_id: UUID,
        target_entity_id: UUID,
        max_hops: int,
        relation_type: str | None = None,
    ) -> bool:
        self.calls.append((source_entity_id, target_entity_id, max_hops, relation_type))
        return self.result


def _kg_rule(*, max_hops: int = 3, relation_type: str | None = None) -> AlertRule:
    a, b = uuid4(), uuid4()
    cond: dict[str, object] = {"source_entity_id": str(a), "target_entity_id": str(b), "max_hops": max_hops}
    if relation_type is not None:
        cond["relation_type"] = relation_type
    return AlertRule.create(
        rule_type=RuleType.KG_CONNECTION,
        name="A↔B",
        tenant_id=uuid4(),
        user_id=uuid4(),
        condition=cond,
        node_a_entity_id=a,
        node_b_entity_id=b,
    )


async def test_evaluate_connected_true() -> None:
    rule = _kg_rule()
    stub = _StubS7(result=True)
    ctx = EvalContext(clients={"s7": stub})
    result = await KgConnectionEvaluator().evaluate(rule, ctx)
    assert result is not None
    assert result.connected is True
    # The rule's two nodes + max_hops are passed straight through to S7.
    assert stub.calls[0][0] == rule.node_a_entity_id
    assert stub.calls[0][1] == rule.node_b_entity_id
    assert stub.calls[0][2] == 3


async def test_evaluate_connected_false() -> None:
    rule = _kg_rule()
    ctx = EvalContext(clients={"s7": _StubS7(result=False)})
    result = await KgConnectionEvaluator().evaluate(rule, ctx)
    assert result is not None
    assert result.connected is False


async def test_evaluate_passes_relation_type_and_hops() -> None:
    rule = _kg_rule(max_hops=2, relation_type="SUPPLIES")
    stub = _StubS7(result=True)
    await KgConnectionEvaluator().evaluate(rule, EvalContext(clients={"s7": stub}))
    assert stub.calls[0][2] == 2
    assert stub.calls[0][3] == "SUPPLIES"


async def test_evaluate_missing_client_skips() -> None:
    """No S7 client wired → skip (None), never a spurious connected=false latch."""
    rule = _kg_rule()
    assert await KgConnectionEvaluator().evaluate(rule, EvalContext(clients={})) is None
    assert await KgConnectionEvaluator().evaluate(rule, EvalContext(clients=None)) is None


async def test_evaluator_metadata_is_event_driven() -> None:
    ev = KgConnectionEvaluator()
    assert ev.rule_type is RuleType.KG_CONNECTION
    assert ev.trigger == "event"
    assert ev.cadence_seconds is None
    assert ev.relevant_topics() == frozenset({"graph.state.changed.v1"})
