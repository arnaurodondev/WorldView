"""NewsMomentumEvaluator — poll evaluator for NEWS_MOMENTUM rules (PLAN-0113 T-2-05).

Reads the trending ``(delta_pct, count)`` for the rule's entity over its window
and emits an ``EvalResult{delta_pct, count}``. The shared edge logic fires when
``delta_pct ≥ threshold AND count ≥ min_count`` on the no→yes transition — the
``min_count`` gate suppresses cheap 1→2-article percentage spikes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from alert.application.ports.signal_clients import IS6NewsClient
from alert.domain.entities import EvalResult
from alert.domain.enums import RuleType
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.rules.registry import EvalContext
    from alert.domain.entities import AlertRule


class NewsMomentumEvaluator:
    """Evaluates one NEWS_MOMENTUM rule per cycle via the S6 trending feed."""

    rule_type: RuleType = RuleType.NEWS_MOMENTUM
    trigger: Literal["event", "poll"] = "poll"
    cadence_seconds: int | None = 3600

    def relevant_topics(self) -> frozenset[str]:
        return frozenset()

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return ``EvalResult{delta_pct, count}`` or None when the entity isn't trending."""
        client = _resolve_s6(ctx)
        if client is None:
            return None
        entity_id = _entity_id(rule)
        if entity_id is None:
            return None
        window_hours = int(rule.condition.get("window_hours", 24))  # type: ignore[call-overload]
        momentum = await client.get_trending_momentum(entity_id, window_hours)
        if momentum is None:
            return None
        delta_pct, count = momentum
        return EvalResult(observed_at=utc_now(), delta_pct=delta_pct, count=count)


def _entity_id(rule: AlertRule) -> UUID | None:
    raw = rule.condition.get("entity_id") or rule.entity_id
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_s6(ctx: EvalContext) -> IS6NewsClient | None:
    client = (ctx.clients or {}).get("s6")
    return client if isinstance(client, IS6NewsClient) else None
