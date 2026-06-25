"""NewsCountEvaluator — poll evaluator for NEWS_COUNT rules (PLAN-0113 T-2-04).

Reads the article count for the rule's entity over its configured window and
emits an ``EvalResult{count}``. The shared edge logic fires when the count first
reaches the threshold and re-arms when it drops below — so a sustained surge
fires once, not every tick.

Window sources (PRD §6.5.4):
  - ``7d``               → S6 ``/internal/v1/instruments/{id}/news-rollup-7d``
  - ``24h`` / ``72h`` / ``168h`` analogues → S6 trending counts (24/72/168 h)

The condition window vocabulary is ``{1h, 6h, 24h, 7d}`` (domain validator).
``7d`` maps to the rollup; ``24h`` maps to the 24h trending count; ``1h`` and
``6h`` have no dedicated v1 source so they fall back to the 24h trending count
(the smallest available window — documented degradation, never a silent zero).
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

# Map the condition's ``window`` to a trending ``window_hours`` for the short
# windows. ``7d`` is handled separately by the rollup endpoint.
_WINDOW_TO_HOURS: dict[str, int] = {"1h": 24, "6h": 24, "24h": 24}


class NewsCountEvaluator:
    """Evaluates one NEWS_COUNT rule per cycle via the S6 news client."""

    rule_type: RuleType = RuleType.NEWS_COUNT
    trigger: Literal["event", "poll"] = "poll"
    cadence_seconds: int | None = 3600

    def relevant_topics(self) -> frozenset[str]:
        return frozenset()

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Return ``EvalResult{count}`` for the entity's window, or None on failure."""
        client = _resolve_s6(ctx)
        if client is None:
            return None
        entity_id = _entity_id(rule)
        if entity_id is None:
            return None
        window = str(rule.condition.get("window", "7d"))

        count: int | None
        if window == "7d":
            count = await client.get_news_count_7d(entity_id)
        else:
            window_hours = _WINDOW_TO_HOURS.get(window, 24)
            count = await client.get_trending_count(entity_id, window_hours)

        if count is None:
            return None
        return EvalResult(observed_at=utc_now(), count=count)


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
