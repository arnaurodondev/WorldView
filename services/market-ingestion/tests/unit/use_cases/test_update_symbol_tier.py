"""Tests for UpdateSymbolTierUseCase."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.update_symbol_tier import UpdateSymbolTierUseCase
from market_ingestion.domain.entities.symbol_tier import SymbolTier, TierLevel


def _make_uow(existing: SymbolTier | None = None) -> Any:
    """Build a minimal fake UnitOfWork with a symbol_tiers stub."""
    tier_repo = MagicMock()
    tier_repo.get = AsyncMock(return_value=existing)
    tier_repo.save = AsyncMock()

    uow = MagicMock()
    uow.symbol_tiers = tier_repo
    uow.commit = AsyncMock()
    # Make it usable as an async context manager
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    return uow


@pytest.mark.unit()
async def test_creates_new_tier_for_unknown_symbol() -> None:
    uow = _make_uow(existing=None)
    uc = UpdateSymbolTierUseCase(uow)

    result = await uc.execute("AAPL", "US", TierLevel.T0, source="portfolio")

    assert result.symbol == "AAPL"
    assert result.exchange == "US"
    assert result.new_tier == TierLevel.T0
    assert result.previous_tier is None
    assert result.changed is True
    uow.symbol_tiers.save.assert_awaited_once()
    uow.commit.assert_awaited_once()


@pytest.mark.unit()
async def test_updates_existing_tier() -> None:
    existing = SymbolTier(symbol="TSLA", exchange="US", tier=TierLevel.T2, tier_source="default")
    uow = _make_uow(existing=existing)
    uc = UpdateSymbolTierUseCase(uow)

    result = await uc.execute("TSLA", "US", TierLevel.T1, source="watchlist")

    assert result.previous_tier == TierLevel.T2
    assert result.new_tier == TierLevel.T1
    assert result.changed is True
    uow.symbol_tiers.save.assert_awaited_once()


@pytest.mark.unit()
async def test_returns_unchanged_when_tier_same() -> None:
    existing = SymbolTier(symbol="AMZN", exchange="US", tier=TierLevel.T1, tier_source="watchlist")
    uow = _make_uow(existing=existing)
    uc = UpdateSymbolTierUseCase(uow)

    result = await uc.execute("AMZN", "US", TierLevel.T1, source="watchlist")

    assert result.changed is False
    assert result.new_tier == TierLevel.T1
    # save must NOT be called when tier hasn't changed
    uow.symbol_tiers.save.assert_not_awaited()
    uow.commit.assert_awaited_once()


@pytest.mark.unit()
async def test_tier_assignment_tracks_source() -> None:
    uow = _make_uow(existing=None)
    uc = UpdateSymbolTierUseCase(uow)

    await uc.execute("BTC-USD", "CC", TierLevel.T3, source="screener")

    saved: SymbolTier = uow.symbol_tiers.save.call_args[0][0]
    assert saved.tier_source == "screener"
    assert saved.tier == TierLevel.T3
