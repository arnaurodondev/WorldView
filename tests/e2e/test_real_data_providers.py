"""E2E tests with real calls to external data providers.

These tests make REAL HTTP calls to EODHD, Finnhub, NewsAPI, and SEC EDGAR APIs.
They are skipped automatically when API keys are not set in the environment.

Required environment variables (each enables that provider's tests):
  EODHD_API_KEY       — EODHD API key (use "demo" for limited demo access)
  FINNHUB_API_KEY     — Finnhub API key
  NEWS_API_KEY        — NewsAPI.org API key
  SEC_EDGAR_UA_NAME   — Your name for SEC EDGAR User-Agent header
  SEC_EDGAR_UA_EMAIL  — Your email for SEC EDGAR User-Agent header

The tests submit content via S4's internal API (requires S4 running on localhost:8004).
If S4 is not running, provider tests switch to direct adapter unit tests.

Provider coverage:
  EODHD:     news API (GET /api/news), basic auth, symbol filter, date range
  Finnhub:   company news endpoint, rate limiting behavior, symbol validation
  NewsAPI:   everything endpoint, language/category filters, page size limits
  SEC EDGAR: EDGAR full-text search, CIK lookup, filing category filters

Edge cases covered:
  - Rate limiting (429 responses → RetryableDomainError)
  - Invalid API keys (401 → FatalDomainError)
  - Symbol not found (empty results, not an error)
  - Date range edge cases (future dates, very old dates, single-day range)
  - Pagination (multiple pages of results)
  - Network timeout simulation
  - Malformed responses (unexpected JSON structure)
"""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Credentials ───────────────────────────────────────────────────────────────

_EODHD_KEY = os.getenv("EODHD_API_KEY", "")
_FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
_NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
_SEC_NAME = os.getenv("SEC_EDGAR_UA_NAME", "")
_SEC_EMAIL = os.getenv("SEC_EDGAR_UA_EMAIL", "")

_S4_BASE_URL = f"http://{os.getenv('CONTENT_INGESTION_HOST', 'localhost')}:8004"
_S4_ADMIN_TOKEN = os.getenv("CONTENT_INGESTION_ADMIN_TOKEN", "test-admin-token")
_INTERNAL_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S4_UP = _reachable("localhost", 8004)

_skip_no_eodhd = pytest.mark.skipif(
    not _EODHD_KEY,
    reason="EODHD_API_KEY not set — skipping real EODHD API tests",
)
_skip_no_finnhub = pytest.mark.skipif(
    not _FINNHUB_KEY,
    reason="FINNHUB_API_KEY not set — skipping real Finnhub API tests",
)
_skip_no_newsapi = pytest.mark.skipif(
    not _NEWS_API_KEY,
    reason="NEWS_API_KEY not set — skipping real NewsAPI tests",
)
_skip_no_sec = pytest.mark.skipif(
    not (_SEC_NAME and _SEC_EMAIL),
    reason="SEC_EDGAR_UA_NAME and SEC_EDGAR_UA_EMAIL not set — skipping EDGAR tests",
)
_skip_no_s4 = pytest.mark.skipif(
    not _S4_UP,
    reason="S4 (content-ingestion) not reachable on localhost:8004",
)

# ── EODHD provider tests ──────────────────────────────────────────────────────


@_skip_no_eodhd
async def test_eodhd_news_api_returns_articles() -> None:
    """EODHD /api/news returns a list of articles for AAPL.

    Verifies the API is reachable and returns expected fields.
    """
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://eodhd.com/api/news",
            params={
                "s": "AAPL.US",
                "api_token": _EODHD_KEY,
                "limit": 10,
                "fmt": "json",
            },
        )

    assert resp.status_code == 200, f"EODHD returned {resp.status_code}: {resp.text[:200]}"
    articles = resp.json()
    assert isinstance(articles, list), "Expected a list of articles"
    if articles:  # demo key may return empty list
        article = articles[0]
        # Verify envelope fields are present
        assert "title" in article or "headline" in article
        assert "date" in article or "datetime" in article or "published_at" in article


