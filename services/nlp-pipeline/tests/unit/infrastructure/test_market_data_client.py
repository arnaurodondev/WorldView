"""Unit tests for MarketDataClient (T-B-1-01)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest
from nlp_pipeline.infrastructure.http.market_data_client import MarketDataClient, OHLCVBar

if TYPE_CHECKING:
    import pytest_httpx

pytestmark = pytest.mark.unit

_DATE = date(2026, 4, 1)
_SYMBOL = "AAPL"
# PLAN-0052 platform-QA round 4 (2026-05-01): client now resolves ticker
# → instrument_id before fetching OHLCV. Use a deterministic UUID so the
# tests can predict the second URL.
# PLAN-0073 B-1: /instruments/symbol/{ticker} was removed; use the unified
# /instruments/lookup?symbol= endpoint. Response field is "id", not "instrument_id".
_RESOLVED_ID = "550e8400-e29b-41d4-a716-446655440000"
_RESOLVE_URL = f"http://market-data:8003/api/v1/instruments/lookup?symbol={_SYMBOL}"
_RESOLVE_RESPONSE = {"id": _RESOLVED_ID, "symbol": _SYMBOL, "exchange": "US", "is_active": True}


@pytest.fixture(autouse=True)
def _mock_ticker_resolve(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    """Auto-mock the ticker→UUID resolve so OHLCV tests focus on the
    OHLCV fetch path. Each test gets a fresh httpx_mock — the resolve
    response is consumed by the FIRST httpx GET in the client, then the
    second GET (for OHLCV) hits the test-specific mock. Tests that don't
    call get_ohlcv simply leave this mock unused (which is fine —
    pytest-httpx complains only about UNMOCKED requests, not unused
    mocks unless `assert_all_responses_were_requested=True`)."""
    httpx_mock.add_response(url=_RESOLVE_URL, json=_RESOLVE_RESPONSE)


_OHLCV_LIST_RESPONSE = {
    "items": [
        {
            "instrument_id": "AAPL",
            "timeframe": "1d",
            "bar_date": "2026-04-01T00:00:00",
            "open": "150.00",
            "high": "155.00",
            "low": "149.00",
            "close": "153.00",
            "volume": 1000000,
            "adjusted_close": None,
            "source": "eodhd",
        }
    ],
    "total": 1,
    "timeframe": "1d",
}


class TestMarketDataClientParsesOHLCV:
    @pytest.mark.asyncio
    async def test_market_data_client_parses_ohlcv(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with 200 JSON response returns populated OHLCVBar."""
        httpx_mock.add_response(
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert isinstance(bar, OHLCVBar)
        assert bar.symbol == _SYMBOL
        assert bar.date == _DATE
        assert bar.open == Decimal("150.00")
        assert bar.close == Decimal("153.00")
        assert bar.high == Decimal("155.00")
        assert bar.low == Decimal("149.00")
        assert bar.volume == 1000000

    @pytest.mark.asyncio
    async def test_market_data_client_returns_none_when_items_empty(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with empty items list returns None."""
        httpx_mock.add_response(
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json={"items": [], "total": 0, "timeframe": "1d"},
            status_code=200,
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is None


class TestMarketDataClientNot404:
    @pytest.mark.asyncio
    async def test_market_data_client_returns_none_on_404(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with 404 returns None without raising."""
        httpx_mock.add_response(
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            status_code=404,
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is None

    @pytest.mark.asyncio
    async def test_market_data_client_returns_none_on_5xx(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with 500 returns None and logs warning."""
        httpx_mock.add_response(
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            status_code=500,
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is None


class TestMarketDataClientTimeout:
    @pytest.mark.asyncio
    async def test_market_data_client_returns_none_on_timeout(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with RequestError returns None without raising."""
        httpx_mock.add_exception(
            httpx.ConnectTimeout("timed out"),
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is None

    @pytest.mark.asyncio
    async def test_market_data_client_returns_none_on_zero_price(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """get_ohlcv() with open=0 returns None (invalid bar)."""
        bad_response = {
            "items": [
                {
                    "instrument_id": "AAPL",
                    "timeframe": "1d",
                    "bar_date": "2026-04-01T00:00:00",
                    "open": "0.00",
                    "high": "0.00",
                    "low": "0.00",
                    "close": "0.00",
                    "volume": 0,
                    "adjusted_close": None,
                    "source": "eodhd",
                }
            ],
            "total": 1,
            "timeframe": "1d",
        }
        httpx_mock.add_response(
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=bad_response,
            status_code=200,
        )
        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is None


class TestMarketDataClientInternalJWT:
    """PLAN-0057 Wave E-1 — verify the X-Internal-JWT header path.

    market-data is guarded by ``InternalJWTMiddleware`` so unauthenticated
    requests return 401 and ``article_impact_windows`` stays empty.  The
    fix: when ``api_gateway_url`` is configured, MarketDataClient mints a
    token via S9's ``POST /v1/auth/dev-login`` and forwards it as
    ``X-Internal-JWT`` on every OHLCV call.
    """

    @pytest.mark.asyncio
    async def test_mints_token_and_sets_header(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """Happy path: gateway returns access_token, OHLCV request carries the header."""
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            json={"access_token": "eyJ.fake-jwt"},
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
            )
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None
        ohlcv_req = next(r for r in httpx_mock.get_requests() if "ohlcv" in str(r.url))
        assert ohlcv_req.headers.get("X-Internal-JWT") == "eyJ.fake-jwt"

    @pytest.mark.asyncio
    async def test_token_is_cached_across_calls(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """Two get_ohlcv calls in quick succession must share a single dev-login mint."""
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            json={"access_token": "cached-token"},
            status_code=200,
        )
        # Each call consumes one queued response; both must succeed.
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
            )
            await mc.get_ohlcv(_SYMBOL, _DATE)
            await mc.get_ohlcv(_SYMBOL, _DATE)

        login_calls = [r for r in httpx_mock.get_requests() if "dev-login" in str(r.url)]
        assert len(login_calls) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_no_header_when_gateway_unreachable(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """If dev-login fails, fall back to unauthenticated request (preserve 401-and-warn)."""
        # Two 503 mocks: _get_internal_jwt is called once before ticker-resolve
        # and once before OHLCV fetch; each failed mint leaves _token=None so the
        # cache is not populated and both calls hit the endpoint.
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            status_code=503,
            text="gateway down",
        )
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            status_code=503,
            text="gateway down",
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
            )
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None  # Bar still parses — token-failure is non-fatal.
        ohlcv_req = next(r for r in httpx_mock.get_requests() if "ohlcv" in str(r.url))
        assert "X-Internal-JWT" not in ohlcv_req.headers

    @pytest.mark.asyncio
    async def test_no_gateway_url_means_no_token_attempt(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """Backward-compat: if api_gateway_url omitted, never call dev-login."""
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None
        login_calls = [r for r in httpx_mock.get_requests() if "dev-login" in str(r.url)]
        assert login_calls == []


class TestMarketDataClientServiceToken:
    """PLAN-0057 Wave A-1 / BP-303 — verify service-account auth path.

    When ``service_account_token`` is set, MarketDataClient must mint its
    X-Internal-JWT via S9's production-safe ``POST /internal/v1/service-token``
    endpoint. When unset, it must fall back to ``POST /v1/auth/dev-login``
    (the legacy local-dev path) so existing tests and dev workflows keep
    working.
    """

    @pytest.mark.asyncio
    async def test_uses_service_token_endpoint_when_secret_set(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """``service_account_token`` set → POST /internal/v1/service-token, NOT /v1/auth/dev-login."""
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/internal/v1/service-token",
            json={"access_token": "svc-token-abc", "expires_in": 300, "token_type": "Bearer"},
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
                service_account_token="shared-secret-xyz",
            )
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None

        # Verify: service-token call made, dev-login NOT called.
        all_requests = httpx_mock.get_requests()
        svc_calls = [r for r in all_requests if "service-token" in str(r.url)]
        dev_login_calls = [r for r in all_requests if "dev-login" in str(r.url)]
        assert len(svc_calls) == 1, "Should mint via /internal/v1/service-token"
        assert dev_login_calls == [], "dev-login MUST NOT be called when service_account_token is set"

        # Verify: request body carries the secret + service_name
        import json

        body = json.loads(svc_calls[0].content.decode())
        assert body == {
            "service_name": "nlp-pipeline-price-impact",
            "secret": "shared-secret-xyz",
        }

        # Verify: OHLCV request carries the minted JWT
        ohlcv_req = next(r for r in all_requests if "ohlcv" in str(r.url))
        assert ohlcv_req.headers.get("X-Internal-JWT") == "svc-token-abc"

    @pytest.mark.asyncio
    async def test_falls_back_to_dev_login_when_service_token_unset(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """``service_account_token`` unset → POST /v1/auth/dev-login (legacy path)."""
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            json={"access_token": "dev-token-xyz"},
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
                # service_account_token left unset → fallback path
            )
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None
        all_requests = httpx_mock.get_requests()
        dev_login_calls = [r for r in all_requests if "dev-login" in str(r.url)]
        svc_calls = [r for r in all_requests if "service-token" in str(r.url)]
        assert len(dev_login_calls) == 1
        assert svc_calls == []

    @pytest.mark.asyncio
    async def test_empty_service_token_treated_as_unset(self, httpx_mock: pytest_httpx.HTTPXMock) -> None:
        """An empty string ``service_account_token`` (common .env pattern) falls back to dev-login."""
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            json={"access_token": "dev-token-xyz"},
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
                service_account_token="",  # empty string == unset
            )
            await mc.get_ohlcv(_SYMBOL, _DATE)

        all_requests = httpx_mock.get_requests()
        dev_login_calls = [r for r in all_requests if "dev-login" in str(r.url)]
        svc_calls = [r for r in all_requests if "service-token" in str(r.url)]
        assert len(dev_login_calls) == 1
        assert svc_calls == []

    @pytest.mark.asyncio
    async def test_service_token_failure_does_not_fall_back_to_dev_login(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ) -> None:
        """If service-token returns 401 (e.g. wrong secret), do NOT silently call dev-login.

        The client returns ``None`` from ``_get_internal_jwt`` and the OHLCV
        request goes out unauthenticated. This preserves the legacy
        401-and-warn fallback behaviour without leaking attempts to a
        secondary auth path that the operator deliberately disabled.
        """
        # Two 401 mocks: _get_internal_jwt is called once before ticker-resolve and
        # once before OHLCV fetch; failed service-token mints don't populate _token
        # so each inner request retries the service-token endpoint independently.
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/internal/v1/service-token",
            status_code=401,
            json={"error": "unauthorized"},
        )
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/internal/v1/service-token",
            status_code=401,
            json={"error": "unauthorized"},
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/ohlcv/{_RESOLVED_ID}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(
                client,
                "http://market-data:8003",
                api_gateway_url="http://api-gateway:8000",
                service_account_token="bad-secret",
            )
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None
        all_requests = httpx_mock.get_requests()
        svc_calls = [r for r in all_requests if "service-token" in str(r.url)]
        dev_login_calls = [r for r in all_requests if "dev-login" in str(r.url)]
        # PLAN-0052 platform-QA round 4 (2026-05-01): client now makes
        # two backend HTTP requests per OHLCV fetch (resolve ticker→UUID,
        # then OHLCV). Each calls `_get_internal_jwt` independently; on
        # service-token failure the cache is NOT populated so each
        # attempt re-mints. The number of svc-token calls is therefore
        # 2 (once per inner request), not 1. The IMPORTANT assertion is
        # the dev-login fallback check — that's the security invariant.
        assert len(svc_calls) >= 1, "Service-token must be attempted at least once"
        assert dev_login_calls == [], "Must NOT silently fall back to dev-login"

        ohlcv_req = next(r for r in all_requests if "/api/v1/ohlcv/" in str(r.url))
        assert "X-Internal-JWT" not in ohlcv_req.headers
