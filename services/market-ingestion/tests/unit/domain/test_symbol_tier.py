"""Tests for SymbolTier entity."""

from __future__ import annotations

import pytest
from market_ingestion.domain.entities.symbol_tier import SymbolTier, TierLevel


@pytest.mark.unit()
def test_symbol_tier_default_is_t2() -> None:
    tier = SymbolTier(symbol="AAPL", exchange="US")
    assert tier.tier == TierLevel.T2
    assert tier.tier_source == "default"


@pytest.mark.unit()
def test_symbol_tier_creation_fields() -> None:
    tier = SymbolTier(
        symbol="TSLA",
        exchange="US",
        tier=TierLevel.T0,
        tier_source="portfolio",
    )
    assert tier.symbol == "TSLA"
    assert tier.exchange == "US"
    assert tier.tier == TierLevel.T0
    assert tier.tier_source == "portfolio"
    # ID should be a 26-char ULID
    assert isinstance(tier.id, str)
    assert len(tier.id) == 26
    # Timestamps are set
    assert tier.assigned_at is not None
    assert tier.created_at is not None
    assert tier.last_user_refresh_at is None
