"""Unit tests for Retry-After header parsing and ProviderRateLimited.retry_after.

Covers:
- _parse_retry_after with integer seconds
- _parse_retry_after with HTTP-date format
- _parse_retry_after with invalid/absent header
- ProviderRateLimited carries retry_after attribute
- API key is NOT present in error messages (security: no secret leakage)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.domain.errors import ProviderRateLimited
from market_ingestion.infrastructure.adapters.providers.eodhd import (
    EODHDProviderAdapter,
    _parse_retry_after,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# _parse_retry_after unit tests
# ---------------------------------------------------------------------------


def test_parse_retry_after_integer_seconds() -> None:
    """Integer string is parsed as delta-seconds."""
    result = _parse_retry_after("120")
    assert result == pytest.approx(120.0)


def test_parse_retry_after_float_seconds() -> None:
    """Float string is parsed correctly."""
    result = _parse_retry_after("30.5")
    assert result == pytest.approx(30.5)


def test_parse_retry_after_zero_clamped_to_zero() -> None:
    """Negative values are clamped to 0."""
    result = _parse_retry_after("-5")
    assert result == pytest.approx(0.0)


def test_parse_retry_after_http_date_format() -> None:
    """HTTP-date format is parsed into seconds until that time."""
    # Target 60 seconds in the future
    target = datetime.now(tz=UTC) + timedelta(seconds=60)
    http_date = format_datetime(target, usegmt=True)

    result = _parse_retry_after(http_date)

    # Allow ±5s tolerance for test execution time
    assert result is not None
    assert 55.0 <= result <= 65.0


def test_parse_retry_after_http_date_in_past_clamped_to_zero() -> None:
    """HTTP-date in the past returns 0.0 (not negative)."""
    past = datetime.now(tz=UTC) - timedelta(seconds=120)
    http_date = format_datetime(past, usegmt=True)

    result = _parse_retry_after(http_date)

    assert result is not None
    assert result == pytest.approx(0.0)


def test_parse_retry_after_none_returns_none() -> None:
    """Absent header returns None."""
    assert _parse_retry_after(None) is None


def test_parse_retry_after_invalid_returns_none() -> None:
    """Garbage header value returns None without raising."""
    assert _parse_retry_after("not-a-date-or-number") is None


def test_parse_retry_after_empty_string_returns_none() -> None:
    """Empty string returns None."""
    assert _parse_retry_after("") is None


# ---------------------------------------------------------------------------
# ProviderRateLimited.retry_after attribute
# ---------------------------------------------------------------------------


def test_provider_rate_limited_carries_retry_after() -> None:
    """ProviderRateLimited stores the retry_after value."""
    exc = ProviderRateLimited("rate limited", retry_after=45.0)
    assert exc.retry_after == pytest.approx(45.0)


def test_provider_rate_limited_retry_after_defaults_to_none() -> None:
    """ProviderRateLimited.retry_after is None by default (no header present)."""
    exc = ProviderRateLimited("rate limited")
    assert exc.retry_after is None


def test_provider_rate_limited_is_retryable() -> None:
    """ProviderRateLimited is a retryable error."""
    exc = ProviderRateLimited("rate limited", retry_after=30.0)
    assert exc.is_retryable is True


# ---------------------------------------------------------------------------
# EODHDProviderAdapter: 429 populates retry_after; API key not in message
# ---------------------------------------------------------------------------


def _make_response(status_code: int, headers: dict | None = None, content: bytes = b"") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.headers = headers or {}
    r.content = content
    return r


@pytest.mark.unit
@pytest.mark.asyncio
async def test_429_retry_after_header_sets_retry_after_on_exception() -> None:
    """HTTP 429 with Retry-After: 60 raises ProviderRateLimited(retry_after=60.0)."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(429, headers={"Retry-After": "60"}))
    adapter = EODHDProviderAdapter(api_key="secret-key", client=client)

    with pytest.raises(ProviderRateLimited) as exc_info:
        await adapter.fetch_quotes("AAPL")

    assert exc_info.value.retry_after == pytest.approx(60.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_429_no_retry_after_header_sets_none() -> None:
    """HTTP 429 without Retry-After header raises ProviderRateLimited(retry_after=None)."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(429, headers={}))
    adapter = EODHDProviderAdapter(api_key="secret-key", client=client)

    with pytest.raises(ProviderRateLimited) as exc_info:
        await adapter.fetch_quotes("AAPL")

    assert exc_info.value.retry_after is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_key_not_logged_on_429_error() -> None:
    """The secret API key must NOT appear in the ProviderRateLimited error message."""
    secret_key = "super-secret-api-key-12345"  # noqa: S105
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(429, headers={"Retry-After": "30"}))
    adapter = EODHDProviderAdapter(api_key=secret_key, client=client)

    with pytest.raises(ProviderRateLimited) as exc_info:
        await adapter.fetch_ohlcv("AAPL", "1d")

    assert secret_key not in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_key_not_in_auth_error_message() -> None:
    """The API key must NOT appear in ProviderAuthError messages either."""
    secret_key = "super-secret-api-key-12345"  # noqa: S105
    from market_ingestion.domain.errors import ProviderAuthError

    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(401, headers={}))
    adapter = EODHDProviderAdapter(api_key=secret_key, client=client)

    with pytest.raises(ProviderAuthError) as exc_info:
        await adapter.fetch_quotes("AAPL")

    assert secret_key not in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_429_http_date_retry_after_parsed() -> None:
    """HTTP 429 with HTTP-date Retry-After is parsed correctly."""
    target = datetime.now(tz=UTC) + timedelta(seconds=30)
    from email.utils import format_datetime

    http_date = format_datetime(target, usegmt=True)

    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(429, headers={"Retry-After": http_date}))
    adapter = EODHDProviderAdapter(api_key="key", client=client)

    with pytest.raises(ProviderRateLimited) as exc_info:
        await adapter.fetch_quotes("AAPL")

    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after >= 0.0
