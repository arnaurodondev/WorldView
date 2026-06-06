"""Verify the EODHD client emits Prometheus per-attempt metrics (BP-174 wiring).

These tests guard against regression to the "metrics defined but never called"
pattern by asserting that:
  - happy-path fetch increments s4_fetches_total{status="success"}
  - HTTP error path increments s4_fetches_total{status="error"}
  - HTTP 429 path increments s4_fetches_total{status="rate_limited"}
  - the duration histogram observes a positive sample on every attempt
"""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.config import EODHDProviderSettings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
from content_ingestion.infrastructure.metrics.prometheus import (
    s4_fetch_duration_seconds,
    s4_fetches_total,
)

pytestmark = pytest.mark.unit


def _make_client(http: httpx.AsyncClient) -> EODHDClient:
    return EODHDClient(http_client=http, api_key="k", provider_cfg=EODHDProviderSettings())


class TestEODHDClientMetrics:
    async def test_success_increments_success_counter(self) -> None:
        before = s4_fetches_total.labels(source="eodhd", status="success")._value.get()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"link": "x", "date": "2026-03-01"}])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await _make_client(http).fetch_news(ticker="AAPL.US")

        after = s4_fetches_total.labels(source="eodhd", status="success")._value.get()
        assert after - before == 1

    async def test_error_increments_error_counter(self) -> None:
        before = s4_fetches_total.labels(source="eodhd", status="error")._value.get()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError):
                await _make_client(http).fetch_news(ticker="AAPL.US")

        after = s4_fetches_total.labels(source="eodhd", status="error")._value.get()
        assert after - before == 1

    async def test_rate_limited_increments_rate_limited_counter(self) -> None:
        before = s4_fetches_total.labels(source="eodhd", status="rate_limited")._value.get()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError):
                await _make_client(http).fetch_news(ticker="AAPL.US")

        after = s4_fetches_total.labels(source="eodhd", status="rate_limited")._value.get()
        assert after - before == 1

    async def test_duration_histogram_observes_positive_sample(self) -> None:
        """Every attempt — success or failure — must produce a histogram sample."""
        hist = s4_fetch_duration_seconds.labels(source="eodhd")
        before_sum = hist._sum.get()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await _make_client(http).fetch_news(ticker="AAPL.US")

        # Sum is monotonic and increases by the observed duration (a positive float).
        assert hist._sum.get() - before_sum > 0.0
