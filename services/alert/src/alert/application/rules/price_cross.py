"""PriceCrossEvaluator — poll evaluator for PRICE_CROSS rules (PLAN-0113 T-2-02).

Reads the current last price for the rule's instrument and emits an ``EvalResult``
carrying ``value``. The shared ``AlertRule.should_fire`` turns that into an
edge-triggered decision against ``last_state.was_above`` + the rule's operator —
so the rule fires only on the no→yes transition, never every tick while held.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from alert.application.ports.signal_clients import IS3PriceClient
from alert.domain.entities import EvalResult
from alert.domain.enums import RuleType
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.rules.registry import EvalContext
    from alert.domain.entities import AlertRule


class PriceCrossEvaluator:
    """Evaluates one PRICE_CROSS rule per cycle via the S3 price-batch read."""

    rule_type: RuleType = RuleType.PRICE_CROSS
    trigger: Literal["event", "poll"] = "poll"
    cadence_seconds: int | None = 60

    def relevant_topics(self) -> frozenset[str]:
        return frozenset()

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return an ``EvalResult{value}`` or None when no price is available.

        None (a missing price) is a *skip*: ``should_fire`` returns False and the
        poller leaves ``last_state`` untouched, so a transient S3 gap never flips
        the ``was_above`` edge memory.
        """
        client = _resolve_s3(ctx)
        if client is None:
            return None
        instrument_id = _instrument_id(rule)
        if instrument_id is None:
            return None
        prices = await client.get_price_batch([instrument_id])
        price = prices.get(instrument_id)
        if price is None:
            return None
        return EvalResult(observed_at=utc_now(), value=price)


def _instrument_id(rule: AlertRule) -> UUID | None:
    """The instrument the rule keys on (PRICE_CROSS uses ``instrument_id``)."""
    raw = rule.condition.get("instrument_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _resolve_s3(ctx: EvalContext) -> IS3PriceClient | None:
    client = (ctx.clients or {}).get("s3")
    return client if isinstance(client, IS3PriceClient) else None