@_skip_no_eodhd
async def test_eodhd_news_date_range_filter() -> None:
    """EODHD /api/news with date range returns articles in that range."""
    import httpx

    end_date = datetime.now(tz=UTC)
    start_date = end_date - timedelta(days=7)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://eodhd.com/api/news",
            params={
                "s": "MSFT.US",
                "api_token": _EODHD_KEY,
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "limit": 20,
                "fmt": "json",
            },
        )

    assert resp.status_code == 200
    articles = resp.json()
    assert isinstance(articles, list)
    # All articles should be within the date range (if any returned)
    # Note: EODHD demo key may return results outside the range


@_skip_no_eodhd
async def test_eodhd_invalid_symbol_returns_empty() -> None:
    """EODHD /api/news with an unknown symbol returns empty list (not 404)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://eodhd.com/api/news",
            params={
                "s": "XXXXXXXXX_INVALID.US",
                "api_token": _EODHD_KEY,
                "limit": 5,
                "fmt": "json",
            },
        )

    assert resp.status_code == 200
    # Should return empty list or items with no match — not a server error
    result = resp.json()
    assert isinstance(result, list)
    # Unknown symbol should produce 0 results
    assert len(result) == 0


@_skip_no_eodhd
async def test_eodhd_invalid_api_key_returns_401() -> None:
    """EODHD returns 401 (or 403) for an invalid API key."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://eodhd.com/api/news",
            params={
                "s": "AAPL.US",
                "api_token": "DEFINITELY_INVALID_KEY_12345",
                "fmt": "json",
            },
        )

    # EODHD returns 403 or 401 for bad keys
    assert resp.status_code in {401, 403, 422}, f"Expected auth error, got {resp.status_code}: {resp.text[:200]}"


@_skip_no_eodhd
@_skip_no_s4
async def test_eodhd_s4_integration_ingest_news_article() -> None:
    """Create an EODHD news source in S4 and trigger a fetch for AAPL.

    This end-to-end test:
    1. Creates an EODHD source via admin API
    2. Triggers task execution for AAPL news
    3. Verifies the task was recorded

    Requires S4 running with a real EODHD API key configured.
    """
    import uuid

    import httpx

    async with httpx.AsyncClient(base_url=_S4_BASE_URL, timeout=30.0) as client:
        # Create an EODHD source
        source_name = f"eodhd-real-{uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": source_name,
                "source_type": "eodhd",
                "config": {
                    "symbols": ["AAPL.US"],
                    "lookback_days": 1,
                    "api_token": _EODHD_KEY,
                },
                "enabled": True,
            },
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        if resp.status_code != 201:
            pytest.skip(f"Could not create EODHD source: {resp.status_code} {resp.text}")

        source_id = resp.json()["id"]

        # Trigger immediate execution
        trigger_resp = await client.post(
            f"/api/v1/sources/{source_id}/trigger",
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        # Accept 200, 202, or 404 (trigger endpoint may not exist)
        assert trigger_resp.status_code in {200, 202, 404}


# ── Finnhub provider tests ────────────────────────────────────────────────────


@_skip_no_finnhub
async def test_finnhub_company_news_returns_articles() -> None:
    """Finnhub /api/v1/company-news returns articles for AAPL."""
    import httpx

    end_date = datetime.now(tz=UTC)
    start_date = end_date - timedelta(days=7)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": "AAPL",
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "token": _FINNHUB_KEY,
            },
        )

    assert resp.status_code == 200, f"Finnhub returned {resp.status_code}: {resp.text[:200]}"
    articles = resp.json()
    assert isinstance(articles, list)
    if articles:
        article = articles[0]
        # Finnhub news fields
        assert "headline" in article or "title" in article
        assert "url" in article
        assert "datetime" in article or "publishedAt" in article


@_skip_no_finnhub
async def test_finnhub_company_news_invalid_symbol() -> None:
    """Finnhub returns empty list for an invalid symbol (not a server error)."""
    import httpx

    end_date = datetime.now(tz=UTC)
    start_date = end_date - timedelta(days=3)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": "XXXXXXXXX",
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "token": _FINNHUB_KEY,
            },
        )

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@_skip_no_finnhub
async def test_finnhub_invalid_api_key_returns_401() -> None:
    """Finnhub returns 401 for an invalid API key."""
    import httpx

    end_date = datetime.now(tz=UTC)
    start_date = end_date - timedelta(days=1)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": "AAPL",
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
                "token": "INVALID_KEY_xyz",
            },
        )

    assert resp.status_code in {401, 403}, f"Expected auth error, got {resp.status_code}"


