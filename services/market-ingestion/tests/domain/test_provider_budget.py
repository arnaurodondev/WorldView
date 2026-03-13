"""Tests for ProviderBudget entity — token-bucket rate limiting."""

from __future__ import annotations

import pytest
from market_ingestion.domain.entities.provider_budget import ProviderBudget
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderRateLimited


@pytest.mark.unit
def test_budget_default_values() -> None:
    budget = ProviderBudget()
    assert budget.tokens == budget.burst_capacity
    assert budget.id is not None


@pytest.mark.unit
def test_try_consume_succeeds_when_tokens_available() -> None:
    budget = ProviderBudget(tokens=10.0)
    result = budget.try_consume(1.0)
    assert result is True
    assert budget.tokens == 9.0


@pytest.mark.unit
def test_try_consume_fails_when_insufficient() -> None:
    budget = ProviderBudget(tokens=0.5)
    result = budget.try_consume(1.0)
    assert result is False
    assert budget.tokens == 0.5  # unchanged


@pytest.mark.unit
def test_consume_raises_when_exhausted() -> None:
    budget = ProviderBudget(tokens=0.0)
    with pytest.raises(ProviderRateLimited):
        budget.consume(1.0)


@pytest.mark.unit
def test_consume_succeeds_and_decrements() -> None:
    budget = ProviderBudget(tokens=5.0)
    budget.consume(2.0)
    assert budget.tokens == 3.0


@pytest.mark.unit
def test_refill_adds_tokens_based_on_elapsed() -> None:
    budget = ProviderBudget(tokens=0.0, refill_rate=10.0, burst_capacity=1000.0)
    budget.refill(elapsed_seconds=5.0)
    assert budget.tokens == 50.0


@pytest.mark.unit
def test_refill_caps_at_burst_capacity() -> None:
    budget = ProviderBudget(tokens=990.0, refill_rate=10.0, burst_capacity=1000.0)
    budget.refill(elapsed_seconds=100.0)
    assert budget.tokens == 1000.0


@pytest.mark.unit
def test_time_until_available_zero_when_tokens_ready() -> None:
    budget = ProviderBudget(tokens=5.0)
    assert budget.time_until_available(1.0) == 0.0


@pytest.mark.unit
def test_time_until_available_calculated_correctly() -> None:
    budget = ProviderBudget(tokens=0.0, refill_rate=5.0)
    # Need 3 tokens, have 0 → deficit = 3, rate = 5 → wait = 3/5 = 0.6s
    wait = budget.time_until_available(3.0)
    assert abs(wait - 0.6) < 1e-6


@pytest.mark.unit
def test_burst_limit_not_exceeded() -> None:
    budget = ProviderBudget(burst_capacity=10.0, tokens=0.0, refill_rate=1.0)
    budget.refill(elapsed_seconds=1000.0)
    assert budget.tokens <= budget.burst_capacity


@pytest.mark.unit
def test_provider_default_eodhd() -> None:
    budget = ProviderBudget.for_eodhd()
    assert budget.provider == Provider.EODHD
    assert budget.burst_capacity == 1000.0
    assert budget.refill_rate == 10.0
    assert budget.tokens == 1000.0


@pytest.mark.unit
def test_provider_default_alpha_vantage() -> None:
    budget = ProviderBudget.for_alpha_vantage()
    assert budget.provider == Provider.ALPHA_VANTAGE
    assert budget.burst_capacity == 5.0
    assert abs(budget.refill_rate - 0.083) < 1e-6
    assert budget.tokens == 5.0


@pytest.mark.unit
def test_try_consume_multiple_tokens() -> None:
    budget = ProviderBudget(tokens=10.0)
    assert budget.try_consume(10.0) is True
    assert budget.tokens == 0.0
    assert budget.try_consume(1.0) is False
