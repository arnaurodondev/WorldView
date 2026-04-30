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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
        httpx_mock.add_response(
            method="POST",
            url="http://api-gateway:8000/v1/auth/dev-login",
            status_code=503,
            text="gateway down",
        )
        httpx_mock.add_response(
            method="GET",
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
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
            url=f"http://market-data:8003/api/v1/market-data/ohlcv/{_SYMBOL}?start=2026-04-01&end=2026-04-01",
            json=_OHLCV_LIST_RESPONSE,
            status_code=200,
        )

        async with httpx.AsyncClient() as client:
            mc = MarketDataClient(client, "http://market-data:8003")
            bar = await mc.get_ohlcv(_SYMBOL, _DATE)

        assert bar is not None
        login_calls = [r for r in httpx_mock.get_requests() if "dev-login" in str(r.url)]
        assert login_calls == []
