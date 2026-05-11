"""Tests for F-104 — PremiumEndpointError + retry-loop short-circuit."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.base import (
    RetryConfig,
    SourceAdapter,
    _is_retryable,
)
from content_ingestion.infrastructure.adapters.finnhub.client import (
    FinnhubClient,
    PremiumEndpointError,
    RateLimitError,
)

pytestmark = pytest.mark.unit


class TestPremiumEndpointError:
    def test_inherits_adapter_error(self) -> None:
        """PremiumEndpointError must be an AdapterError so legacy except
        handlers still catch it (we only need to discriminate it before they do)."""
        exc = PremiumEndpointError(endpoint="/api/v1/stock/transcripts/list")
        assert isinstance(exc, AdapterError)
        assert "/api/v1/stock/transcripts/list" in str(exc)
        assert "premium" in str(exc).lower()

    def test_endpoint_attribute_preserved(self) -> None:
        exc = PremiumEndpointError(endpoint="/foo")
        assert exc.endpoint == "/foo"

    def test_check_response_raises_premium_on_403(self) -> None:
        # Build a fake httpx-like response — only status_code + .request.url.path used.
        client = FinnhubClient(http_client=MagicMock(), api_key="x", provider_cfg=MagicMock(base_url="http://x"))
        response = MagicMock()
        response.status_code = 403
        response.request = MagicMock()
        response.request.url = MagicMock()
        response.request.url.path = "/api/v1/stock/transcripts/list"
        with pytest.raises(PremiumEndpointError) as ei:
            client._check_response(response)
        assert ei.value.endpoint == "/api/v1/stock/transcripts/list"

    def test_check_response_raises_rate_limit_on_429(self) -> None:
        # Sanity — make sure F-104 didn't break the existing 429 path.
        client = FinnhubClient(http_client=MagicMock(), api_key="x", provider_cfg=MagicMock(base_url="http://x"))
        response = MagicMock()
        response.status_code = 429
        with pytest.raises(RateLimitError):
            client._check_response(response)

    def test_check_response_raises_adapter_error_on_other_4xx(self) -> None:
        client = FinnhubClient(http_client=MagicMock(), api_key="x", provider_cfg=MagicMock(base_url="http://x"))
        response = MagicMock()
        response.status_code = 500
        with pytest.raises(AdapterError) as ei:
            client._check_response(response)
        # Must NOT be the premium-specific subclass for non-403.
        assert not isinstance(ei.value, PremiumEndpointError)


class TestIsRetryable:
    def test_premium_endpoint_error_is_not_retryable(self) -> None:
        assert _is_retryable(PremiumEndpointError(endpoint="/x")) is False

    def test_rate_limit_error_is_retryable(self) -> None:
        assert _is_retryable(RateLimitError(sleep_secs=1.0)) is True

    def test_generic_adapter_error_is_retryable(self) -> None:
        assert _is_retryable(AdapterError("transient")) is True

    def test_non_adapter_exception_is_retryable(self) -> None:
        # ConnectionError, TimeoutError etc. — must keep the legacy retry semantics.
        assert _is_retryable(ConnectionError("conn refused")) is True


class TestRetryRequestShortCircuitsPremium:
    @pytest.mark.asyncio
    async def test_premium_error_does_not_retry(self) -> None:
        """The retry loop must NOT sleep or retry on PremiumEndpointError.

        Regression guard for F-104: before the fix, every 403 burned 3
        attempts x (1+2+4)s of backoff, wasting ~7s per symbol.
        """
        call_count = 0

        async def coro() -> None:
            nonlocal call_count
            call_count += 1
            raise PremiumEndpointError(endpoint="/transcripts/list")

        with pytest.raises(PremiumEndpointError):
            await SourceAdapter._retry_request(coro, retry_config=RetryConfig(), context="test")
        assert call_count == 1, "Premium error must not be retried"

    @pytest.mark.asyncio
    async def test_generic_error_still_retries(self) -> None:
        """Regression guard — F-104 must not regress the generic-retry path."""
        call_count = 0

        async def coro() -> None:
            nonlocal call_count
            call_count += 1
            raise AdapterError("transient")

        with pytest.raises(AdapterError):
            await SourceAdapter._retry_request(
                coro,
                retry_config=RetryConfig(max_retries=2, backoff_factors=(0.0, 0.0)),
                context="test",
            )
        # max_retries=2 → loop runs 3 times (initial + 2 retries).
        assert call_count == 3
