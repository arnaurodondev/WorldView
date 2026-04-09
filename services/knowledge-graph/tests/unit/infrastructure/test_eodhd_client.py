"""Unit tests for EodhDClient (Workers 13D-6, 13D-7, 13D-8)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_http(
    status_code: int = 200,
    json_data: Any = None,
    raise_exc: Exception | None = None,
) -> AsyncMock:
    """Build a mock httpx.AsyncClient."""
    http = AsyncMock()
    if raise_exc is not None:
        http.get = AsyncMock(side_effect=raise_exc)
        return http
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no body"))
    http.get = AsyncMock(return_value=resp)
    return http


def _make_client(http: AsyncMock, api_key: str = "test-key") -> Any:
    from knowledge_graph.infrastructure.eodhd.client import EodhDClient

    return EodhDClient(api_key=api_key, http=http, base_url="https://eodhd.example.com/api")


class TestGetEconomicEvents:
    def test_happy_path_returns_list(self) -> None:
        """get_economic_events returns the raw list from the API."""
        events = [{"date": "2026-04-01", "type": "CPI m/m", "country": "US"}]
        http = _make_http(status_code=200, json_data=events)
        client = _make_client(http)

        result = __import__("asyncio").run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == events

    def test_default_to_date_is_from_date_plus_one_day(self) -> None:
        """When to_date is None, the 'to' param is from_date + 1 day."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)
        from_d = date(2026, 4, 1)

        import asyncio

        asyncio.run(client.get_economic_events("US", from_d))

        call_kwargs = http.get.call_args[1]["params"]
        assert call_kwargs["from"] == "2026-04-01"
        assert call_kwargs["to"] == str(from_d + timedelta(days=1))

    def test_explicit_to_date_used(self) -> None:
        """When to_date is provided explicitly, it is passed to the API."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)

        import asyncio

        asyncio.run(client.get_economic_events("US", date(2026, 4, 1), to_date=date(2026, 4, 7)))

        call_kwargs = http.get.call_args[1]["params"]
        assert call_kwargs["to"] == "2026-04-07"

    def test_api_key_included_in_request(self) -> None:
        """The api_token query param is sent with each request."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http, api_key="secret-key")

        import asyncio

        asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        params = http.get.call_args[1]["params"]
        assert params["api_token"] == "secret-key"  # noqa: S105

    def test_network_error_returns_empty_list(self) -> None:
        """On connection error, returns [] without raising."""
        http = _make_http(raise_exc=ConnectionError("timeout"))
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []

    def test_http_401_returns_empty_list(self) -> None:
        """HTTP 401 returns [] (logs auth error)."""
        http = _make_http(status_code=401)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []

    def test_http_500_returns_empty_list(self) -> None:
        """HTTP 5xx returns [] (logs warning)."""
        http = _make_http(status_code=500)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []

    def test_http_429_returns_empty_list(self) -> None:
        """HTTP 429 (rate limit) returns []."""
        http = _make_http(status_code=429)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []

    def test_malformed_json_returns_empty_list(self) -> None:
        """If resp.json() raises, returns []."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(side_effect=ValueError("invalid json"))
        http = AsyncMock()
        http.get = AsyncMock(return_value=resp)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []

    def test_non_list_response_returns_empty_list(self) -> None:
        """If the API returns a dict (not a list), returns []."""
        http = _make_http(status_code=200, json_data={"error": "unexpected shape"})
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_economic_events("US", date(2026, 4, 1)))

        assert result == []


class TestGetMacroIndicator:
    def test_happy_path_returns_list(self) -> None:
        """get_macro_indicator returns list of indicator records."""
        records = [{"date": "2025-01-01", "value": 27360.0}]
        http = _make_http(status_code=200, json_data=records)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_macro_indicator("USA", "gdp_current_usd"))

        assert result == records

    def test_url_includes_iso3_country(self) -> None:
        """The ISO-3 country code is part of the URL path."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)

        import asyncio

        asyncio.run(client.get_macro_indicator("DEU", "unemployment_total_percent"))

        url_called = http.get.call_args[0][0]
        assert url_called.endswith("/macro-indicator/DEU")

    def test_indicator_code_in_params(self) -> None:
        """The indicator code is passed as a query param."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)

        import asyncio

        asyncio.run(client.get_macro_indicator("USA", "gdp_current_usd"))

        params = http.get.call_args[1]["params"]
        assert params["indicator"] == "gdp_current_usd"

    def test_network_error_returns_empty(self) -> None:
        http = _make_http(raise_exc=TimeoutError("timeout"))
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_macro_indicator("USA", "gdp_current_usd"))

        assert result == []

    def test_non_list_returns_empty(self) -> None:
        http = _make_http(status_code=200, json_data={"message": "not a list"})
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_macro_indicator("USA", "gdp_current_usd"))

        assert result == []


class TestGetInsiderTransactions:
    def test_happy_path_returns_list(self) -> None:
        """get_insider_transactions returns list of transaction records."""
        txns = [{"transactionDate": "2026-03-15", "ownerName": "Tim Cook", "transactionCode": "S"}]
        http = _make_http(status_code=200, json_data=txns)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_insider_transactions("AAPL.US"))

        assert result == txns

    def test_code_and_limit_in_params(self) -> None:
        """ticker code and limit are included in the request params."""
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)

        import asyncio

        asyncio.run(client.get_insider_transactions("MSFT.US", limit=50))

        params = http.get.call_args[1]["params"]
        assert params["code"] == "MSFT.US"
        assert params["limit"] == 50

    def test_default_limit_is_100(self) -> None:
        http = _make_http(status_code=200, json_data=[])
        client = _make_client(http)

        import asyncio

        asyncio.run(client.get_insider_transactions("AAPL.US"))

        params = http.get.call_args[1]["params"]
        assert params["limit"] == 100

    def test_http_error_returns_empty(self) -> None:
        http = _make_http(status_code=503)
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_insider_transactions("AAPL.US"))

        assert result == []

    def test_network_error_returns_empty(self) -> None:
        http = _make_http(raise_exc=OSError("connection refused"))
        client = _make_client(http)

        import asyncio

        result = asyncio.run(client.get_insider_transactions("AAPL.US"))

        assert result == []
