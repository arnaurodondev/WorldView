"""Unit tests for decay-fit value objects — PLAN-0123 Wave 2 (T-A-2-01)."""

from __future__ import annotations

import dataclasses
import math
from uuid import uuid4

import pytest
from knowledge_graph.domain.decay_fit import DecayFit, Lifetime, MentionSeries

pytestmark = pytest.mark.unit


class TestLifetime:
    def test_construction(self) -> None:
        lt = Lifetime(duration_days=42.0, event_observed=True)
        assert lt.duration_days == pytest.approx(42.0)
        assert lt.event_observed is True

    def test_frozen_immutable(self) -> None:
        lt = Lifetime(duration_days=10.0, event_observed=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            lt.duration_days = 20.0  # type: ignore[misc]

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValueError, match="duration_days must be >= 0.0"):
            Lifetime(duration_days=-1.0, event_observed=True)

    def test_zero_duration_allowed(self) -> None:
        lt = Lifetime(duration_days=0.0, event_observed=False)
        assert lt.duration_days == 0.0


class TestMentionSeries:
    def test_construction(self) -> None:
        rel_id = uuid4()
        series = MentionSeries(
            canonical_type="analyst_rating",
            relation_id=rel_id,
            mention_ages_days=(3.0, 7.5, 20.0),
            observation_window_days=30.0,
        )
        assert series.relation_id == rel_id
        assert series.mention_ages_days == (3.0, 7.5, 20.0)

    def test_frozen_immutable(self) -> None:
        series = MentionSeries(
            canonical_type="analyst_rating",
            relation_id=uuid4(),
            mention_ages_days=(),
            observation_window_days=10.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            series.observation_window_days = 20.0  # type: ignore[misc]

    def test_empty_mention_ages_allowed(self) -> None:
        """A relation instance with only its founding evidence (no re-mentions)."""
        series = MentionSeries(
            canonical_type="price_target",
            relation_id=uuid4(),
            mention_ages_days=(),
            observation_window_days=15.0,
        )
        assert series.mention_ages_days == ()

    def test_negative_observation_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="observation_window_days must be >= 0.0"):
            MentionSeries(
                canonical_type="analyst_rating",
                relation_id=uuid4(),
                mention_ages_days=(),
                observation_window_days=-5.0,
            )

    def test_mention_age_beyond_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside observation window"):
            MentionSeries(
                canonical_type="analyst_rating",
                relation_id=uuid4(),
                mention_ages_days=(5.0, 40.0),
                observation_window_days=30.0,
            )

    def test_mention_age_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside observation window"):
            MentionSeries(
                canonical_type="analyst_rating",
                relation_id=uuid4(),
                mention_ages_days=(-1.0,),
                observation_window_days=30.0,
            )


class TestDecayFit:
    def _make(self, **overrides: object) -> DecayFit:
        defaults: dict[str, object] = {
            "canonical_type": "analyst_rating",
            "lifetime_definition": "corroboration_nhpp",
            "lambda_hat": 0.05,
            "n": 42,
            "exposure_time": 1000.0,
            "censoring_rate": 0.6,
            "prior_alpha": 0.049510,
            "method": "nhpp_corroboration",
        }
        defaults.update(overrides)
        return DecayFit(**defaults)  # type: ignore[arg-type]

    def test_half_life_derived_from_lambda(self) -> None:
        fit = self._make(lambda_hat=0.0231)
        assert fit.half_life_days == pytest.approx(math.log(2) / 0.0231)

    def test_half_life_not_stored_redundantly(self) -> None:
        """half_life_days is a computed property, not a dataclass field."""
        field_names = {f.name for f in dataclasses.fields(DecayFit)}
        assert "half_life_days" not in field_names

    def test_frozen_immutable(self) -> None:
        fit = self._make()
        with pytest.raises(dataclasses.FrozenInstanceError):
            fit.lambda_hat = 0.1  # type: ignore[misc]

    def test_non_positive_lambda_rejected(self) -> None:
        with pytest.raises(ValueError, match="lambda_hat must be > 0.0"):
            self._make(lambda_hat=0.0)

    def test_negative_n_rejected(self) -> None:
        with pytest.raises(ValueError, match="n must be >= 0"):
            self._make(n=-1)

    def test_censoring_rate_out_of_bounds_rejected(self) -> None:
        with pytest.raises(ValueError, match="censoring_rate must be in"):
            self._make(censoring_rate=1.5)

    def test_defaults_shrinkage_and_final_none(self) -> None:
        """A bare Wave-2 fit has no pooled/final alpha yet (Wave 3 populates it)."""
        fit = self._make()
        assert fit.shrinkage_weight is None
        assert fit.alpha_final is None
