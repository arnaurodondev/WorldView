"""Unit tests for EODHDTickerNewsAdapter (PLAN-0106 Wave C-1).

Tests cover:
  - Happy path: articles are mapped to FetchResult correctly.
  - Watermark: ``from_date`` is sent as ``from`` query param.
  - HTTP 429 → ProviderRateLimited (subclass of AdapterError).
  - Non-2xx (e.g. 500) → AdapterError.
  - Missing symbol/exchange config → empty list + warning, no raise.
  - Article without link → skipped.
  - published_at parsed from EODHD date field.
"""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from content_ingestion.domain.entities import FetchResult
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.eodhd_ticker_news.adapter import (
    EODHDTickerNewsAdapter,
    ProviderRateLimited,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(api_key: str = "test-api-key") -> MagicMock:
    s = MagicMock()
    s.eodhd_api_key = api_key
    return s


def _make_source(symbol: str = "AAPL", exchange: str = "US") -> MagicMock:
    """Create a minimal Source mock with the given config."""
    from uuid import uuid4

    source = MagicMock()
    source.id = uuid4()
    source.name = f"eodhd-ticker-news-{symbol.lower()}-{exchange.lower()}"
    source.config = {"symbol": symbol, "exchange": exchange}
    return source


def _make_article(
    link: str = "https://example.com/article/1",
    title: str = "Test article",
    date: str = "2026-06-05T12:00:00+00:00",
) -> dict:  # type: ignore[type-arg]
    return {"link": link, "title": title, "date": date, "content": "Body text."}


def _make_httpx_response(
    json_data: object,
    status_code: int = 200,
) -> MagicMock:
    """Build a fake httpx.Response mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEODHDTickerNewsAdapterHappyPath:
    async def test_returns_fetch_results_for_each_article(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        articles = [_make_article(link=f"https://example.com/{i}") for i in range(3)]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        assert len(results) == 3
        for r in results:
            assert isinstance(r, FetchResult)
            assert r.source_id == source.id
            assert r.http_status == 200
            assert r.content_type == "application/json"
            assert r.is_backfill is False

    async def test_article_url_hash_is_sha256_of_link(self) -> None:
        import hashlib

        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        link = "https://example.com/unique-article"
        articles = [_make_article(link=link)]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        expected_hash = hashlib.sha256(link.encode()).hexdigest()
        assert results[0].url_hash == expected_hash

    async def test_published_at_parsed_from_date_field(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        articles = [_make_article(date="2026-06-05T12:30:00+00:00")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        assert results[0].published_at is not None
        assert results[0].published_at.year == 2026
        assert results[0].published_at.tzinfo is not None

    async def test_title_propagated(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        articles = [_make_article(title="Apple earnings beat")]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        assert results[0].title == "Apple earnings beat"

    async def test_is_backfill_propagated(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([_make_article()])

            results = await adapter.fetch(source, is_backfill=True)

        assert results[0].is_backfill is True


class TestEODHDTickerNewsAdapterURL:
    """Regression tests for BP-XXX: /api/v1/news vs /api/news URL bug."""

    async def test_request_url_has_no_v1_segment(self) -> None:
        """Requests must go to /api/news, NOT /api/v1/news (returns 404)."""
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source)

        called_url: str = mock_client.get.call_args.args[0]
        assert "/api/v1/" not in called_url, f"URL must not contain /api/v1/ — got {called_url!r}"
        assert called_url == "https://eodhd.com/api/news", f"Expected 'https://eodhd.com/api/news', got {called_url!r}"

    async def test_request_url_correct_path(self) -> None:
        """Exact URL sent to httpx is https://eodhd.com/api/news."""
        from content_ingestion.infrastructure.adapters.eodhd_ticker_news import adapter as adapter_module

        assert adapter_module._EODHD_TICKER_NEWS_BASE_URL == "https://eodhd.com/api/news", (
            "Module constant _EODHD_TICKER_NEWS_BASE_URL must be 'https://eodhd.com/api/news' — "
            "'/api/v1/news' is a non-existent EODHD endpoint that returns HTTP 404"
        )


class TestEODHDTickerNewsAdapterWatermark:
    async def test_from_date_sent_as_from_param(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source, from_date="2026-01-01")

        # params is passed as a kwarg in httpx client.get(url, params=...)
        actual_params = mock_client.get.call_args.kwargs.get("params") or {}
        assert actual_params.get("from") == "2026-01-01"

    async def test_no_from_param_when_no_watermark(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source)  # no from_date

        actual_params = mock_client.get.call_args.kwargs.get("params") or {}
        assert "from" not in actual_params

    async def test_symbol_exchange_in_s_param(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source(symbol="MSFT", exchange="US")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source)

        actual_params = mock_client.get.call_args.kwargs.get("params") or {}
        assert actual_params["s"] == "MSFT.US"

    async def test_dot_class_symbol_translated_to_hyphen(self) -> None:
        # EODHD encodes US share classes with a hyphen: a stored dot-class
        # symbol BRK.B must become BRK-B.US, not BRK.B.US (the latter -> HTTP 422).
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source(symbol="BRK.B", exchange="US")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source)

        actual_params = mock_client.get.call_args.kwargs.get("params") or {}
        assert actual_params["s"] == "BRK-B.US"

    async def test_plain_symbol_s_param_unchanged(self) -> None:
        # Symbols without a dot class are passed through verbatim.
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source(symbol="AAPL", exchange="US")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            await adapter.fetch(source)

        actual_params = mock_client.get.call_args.kwargs.get("params") or {}
        assert actual_params["s"] == "AAPL.US"


