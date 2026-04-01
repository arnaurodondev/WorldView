"""Unit tests for ProviderRegistry (T-E1-1-05).

Verifies that D-006 decision is enforced: Polygon and AlphaVantage are NOT
registered in the production registry (stubs removed until real implementation).
"""

from __future__ import annotations

import pytest
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderUnavailable
from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_adapter(provider: Provider) -> object:
    """Minimal stub that satisfies the registry.register() interface."""
    from unittest.mock import MagicMock

    adapter = MagicMock()
    adapter.provider = provider
    return adapter


# ---------------------------------------------------------------------------
# Tests — D-006: Polygon and AlphaVantage removed from registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_registry_polygon_not_registered() -> None:
    """ProviderRegistry.get(POLYGON) raises ProviderUnavailable — D-006."""
    registry = ProviderRegistry()
    with pytest.raises(ProviderUnavailable, match="POLYGON"):
        registry.get(Provider.POLYGON)


@pytest.mark.unit
def test_registry_alpha_vantage_not_registered() -> None:
    """ProviderRegistry.get(ALPHA_VANTAGE) raises ProviderUnavailable — D-006."""
    registry = ProviderRegistry()
    with pytest.raises(ProviderUnavailable, match="ALPHA_VANTAGE"):
        registry.get(Provider.ALPHA_VANTAGE)


@pytest.mark.unit
def test_registry_eodhd_still_registered() -> None:
    """EODHD can be registered and retrieved successfully."""
    registry = ProviderRegistry()
    adapter = _stub_adapter(Provider.EODHD)
    registry.register(adapter)  # type: ignore[arg-type]
    result = registry.get(Provider.EODHD)
    assert result is adapter


@pytest.mark.unit
def test_build_provider_registry_does_not_contain_polygon() -> None:
    """build_provider_registry() does not register Polygon (D-006)."""
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry

    registry = build_provider_registry()
    with pytest.raises(ProviderUnavailable):
        registry.get(Provider.POLYGON)


@pytest.mark.unit
def test_build_provider_registry_does_not_contain_alpha_vantage() -> None:
    """build_provider_registry() does not register AlphaVantage (D-006)."""
    from market_ingestion.infrastructure.adapters.providers import build_provider_registry

    registry = build_provider_registry()
    with pytest.raises(ProviderUnavailable):
        registry.get(Provider.ALPHA_VANTAGE)
