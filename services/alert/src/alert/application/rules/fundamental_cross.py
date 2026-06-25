"""FundamentalCrossEvaluator — poll evaluator for FUNDAMENTAL_CROSS (PLAN-0113 T-2-03).

Reads the latest value of a fundamental metric (e.g. ``pe_ratio``,
``target_price``) and emits an ``EvalResult{value}``; the shared edge logic fires
on the no→yes transition vs ``last_state.was_above`` / ``last_value``.

Cadence (21600s = 6h) is how often we *read*; the per-type cooldown (86400s = 24h
default) is the re-arm window after a fire. These are deliberately distinct knobs.
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


class FundamentalCrossEvaluator:
    """Evaluates one FUNDAMENTAL_CROSS rule per cycle via the S3 timeseries read."""

    rule_type: RuleType = RuleType.FUNDAMENTAL_CROSS
    trigger: Literal["event", "poll"] = "poll"
    cadence_seconds: int | None = 21600  # 6h read cadence (NFR-1)

    def relevant_topics(self) -> frozenset[str]:
        return frozenset()

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return ``EvalResult{value}`` for the latest metric value, or None."""
        client = _resolve_s3(ctx)
        if client is None:
            return None
        instrument_id = _instrument_id(rule)
        metric = rule.condition.get("metric_key")
        if instrument_id is None or not isinstance(metric, str) or not metric:
            return None
        value = await client.get_fundamental_metric(instrument_id, metric)
        if value is None:
            return None
        return EvalResult(observed_at=utc_now(), value=value)


def _instrument_id(rule: AlertRule) -> UUID | None:
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
