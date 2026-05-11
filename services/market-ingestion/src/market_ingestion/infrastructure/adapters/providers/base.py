"""BaseProviderAdapter — shared observability mixin for all provider adapters."""

from __future__ import annotations

from urllib.parse import urlparse

from market_ingestion.application.ports.adapters import ProviderAdapter
from market_ingestion.infrastructure.metrics.providers import (
    record_provider_error,
    record_provider_rate_limited,
    record_provider_request,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class BaseProviderAdapter(ProviderAdapter):
    """Extends ProviderAdapter with shared observability.

    Every concrete adapter MUST extend this class and call the appropriate
    _record_* method on every completed fetch (success or error).

    Guarantees:
    - A ``provider_api_call`` structlog event for every fetch outcome
    - Generic Prometheus metrics (s2_mi_provider_*) incremented uniformly
    - Loki and Prometheus dashboards work across all providers
    """

    @staticmethod
    def _sanitize_url_slug(url: str) -> str:
        """Extract a safe endpoint label — no query params, no secrets.

        Examples
        --------
            "https://finnhub.io/api/v1/company-news?token=SECRET" -> "company-news"
            "https://eodhd.com/api/eod/AAPL.US?api_token=SECRET"  -> "eod"
        """
        path = urlparse(url).path
        segments = [p for p in path.split("/") if p and p not in ("api", "v1")]
        return segments[0] if segments else "unknown"

    def _record_api_call(
        self,
        *,
        dataset_type: str,
        symbol: str,
        exchange: str = "",
        timeframe: str = "",
        bars_returned: int = 0,
        latency_ms: int,
        credit_cost: int = 0,
        status: str = "success",
    ) -> None:
        """Emit provider_api_call log event and increment shared Prometheus metrics."""
        logger.info(
            "provider_api_call",
            provider=self.provider.value,
            dataset_type=dataset_type,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            bars_returned=bars_returned,
            latency_ms=latency_ms,
            credit_cost=credit_cost,
            status=status,
        )
        record_provider_request(
            provider=self.provider.value,
            dataset_type=dataset_type,
            timeframe=timeframe,
            duration_seconds=latency_ms / 1000.0,
            credit_cost=credit_cost,
        )

    def _record_rate_limited(self, *, endpoint: str = "") -> None:
        """Emit rate-limit log and increment s2_mi_provider_rate_limited_total."""
        logger.warning(
            "provider_rate_limited",
            provider=self.provider.value,
            endpoint=endpoint,
        )
        record_provider_rate_limited(provider=self.provider.value)

    def _record_error(self, *, reason: str, endpoint: str = "") -> None:
        """Emit error log and increment s2_mi_provider_errors_total."""
        logger.error(
            "provider_error",
            provider=self.provider.value,
            endpoint=endpoint,
            reason=reason,
        )
        record_provider_error(provider=self.provider.value, reason=reason)
