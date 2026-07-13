"""PredictionRuleEvaluator — event-driven evaluator for PREDICTION rules (PLAN-0056 Wave D3).

Like :class:`KgConnectionEvaluator`, this one is ``trigger="event"``: it reacts to
``market.prediction.signal.v1`` events (not the periodic poller,
``cadence_seconds=None``). It reads the rule entity's latest prediction-market
impact score + polarity and emits an ``EvalResult{value=market_impact_score}``;
the shared ``AlertRule.should_fire`` fires when the score clears the rule's
``min_impact_score`` floor (bursts collapsed by the per-type cooldown).

IMPORTANT: prediction alerts already fan out through the watchlist-gated
``AlertFanoutUseCase`` for *every* watcher of the entity, independent of any
rule (exactly like the other SIGNAL-class topics). This evaluator only powers
the optional user-configurable PREDICTION rule (a per-user score/polarity/trigger
toggle). It lives in the single registry so any future event dispatch resolves
the same instance.

Fail-soft: a missing client, unparsable entity, or absent signal returns
``None`` (skip — no state change), mirroring the poll/KG evaluators on a flaky
upstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from alert.application.ports.signal_clients import IPredictionSignalClient
from alert.domain.entities import EvalResult
from alert.domain.enums import RuleType
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.rules.registry import EvalContext
    from alert.domain.entities import AlertRule

# The topic that drives this evaluator (matches the avsc + consumer subscription).
_PREDICTION_SIGNAL_TOPIC = "market.prediction.signal.v1"


class PredictionRuleEvaluator:
    """Evaluates one PREDICTION rule from the entity's latest prediction signal."""

    rule_type: RuleType = RuleType.PREDICTION
    trigger: Literal["event", "poll"] = "event"
    # Event-driven: no poll cadence (the poller skips PREDICTION entirely).
    cadence_seconds: int | None = None

    def relevant_topics(self) -> frozenset[str]:
        return frozenset({_PREDICTION_SIGNAL_TOPIC})

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return ``EvalResult{value}`` (the impact score) or None to skip.

        Applies the rule's optional ``polarities`` filter here: a signal whose
        polarity is not in the allow-list is a *skip* (None), so it never flips
        state or fires. The ``min_impact_score`` floor is enforced downstream by
        ``AlertRule.should_fire`` (shared edge logic).
        """
        client = _resolve_client(ctx)
        if client is None:
            return None
        entity_id = _entity_id(rule)
        if entity_id is None:
            return None
        latest = await client.get_latest_impact(entity_id)
        if latest is None:
            return None
        score, polarity = latest
        allowed = _allowed_polarities(rule)
        if allowed is not None and polarity.lower() not in allowed:
            return None
        return EvalResult(observed_at=utc_now(), value=score)


def _entity_id(rule: AlertRule) -> UUID | None:
    """The entity the rule keys on (PREDICTION uses ``entity_id``)."""
    raw = rule.entity_id or rule.condition.get("entity_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _allowed_polarities(rule: AlertRule) -> set[str] | None:
    """Lower-cased polarity allow-list from the condition, or None for 'all'."""
    raw = rule.condition.get("polarities")
    if not raw or not isinstance(raw, list):
        return None
    return {str(p).lower() for p in raw}


def _resolve_client(ctx: EvalContext) -> IPredictionSignalClient | None:
    client = (ctx.clients or {}).get("prediction")
    return client if isinstance(client, IPredictionSignalClient) else None
