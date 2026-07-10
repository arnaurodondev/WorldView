"""Discriminated-union ``condition`` value objects for alert rules (PLAN-0113 §6.5.3).

Each of the 5 ``RuleType`` values pairs with exactly one Pydantic condition
model.  The models live in the domain layer (no infrastructure imports) and are
validated at the API boundary — replacing the legacy free-text ``condition`` +
unvalidated ``threshold`` of the old ``POST /api/v1/alerts`` path.

Design notes
------------
- ``extra="forbid"`` on every model rejects unknown fields (typo'd payloads
  fail loudly with 422 rather than silently dropping data).
- The discriminator is ``rule_type`` (mirrors the DB column), so a single
  ``parse_condition(rule_type, payload)`` resolves the right model.  We do NOT
  embed ``rule_type`` *inside* each condition (it lives on the rule row), so we
  dispatch manually rather than via a Pydantic ``Field(discriminator=...)``.
- ``window_hours`` (momentum) is restricted to the trending endpoint's
  supported set ``{24, 72, 168}``; ``window`` (news-count) to
  ``{1h, 6h, 24h, 7d}`` (v1 source coverage, PRD §6.5.3).
- ``metric_key`` non-emptiness is checked here; the *semantic* check (the key
  exists in the S3 fundamentals vocabulary) happens in the API layer where the
  S3 catalogue is reachable.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from alert.domain.enums import RuleType

# Allow-lists kept as module constants so the API + tests can import the same
# source of truth (avoids drift between validator and error messages).
NEWS_COUNT_WINDOWS: frozenset[str] = frozenset({"1h", "6h", "24h", "7d"})
NEWS_MOMENTUM_WINDOW_HOURS: frozenset[int] = frozenset({24, 72, 168})

# Comparison operators shared by price + fundamental crosses.
CrossOperator = Literal["above", "below"]


class _ConditionBase(BaseModel):
    """Common config for all condition models: reject unknown fields (BP — silent drop)."""

    model_config = ConfigDict(extra="forbid")


class PriceCrossCondition(_ConditionBase):
    """``PRICE_CROSS`` — last price crosses ``value`` (above|below)."""

    instrument_id: UUID
    operator: CrossOperator
    # ``gt=0``: a non-positive price level is never a meaningful trigger.
    value: float = Field(gt=0)


class NewsCountCondition(_ConditionBase):
    """``NEWS_COUNT`` — article count over ``window`` reaches ``threshold``."""

    entity_id: UUID
    window: Literal["1h", "6h", "24h", "7d"]
    # ``ge=1``: at least one article must be required for the rule to mean anything.
    threshold: int = Field(ge=1)
    keyword: str | None = None


class NewsMomentumCondition(_ConditionBase):
    """``NEWS_MOMENTUM`` — momentum ``delta_pct`` over ``window_hours``."""

    entity_id: UUID
    # Restricted to the trending endpoint's supported windows (PRD §6.5.3).
    window_hours: Literal[24, 72, 168]
    delta_pct: float
    # ``ge=1`` default 2: suppresses 1→2 article noise spikes (PRD §6.5.4).
    min_count: int = Field(default=2, ge=1)


class KgConnectionCondition(_ConditionBase):
    """``KG_CONNECTION`` — an edge/path appears between two distinct entities."""

    source_entity_id: UUID
    target_entity_id: UUID
    # AGE path search is bounded to 1..3 hops (S7 ``/paths/between`` limit).
    max_hops: int = Field(default=3, ge=1, le=3)
    relation_type: str | None = None


class FundamentalCrossCondition(_ConditionBase):
    """``FUNDAMENTAL_CROSS`` — a fundamental metric crosses ``value`` (above|below)."""

    instrument_id: UUID
    # Non-empty here; semantic validation against the S3 vocabulary is in the API layer.
    metric_key: str = Field(min_length=1)
    operator: CrossOperator
    value: float


class PredictionCondition(_ConditionBase):
    """``PREDICTION`` — prediction-market signals about ``entity_id`` (PLAN-0056 Wave D3).

    Keyed on ``entity_id`` (the ``subject_entity_id`` carried in
    ``market.prediction.signal.v1``). Optional filters let a user narrow which
    prediction signals raise an alert:

    - ``min_impact_score`` — floor on the event's ``market_impact_score`` (which
      S7 D2 already boosts for adverse/bearish moves). Default 0.0 = any.
    - ``polarities`` — restrict to these directions (e.g. only ``bearish`` = a
      bad-for-the-entity outcome being priced up). ``None`` = all directions.
    - ``triggers`` — restrict to these trigger kinds. ``None`` = all triggers.

    NOTE: prediction signals fan out via watchlist membership regardless of any
    rule; this condition only powers the user-configurable toggle/filter path.
    """

    entity_id: UUID
    # ``ge=0, le=1``: the score is a [0,1] gate; anything else is meaningless.
    min_impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    polarities: list[Literal["bullish", "bearish", "neutral"]] | None = None
    triggers: list[Literal["new_market", "material_move", "resolution"]] | None = None


# Public union type — used in type hints / request schemas.
Condition = Annotated[
    PriceCrossCondition
    | NewsCountCondition
    | NewsMomentumCondition
    | KgConnectionCondition
    | FundamentalCrossCondition
    | PredictionCondition,
    Field(),
]


# Single registration point mapping a rule type to its condition model.
_CONDITION_MODELS: dict[RuleType, type[_ConditionBase]] = {
    RuleType.PRICE_CROSS: PriceCrossCondition,
    RuleType.NEWS_COUNT: NewsCountCondition,
    RuleType.NEWS_MOMENTUM: NewsMomentumCondition,
    RuleType.KG_CONNECTION: KgConnectionCondition,
    RuleType.FUNDAMENTAL_CROSS: FundamentalCrossCondition,
    RuleType.PREDICTION: PredictionCondition,
}


def parse_condition(rule_type: RuleType, payload: dict[str, object]) -> _ConditionBase:
    """Validate ``payload`` against the condition model for ``rule_type``.

    Raises ``pydantic.ValidationError`` on shape/field/constraint violations
    (the API layer maps this to a 400/422).  ``KeyError`` is impossible because
    ``rule_type`` is a closed enum and every member is registered.
    """
    model = _CONDITION_MODELS[rule_type]
    return model.model_validate(payload)


__all__ = [
    "NEWS_COUNT_WINDOWS",
    "NEWS_MOMENTUM_WINDOW_HOURS",
    "Condition",
    "FundamentalCrossCondition",
    "KgConnectionCondition",
    "NewsCountCondition",
    "NewsMomentumCondition",
    "PredictionCondition",
    "PriceCrossCondition",
    "parse_condition",
]