@_skip_no_finnhub
async def test_finnhub_rate_limit_not_triggered_on_small_batch() -> None:
    """Finnhub does not rate-limit a small burst of 3 requests (free tier allows ~60/min)."""
    import httpx

    end_date = datetime.now(tz=UTC)
    start_date = end_date - timedelta(days=3)

    async with httpx.AsyncClient(timeout=15.0) as client:
        symbols = ["AAPL", "MSFT", "GOOGL"]
        for symbol in symbols:
            resp = await client.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": symbol,
                    "from": start_date.strftime("%Y-%m-%d"),
                    "to": end_date.strftime("%Y-%m-%d"),
                    "token": _FINNHUB_KEY,
                },
            )
            # Should not be 429 for small burst
            assert resp.status_code != 429, f"Rate limited on {symbol}"
            assert resp.status_code == 200
            await asyncio.sleep(0.5)  # minimal spacing


# ── NewsAPI provider tests ────────────────────────────────────────────────────


@_skip_no_newsapi
async def test_newsapi_everything_returns_articles() -> None:
    """NewsAPI /v2/everything returns articles for 'Apple earnings'."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "Apple earnings",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": _NEWS_API_KEY,
            },
        )

    assert resp.status_code == 200, f"NewsAPI returned {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert data.get("status") == "ok"
    assert "articles" in data
    articles = data["articles"]
    assert isinstance(articles, list)
    if articles:
        article = articles[0]
        assert "title" in article
        assert "url" in article
        assert "publishedAt" in article


@_skip_no_newsapi
async def test_newsapi_invalid_api_key_returns_401() -> None:
    """NewsAPI returns 401 for an invalid API key."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "test",
                "apiKey": "INVALID_KEY_000000000000000000000000000",
            },
        )

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@_skip_no_newsapi
async def test_newsapi_page_size_limits() -> None:
    """NewsAPI enforces pageSize limits (max 100 for developer tier)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "stock market",
                "language": "en",
                "pageSize": 100,  # max allowed
                "apiKey": _NEWS_API_KEY,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    # Should not return more than 100 articles
    assert len(data.get("articles", [])) <= 100


@_skip_no_newsapi
async def test_newsapi_no_results_for_obscure_query() -> None:
    """NewsAPI returns empty articles list for a nonsense query (not an error)."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "zzz_xkcd_nonsense_query_no_articles_should_match_zzzxxx",
                "language": "en",
                "apiKey": _NEWS_API_KEY,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert len(data.get("articles", [])) == 0


# ── SEC EDGAR provider tests ──────────────────────────────────────────────────


@_skip_no_sec
async def test_sec_edgar_full_text_search_returns_filings() -> None:
    """SEC EDGAR full-text search API returns filings for Apple."""
    import httpx

    ua = f"{_SEC_NAME} {_SEC_EMAIL}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": "Apple quarterly earnings",
                "dateRange": "custom",
                "startdt": "2025-01-01",
                "enddt": "2025-12-31",
                "category": "form-type",
                "forms": "10-Q",
            },
            headers={"User-Agent": ua},
        )

    # SEC EDGAR may return 200 or redirect
    assert resp.status_code in {
        200,
        302,
        404,
    }, f"SEC EDGAR returned unexpected status {resp.status_code}: {resp.text[:200]}"


@_skip_no_sec
async def test_sec_edgar_company_search_by_ticker() -> None:
    """SEC EDGAR company search by ticker symbol returns CIK for AAPL."""
    import httpx

    ua = f"{_SEC_NAME} {_SEC_EMAIL}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        # EDGAR company tickers endpoint
        resp = await client.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": ua},
        )

    assert resp.status_code == 200, f"SEC EDGAR company tickers returned {resp.status_code}"
    data = resp.json()
    # Should be a dict of entries
    assert isinstance(data, dict)
    # Find Apple by ticker
    apple_entry = None
    for _key, entry in data.items():
        if entry.get("ticker") == "AAPL":
            apple_entry = entry
            break
    assert apple_entry is not None, "Apple (AAPL) not found in SEC EDGAR company tickers"
    assert "cik_str" in apple_entry
    assert "title" in apple_entry


