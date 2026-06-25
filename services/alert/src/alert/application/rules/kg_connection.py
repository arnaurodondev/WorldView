"""KgConnectionEvaluator — event-driven evaluator for KG_CONNECTION rules (PLAN-0113 T-3-02).

Unlike the four poll evaluators, this one is ``trigger="event"``: it is driven by
``graph.state.changed.v1`` events arriving at the intelligence consumer, NOT by
the periodic poller (``cadence_seconds=None``). The consumer pre-filters which
rules to evaluate (those whose node_a/node_b appear in the event's affected
entities) and then calls ``evaluate`` here.

``evaluate`` asks S7 to confirm whether the rule's two entities are now connected
within ``max_hops`` (optionally via a pinned ``relation_type``). It emits an
``EvalResult{connected}``; the shared ``AlertRule.should_fire`` latches on the
first ``connected=true`` (KG cooldown default is 0 → fires exactly once, then the
``connected`` flag in ``last_state`` suppresses re-fires).

Fail-closed: the S7 client returns ``False`` on any error, so an unproven
connection never fires. A missing client / missing nodes returns ``None`` (skip —
no state change), exactly like the poll evaluators on a flaky upstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from alert.application.ports.graph_clients import IS7GraphClient
from alert.domain.entities import EvalResult
from alert.domain.enums import RuleType
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.rules.registry import EvalContext
    from alert.domain.entities import AlertRule

# The topic that drives this evaluator (matches the avsc + consumer subscription).
_GRAPH_STATE_TOPIC = "graph.state.changed.v1"


class KgConnectionEvaluator:
    """Evaluates one KG_CONNECTION rule by confirming the A↔B link via S7."""

    rule_type: RuleType = RuleType.KG_CONNECTION
    trigger: Literal["event", "poll"] = "event"
    # Event-driven: no poll cadence (the poller skips KG_CONNECTION entirely).
    cadence_seconds: int | None = None

    def relevant_topics(self) -> frozenset[str]:
        return frozenset({_GRAPH_STATE_TOPIC})

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return ``EvalResult{connected}`` from an S7 confirm, or None to skip.

        None (missing client or unparsable nodes) is a *skip*: ``should_fire``
        returns False and ``last_state`` is left untouched, so a transient wiring
        gap never latches the ``connected`` memory prematurely.
        """
        client = _resolve_s7(ctx)
        if client is None:
            return None
        node_a, node_b = _nodes(rule)
        if node_a is None or node_b is None:
            return None
        max_hops = _max_hops(rule)
        relation_type = _relation_type(rule)
        connected = await client.confirm_connection(node_a, node_b, max_hops, relation_type)
        return EvalResult(observed_at=utc_now(), connected=connected)


def _nodes(rule: AlertRule) -> tuple[UUID | None, UUID | None]:
    """The two KG nodes — prefer the rule columns, fall back to the condition."""
    a = rule.node_a_entity_id or _uuid(rule.condition.get("source_entity_id"))
    b = rule.node_b_entity_id or _uuid(rule.condition.get("target_entity_id"))
    return a, b


def _max_hops(rule: AlertRule) -> int:
    raw = rule.condition.get("max_hops", 3)
    try:
        return int(str(raw))
    except (ValueError, TypeError):
        return 3


def _relation_type(rule: AlertRule) -> str | None:
    raw = rule.condition.get("relation_type")
    return str(raw) if raw else None


def _uuid(raw: object) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_s7(ctx: EvalContext) -> IS7GraphClient | None:
    client = (ctx.clients or {}).get("s7")
    return client if isinstance(client, IS7GraphClient) else None
