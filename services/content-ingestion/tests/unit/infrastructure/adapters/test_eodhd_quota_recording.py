"""EODHD shared-quota recording for content-ingestion adapters (blind-spot fix).

S4 is the largest EODHD consumer but historically wrote NO shared quota keys,
so the account-wide monthly total undercounted true usage.  These tests guard
the fix:
  * every EODHD request rolls its credit cost into the shared counter,
  * a Valkey failure NEVER breaks ingestion (best-effort),
  * soft/hard limit crossings and auth/quota rejections raise loud safeguards.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from content_ingestion.config import EODHDProviderSettings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient
from content_ingestion.infrastructure.adapters.eodhd_quota import (
    SERVICE_NAME,
    record_eodhd_auth_or_quota_rejection,
    record_eodhd_request,
)
from content_ingestion.infrastructure.adapters.eodhd_ticker_news.adapter import (
    EODHDTickerNewsAdapter,
    ProviderRateLimited,
)
from content_ingestion.infrastructure.metrics.prometheus import (
    s4_eodhd_credits_recorded_total,
    s4_eodhd_quota_alerts_total,
)

from messaging.eodhd_quota.quota_service import QuotaCheckResult

pytestmark = pytest.mark.unit


class _FakeQuotaService:
    """Records the calls made to record_usage and returns a scripted result."""

    def __init__(self, result: QuotaCheckResult | None = QuotaCheckResult.OK) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def record_usage(
        self, cost: int, service: str, symbol: str | None = None, month: str | None = None
    ) -> QuotaCheckResult | None:
        self.calls.append({"cost": cost, "service": service, "symbol": symbol})
        return self._result


# ── record_eodhd_request ──────────────────────────────────────────────────────


class TestRecordEodhdRequest:
    async def test_records_credits_and_attributes_to_service(self) -> None:
        credits_metric = s4_eodhd_credits_recorded_total.labels(endpoint="ticker_news")
        before = credits_metric._value.get()
        qs = _FakeQuotaService()

        await record_eodhd_request(qs, endpoint="ticker_news", credit_cost=5, symbol="AAPL.US")

        # Local Prometheus credit counter incremented by the credit cost.
        assert credits_metric._value.get() - before == 5
        # Shared counter called with S4's stable service identity.
        assert qs.calls == [{"cost": 5, "service": SERVICE_NAME, "symbol": "AAPL.US"}]

    async def test_none_quota_service_is_noop(self) -> None:
        before = s4_eodhd_credits_recorded_total.labels(endpoint="news")._value.get()

        # Must not raise when Valkey/quota is unconfigured.
        await record_eodhd_request(None, endpoint="news", credit_cost=5)

        after = s4_eodhd_credits_recorded_total.labels(endpoint="news")._value.get()
        assert after == before

    async def test_soft_limit_raises_alert(self) -> None:
        alert = s4_eodhd_quota_alerts_total.labels(reason="soft_limit")
        before = alert._value.get()
        qs = _FakeQuotaService(result=QuotaCheckResult.SOFT_LIMIT_EXCEEDED)

        await record_eodhd_request(qs, endpoint="ticker_news", credit_cost=5)

        assert alert._value.get() - before == 1

    async def test_hard_limit_raises_alert(self) -> None:
        alert = s4_eodhd_quota_alerts_total.labels(reason="hard_limit")
        before = alert._value.get()
        qs = _FakeQuotaService(result=QuotaCheckResult.HARD_LIMIT_EXCEEDED)

        await record_eodhd_request(qs, endpoint="ticker_news", credit_cost=5)

        assert alert._value.get() - before == 1

    async def test_valkey_failure_returns_none_no_alert(self) -> None:
        """record_usage None (Valkey down) → credits still counted, no alert."""
        alert_soft = s4_eodhd_quota_alerts_total.labels(reason="soft_limit")
        before_soft = alert_soft._value.get()
        qs = _FakeQuotaService(result=None)

        # Must not raise even though the shared counter could not be written.
        await record_eodhd_request(qs, endpoint="news", credit_cost=5)

        assert alert_soft._value.get() == before_soft


class TestRecordAuthRejection:
    async def test_increments_auth_or_quota_alert(self) -> None:
        alert = s4_eodhd_quota_alerts_total.labels(reason="auth_or_quota_rejected")
        before = alert._value.get()

        record_eodhd_auth_or_quota_rejection("news", 401, symbol="AAPL.US")

        assert alert._value.get() - before == 1


# ── Integration through the real adapters ─────────────────────────────────────


class TestEODHDClientRecordsQuota:
    def _client(self, http: httpx.AsyncClient, qs: Any) -> EODHDClient:
        return EODHDClient(
            http_client=http,
            api_key="k",
            provider_cfg=EODHDProviderSettings(),
            quota_service=qs,
        )

    async def test_success_records_shared_quota(self) -> None:
        qs = _FakeQuotaService()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"link": "x", "date": "2026-03-01"}])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await self._client(http, qs).fetch_news(ticker="AAPL.US")

        # Exactly one request → exactly one shared-counter increment of 5 credits.
        assert len(qs.calls) == 1
        assert qs.calls[0]["cost"] == 5
        assert qs.calls[0]["service"] == SERVICE_NAME

    async def test_401_raises_auth_alert_and_does_not_record_credits(self) -> None:
        alert = s4_eodhd_quota_alerts_total.labels(reason="auth_or_quota_rejected")
        before = alert._value.get()
        qs = _FakeQuotaService()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AdapterError):
                await self._client(http, qs).fetch_news(ticker="AAPL.US")

        # Auth safeguard fired; a rejected (unbilled) request records no credits.
        assert alert._value.get() - before == 1
        assert qs.calls == []


class TestEODHDTickerNewsAdapterRecordsQuota:
    def _settings(self) -> MagicMock:
        s = MagicMock()
        s.eodhd_api_key = "k"
        # Real provider sub-model so numeric page/overlap/credit config is read
        # (a bare MagicMock would yield MagicMock ints → TypeError in timedelta).
        s.eodhd = EODHDProviderSettings()
        s.backfill_initial_days = 14
        return s

    def _source(self, symbol: str = "AAPL", exchange: str = "US") -> MagicMock:
        source = MagicMock()
        source.id = __import__("uuid").uuid4()
        source.name = "aapl-ticker-news"
        source.config = {"symbol": symbol, "exchange": exchange}
        return source

    def _response(self, json_data: object, status_code: int = 200) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = json_data
        return resp

    async def test_success_records_shared_quota_per_request(self) -> None:
        qs = _FakeQuotaService()
        adapter = EODHDTickerNewsAdapter(settings=self._settings(), quota_service=qs)

        # One partial page → one request → one shared-counter increment.
        articles = [{"link": "https://x/1", "date": "2026-03-01", "title": "t"}]
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = self._response(articles)

            await adapter.fetch(self._source())

        assert len(qs.calls) == 1
        assert qs.calls[0]["cost"] == 5
        assert qs.calls[0]["service"] == SERVICE_NAME
        assert qs.calls[0]["symbol"] == "AAPL.US"

    async def test_429_raises_auth_alert(self) -> None:
        alert = s4_eodhd_quota_alerts_total.labels(reason="auth_or_quota_rejected")
        before = alert._value.get()
        qs = _FakeQuotaService()
        adapter = EODHDTickerNewsAdapter(settings=self._settings(), quota_service=qs)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = self._response(None, status_code=429)

            with pytest.raises(ProviderRateLimited):
                await adapter.fetch(self._source())

        assert alert._value.get() - before == 1
        # Rejected request bills no credits.
        assert qs.calls == []
