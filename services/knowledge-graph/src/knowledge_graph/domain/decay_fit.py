"""Decay-fit value objects — PLAN-0123 Wave 2 (PRD-0120 §6.5).

Carriers used by the offline empirical decay-rate fitter (``application.
analytics.decay_fitting``). Pure domain objects — no infrastructure imports,
no I/O. See ``docs/specs/0120-empirical-decay-half-life.md`` §6.5 and the
plan's Wave 2 "locked design decision" (SS-1 fix) for the statistical spec
these carry the results of.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

LifetimeDefinition = Literal["corroboration_nhpp", "supersession_mle"]
FitMethod = Literal["nhpp_corroboration", "mle_supersession", "pooled_prior"]


@dataclass(frozen=True)
class Lifetime:
    """A single right-censorable duration observation (PRD §6.5).

    Used by the supersession/contradiction censored-exponential estimator
    (``supersession_estimator.py``). ``event_observed=False`` means the
    relation is still "alive" at the observation cutoff — a right-censored
    exposure, not a terminal event.

    Invariants:
    - ``duration_days >= 0.0``
    """

    duration_days: float
    event_observed: bool

    def __post_init__(self) -> None:
        if self.duration_days < 0.0:
            raise ValueError(f"duration_days must be >= 0.0, got {self.duration_days}")


@dataclass(frozen=True)
class MentionSeries:
    """One relation instance's mention-age series (PRD §6.5, SS-1 fix).

    Used by the non-homogeneous Poisson process (NHPP) corroboration-decay
    estimator (``nhpp_estimator.py``). ``mention_ages_days`` are the ages (in
    days since the relation's ``first_evidence_at``) of every subsequent
    ``relation_evidence_raw`` mention observed within
    ``[0, observation_window_days]`` — the founding mention itself is age 0
    and is NOT included (it defines the origin, not an event).

    Invariants:
    - every age in ``mention_ages_days`` is within ``[0, observation_window_days]``
    - ``observation_window_days >= 0.0``
    """

    canonical_type: str
    relation_id: UUID
    mention_ages_days: tuple[float, ...]
    observation_window_days: float

    def __post_init__(self) -> None:
        if self.observation_window_days < 0.0:
            raise ValueError(
                f"observation_window_days must be >= 0.0, got {self.observation_window_days}",
            )
        for age in self.mention_ages_days:
            if not (0.0 <= age <= self.observation_window_days):
                raise ValueError(
                    f"mention age {age} outside observation window "
                    f"[0, {self.observation_window_days}] for relation {self.relation_id}",
                )


@dataclass(frozen=True)
class DecayFit:
    """One type's decay-rate fit result — the report/write-back carrier (PRD §6.5).

    ``half_life_days`` is intentionally NOT stored — it is derived from
    ``lambda_hat`` via the :pyattr:`half_life_days` property so the two values
    can never drift out of sync.

    ``shrinkage_weight`` and ``alpha_final`` are ``None`` until Wave 3's
    partial-pooling step populates them; a bare Wave-2 fit is a per-definition
    estimate, not yet the pooled per-type final value.
    """

    canonical_type: str
    lifetime_definition: LifetimeDefinition
    lambda_hat: float
    n: int
    exposure_time: float
    censoring_rate: float
    prior_alpha: float
    method: FitMethod
    shrinkage_weight: float | None = None
    alpha_final: float | None = None

    def __post_init__(self) -> None:
        if self.lambda_hat <= 0.0:
            raise ValueError(f"lambda_hat must be > 0.0, got {self.lambda_hat}")
        if self.n < 0:
            raise ValueError(f"n must be >= 0, got {self.n}")
        if not (0.0 <= self.censoring_rate <= 1.0):
            raise ValueError(f"censoring_rate must be in [0, 1], got {self.censoring_rate}")

    @property
    def half_life_days(self) -> float:
        """``ln(2) / lambda_hat`` — derived, never stored redundantly."""
        return math.log(2) / self.lambda_hat