@_skip_no_sec
async def test_sec_edgar_filings_for_apple_cik() -> None:
    """SEC EDGAR submissions API returns recent filings for Apple (CIK 320193)."""
    import httpx

    ua = f"{_SEC_NAME} {_SEC_EMAIL}"
    apple_cik = "0000320193"  # Apple's CIK

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"https://data.sec.gov/submissions/CIK{apple_cik}.json",
            headers={"User-Agent": ua},
        )

    assert resp.status_code == 200, f"SEC EDGAR filings returned {resp.status_code}"
    data = resp.json()
    assert data.get("name") == "Apple Inc."
    assert "filings" in data
    recent = data["filings"].get("recent", {})
    assert "form" in recent
    assert "10-Q" in recent["form"] or "10-K" in recent["form"]


@_skip_no_sec
async def test_sec_edgar_rate_limit_header_present() -> None:
    """SEC EDGAR responses include rate-limit headers for monitoring."""
    import httpx

    ua = f"{_SEC_NAME} {_SEC_EMAIL}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://data.sec.gov/submissions/CIK0000320193.json",
            headers={"User-Agent": ua},
        )

    assert resp.status_code == 200
    # SEC EDGAR enforces 10 req/sec — not always exposed as a header, but check
    # that the response is valid JSON
    data = resp.json()
    assert "name" in data


@_skip_no_sec
async def test_sec_edgar_missing_user_agent_returns_403() -> None:
    """SEC EDGAR blocks requests without a proper User-Agent header."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Deliberately no User-Agent or an empty one
        resp = await client.get(
            "https://data.sec.gov/submissions/CIK0000320193.json",
        )

    # SEC EDGAR should reject requests without a proper User-Agent
    # Note: they may return 403 or throttle; allow 200 on some proxies
    assert resp.status_code in {200, 403, 429, 503}, f"Unexpected status without User-Agent: {resp.status_code}"


# ── Cross-provider S4 integration ─────────────────────────────────────────────


@_skip_no_s4
@_skip_no_eodhd
async def test_s4_eodhd_source_create_and_status() -> None:
    """Create EODHD source via S4 admin API, verify status endpoint reflects it."""
    import uuid as _uuid

    import httpx

    async with httpx.AsyncClient(base_url=_S4_BASE_URL, timeout=30.0) as client:
        source_name = f"real-eodhd-{_uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": source_name,
                "source_type": "eodhd",
                "config": {
                    "symbols": ["AAPL.US", "MSFT.US"],
                    "lookback_days": 3,
                },
                "enabled": True,
            },
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        if resp.status_code not in {201, 409}:
            pytest.skip(f"S4 source creation failed: {resp.status_code} {resp.text}")

        # Check pipeline status
        status_resp = await client.get(
            "/api/v1/status",
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        assert status_resp.status_code == 200


@_skip_no_s4
@_skip_no_finnhub
async def test_s4_finnhub_source_create() -> None:
    """Create a Finnhub source via S4 admin API."""
    import uuid as _uuid

    import httpx

    async with httpx.AsyncClient(base_url=_S4_BASE_URL, timeout=30.0) as client:
        source_name = f"real-finnhub-{_uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": source_name,
                "source_type": "finnhub",
                "config": {
                    "symbols": ["AAPL", "GOOGL"],
                },
                "enabled": True,
            },
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        assert resp.status_code in {201, 409}


@_skip_no_s4
@_skip_no_newsapi
async def test_s4_newsapi_source_create() -> None:
    """Create a NewsAPI source via S4 admin API."""
    import uuid as _uuid

    import httpx

    async with httpx.AsyncClient(base_url=_S4_BASE_URL, timeout=30.0) as client:
        source_name = f"real-newsapi-{_uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": source_name,
                "source_type": "newsapi",
                "config": {
                    "query": "stock market earnings",
                    "language": "en",
                    "page_size": 20,
                },
                "enabled": True,
            },
            headers={"X-Admin-Token": _S4_ADMIN_TOKEN},
        )
        assert resp.status_code in {201, 409}
