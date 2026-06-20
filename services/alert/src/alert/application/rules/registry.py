"""RuleEvaluator protocol + the single evaluator registry (PLAN-0113 §6.5.4).

The registry is the one place evaluators register themselves against a
``RuleType``. Wave 1 ships it empty (the poller resolves a no-op when a type has
no evaluator yet); Wave 2/3 populate it (price/fundamental/news/kg).

An evaluator is a small object satisfying ``RuleEvaluator``: it declares its
trigger (``poll`` or ``event``), poll cadence, and the event topics it cares
about, and implements ``evaluate`` returning an ``EvalResult`` (or None to skip
without a state change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from alert.domain.entities import AlertRule, EvalResult
    from alert.domain.enums import RuleType


@dataclass
class EvalContext:
    """Ambient dependencies an evaluator may use during a single evaluation.

    Wave 1 keeps this minimal; Wave 2/3 attach the S3/S6/S7 clients here so
    evaluators stay free of construction concerns and remain unit-testable with
    stubbed clients.
    """

    # Populated by the poller / consumer when wiring real clients (Wave 2/3).
    clients: dict[str, object] | None = None


@runtime_checkable
class RuleEvaluator(Protocol):
    """Strategy interface for evaluating one rule type (PRD §6.5.4)."""

    rule_type: RuleType
    trigger: Literal["event", "poll"]
    cadence_seconds: int | None

    def relevant_topics(self) -> frozenset[str]:
        """Event topics this evaluator reacts to (empty for poll types)."""
        ...

    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None:
        """Observe the current world state for ``rule``; None = skip (no state change)."""
        ...


# The single registration point. Populated by ``register_default_evaluators``
# (called once at poller/consumer boot) rather than at import time so that the
# evaluator modules — which import ``EvalContext`` from here — never create an
# import cycle, and so tests can register a subset / stubs explicitly.
EVALUATOR_REGISTRY: dict[RuleType, RuleEvaluator] = {}


def get_evaluator(rule_type: RuleType) -> RuleEvaluator | None:
    """Resolve the evaluator for a rule type, or None if not yet registered."""
    return EVALUATOR_REGISTRY.get(rule_type)


def register_default_evaluators() -> dict[RuleType, RuleEvaluator]:
    """Register the production poll evaluators into ``EVALUATOR_REGISTRY``.

    Idempotent — re-registers the same singletons on each call. Imports are
    local to keep this module import-cycle-free (the evaluators import
    ``EvalContext`` from here). The KG_CONNECTION evaluator is event-driven and
    registered by the intelligence consumer in Wave 3, not here.
    """
    from alert.application.rules.fundamental_cross import FundamentalCrossEvaluator
    from alert.application.rules.news_count import NewsCountEvaluator
    from alert.application.rules.news_momentum import NewsMomentumEvaluator
    from alert.application.rules.price_cross import PriceCrossEvaluator
    from alert.domain.enums import RuleType as _RuleType

    EVALUATOR_REGISTRY[_RuleType.PRICE_CROSS] = PriceCrossEvaluator()
    EVALUATOR_REGISTRY[_RuleType.FUNDAMENTAL_CROSS] = FundamentalCrossEvaluator()
    EVALUATOR_REGISTRY[_RuleType.NEWS_COUNT] = NewsCountEvaluator()
    EVALUATOR_REGISTRY[_RuleType.NEWS_MOMENTUM] = NewsMomentumEvaluator()
    return EVALUATOR_REGISTRY