class TestEODHDTickerNewsAdapterErrors:
    async def test_http_429_raises_provider_rate_limited(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([], status_code=429)

            with pytest.raises(ProviderRateLimited):
                await adapter.fetch(source)

    async def test_http_429_is_subclass_of_adapter_error(self) -> None:
        """ProviderRateLimited must be catchable as AdapterError."""
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([], status_code=429)

            with pytest.raises(AdapterError):
                await adapter.fetch(source)

    async def test_http_500_raises_adapter_error(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([], status_code=500)

            with pytest.raises(AdapterError):
                await adapter.fetch(source)

    async def test_http_error_raises_adapter_error(self) -> None:
        """Network errors (ConnectionError, etc.) are wrapped in AdapterError."""
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("refused")

            with pytest.raises(AdapterError):
                await adapter.fetch(source)


class TestEODHDTickerNewsAdapterEdgeCases:
    async def test_missing_symbol_returns_empty(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        source.config = {"exchange": "US"}  # symbol missing

        with patch("content_ingestion.infrastructure.adapters.eodhd_ticker_news.adapter.logger") as mock_logger:
            results = await adapter.fetch(source)

        assert results == []
        mock_logger.warning.assert_called_once()

    async def test_missing_exchange_returns_empty(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        source.config = {"symbol": "AAPL"}  # exchange missing

        with patch("content_ingestion.infrastructure.adapters.eodhd_ticker_news.adapter.logger") as mock_logger:
            results = await adapter.fetch(source)

        assert results == []
        mock_logger.warning.assert_called_once()

    async def test_article_without_link_is_skipped(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        articles = [
            {"title": "No link article", "date": "2026-01-01"},  # no link
            _make_article(link="https://example.com/valid"),
        ]

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        assert len(results) == 1
        assert results[0].url == "https://example.com/valid"

    async def test_empty_article_list_returns_empty(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([])

            results = await adapter.fetch(source)

        assert results == []

    async def test_non_list_response_returns_empty(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response({"error": "no data"})

            results = await adapter.fetch(source)

        assert results == []

    async def test_published_at_none_when_date_absent(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        article = {"link": "https://example.com/no-date", "title": "No date"}  # no date

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response([article])

            results = await adapter.fetch(source)

        assert results[0].published_at is None

    async def test_naive_datetime_made_utc_aware(self) -> None:
        adapter = EODHDTickerNewsAdapter(settings=_make_settings())
        source = _make_source()
        articles = [_make_article(date="2026-06-05T12:00:00")]  # no tz info

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _make_httpx_response(articles)

            results = await adapter.fetch(source)

        assert results[0].published_at is not None
        assert results[0].published_at.tzinfo == UTC
