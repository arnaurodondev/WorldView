"""PolygonProviderAdapter stub — not yet implemented."""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_ingestion.application.ports.adapters import ProviderAdapter, ProviderFetchResult
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderUnavailable

if TYPE_CHECKING:
    from datetime import datetime


class PolygonProviderAdapter(ProviderAdapter):
    """Stub adapter for Polygon.io — raises ProviderUnavailable until implemented."""

    @property
    def provider(self) -> Provider:
        return Provider.POLYGON

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Polygon adapter not yet implemented")

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Polygon adapter not yet implemented")

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Polygon adapter not yet implemented")
