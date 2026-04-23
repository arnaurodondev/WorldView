"""YahooFinanceProviderAdapter stub — not yet implemented."""

from __future__ import annotations

from datetime import datetime

from market_ingestion.application.ports.adapters import ProviderAdapter, ProviderFetchResult
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderUnavailable


class YahooFinanceProviderAdapter(ProviderAdapter):
    """Stub adapter for Yahoo Finance — raises ProviderUnavailable until implemented."""

    @property
    def provider(self) -> Provider:
        return Provider.YAHOO_FINANCE

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Yahoo Finance adapter not yet implemented")

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Yahoo Finance adapter not yet implemented")

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Yahoo Finance adapter not yet implemented")
