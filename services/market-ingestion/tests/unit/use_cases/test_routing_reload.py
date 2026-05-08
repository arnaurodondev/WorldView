"""Unit tests for RoutingReloadUseCase.

Covers:
- execute() calls load_from_config and returns correct slot count
- execute() returns reloaded=True
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from market_ingestion.application.use_cases.routing_reload import RoutingReloadUseCase

pytestmark = pytest.mark.unit


def _make_cache(slot_count: int = 5) -> MagicMock:
    """Build a mock ProviderRoutingCache that returns *slot_count* on load."""
    cache = MagicMock()
    cache.load_from_config = MagicMock(return_value=slot_count)
    return cache


def _make_settings() -> MagicMock:
    """Build a mock Settings."""
    return MagicMock()


@pytest.mark.unit()
def test_routing_reload_calls_load_from_config() -> None:
    """execute() calls load_from_config() on the cache and returns correct slot count."""
    cache = _make_cache(slot_count=11)
    settings = _make_settings()
    uc = RoutingReloadUseCase(cache=cache, settings=settings)

    result = uc.execute()

    cache.load_from_config.assert_called_once_with(settings)
    assert result == {"reloaded": True, "rules_loaded": 11}


@pytest.mark.unit()
def test_routing_reload_returns_reloaded_true() -> None:
    """execute() always returns reloaded=True."""
    cache = _make_cache(slot_count=0)
    settings = _make_settings()
    uc = RoutingReloadUseCase(cache=cache, settings=settings)

    result = uc.execute()

    assert result["reloaded"] is True


@pytest.mark.unit()
def test_routing_reload_different_slot_counts() -> None:
    """execute() returns the exact count from load_from_config()."""
    for count in (0, 1, 7, 42):
        cache = _make_cache(slot_count=count)
        settings = _make_settings()
        uc = RoutingReloadUseCase(cache=cache, settings=settings)
        result = uc.execute()
        assert result["rules_loaded"] == count
