"""Tests for EODHDProviderAdapter (T-MI-19). ≥10 test functions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderRateLimited,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
)
from market_ingestion.infrastructure.adapters.providers.eodhd import (
    EODHDProviderAdapter,
    _build_ticker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, content: bytes = b"[]") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    return r


def _make_adapter(
    status_code: int = 200,
    content: bytes = b"[]",
    base_url: str = "https://eodhd.com/api",
) -> tuple[EODHDProviderAdapter, MagicMock]:
    """Return (adapter, mock_client) with a pre-configured GET response."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(status_code, content))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client, base_url=base_url)
    return adapter, client


_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 3, 1, tzinfo=UTC)

# ---------------------------------------------------------------------------
# _build_ticker (module-level helper)
# ---------------------------------------------------------------------------


def test_build_ticker_without_exchange():
    assert _build_ticker("AAPL", None) == "AAPL"


def test_build_ticker_with_exchange():
    assert _build_ticker("AAPL", "US") == "AAPL.US"


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        # EODHD encodes US share classes with a hyphen: BRK.B -> BRK-B.US.
        # A second dot (BRK.B.US) would trigger HTTP 422.
        ("BRK.B", "US", "BRK-B.US"),
        ("BF.B", "US", "BF-B.US"),
        # Plain tickers are unaffected.
        ("AAPL", "US", "AAPL.US"),
    ],
)
def test_build_ticker_dot_class_translated_to_hyphen(symbol, exchange, expected):
    assert _build_ticker(symbol, exchange) == expected


# ---------------------------------------------------------------------------
# fetch_ohlcv
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_result():
    adapter, _ = _make_adapter(content=b'[{"date":"2024-01-02"}]')

    result = await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    assert result.provider == Provider.EODHD
    assert result.dataset_type == DatasetType.OHLCV
    assert result.symbol == "AAPL"
    assert result.content_type == "application/json"
    assert b"2024-01-02" in result.raw_data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_ticker_includes_exchange():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END, exchange="US")

    call_kwargs = client.get.call_args
    url = call_kwargs[0][0]
    assert "AAPL.US" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_date_range_in_params():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1d", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["from"] == "2024-01-01"
    assert params["to"] == "2024-03-01"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_timeframe_mapped_to_d():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1d", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["period"] == "d"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_weekly_timeframe_mapped():
    adapter, client = _make_adapter()

    await adapter.fetch_ohlcv("MSFT", "1w", _START, _END)

    params = client.get.call_args[1]["params"]
    assert params["period"] == "w"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_401_raises_auth_error():
    adapter, _ = _make_adapter(status_code=401)

    with pytest.raises(ProviderAuthError):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_403_raises_auth_error():
    adapter, _ = _make_adapter(status_code=403)

    with pytest.raises(ProviderAuthError):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_429_raises_rate_limited():
    adapter, _ = _make_adapter(status_code=429)

    with pytest.raises(ProviderRateLimited):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_500_raises_unavailable():
    adapter, _ = _make_adapter(status_code=500)

    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_503_raises_unavailable():
    adapter, _ = _make_adapter(status_code=503)

    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_ohlcv_404_raises_unsupported_symbol():
    """PLAN-0052 platform-QA round 4: 404 from EODHD now raises
    ``ProviderUnsupportedSymbol`` (not ``ProviderDataError``) so the
    caller can dead-letter without polluting the fatal-error metric.
    A symbol the provider doesn't support is structurally different
    from a malformed-data response — both are non-retryable, but the
    metric impact differs."""
    adapter, _ = _make_adapter(status_code=404)

    with pytest.raises(ProviderUnsupportedSymbol):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_error_raises_unavailable():
    client = MagicMock()
    client.get = AsyncMock(side_effect=OSError("connection refused"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    with pytest.raises(ProviderUnavailable, match="connection error"):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connection_error_log_redacts_api_token(monkeypatch):
    """The ``eodhd_connection_error`` warning must not leak the api_token.

    ``error=str(exc)`` is a structlog FIELD (not scrubbed by the log handler's
    SecretRedactingFilter), and some httpx transport errors embed the full
    request URL — so the adapter must redact it at the call site. Token below
    is an obviously-fake, EODHD-shaped placeholder, never a live key.
    """
    fake_token = "demo0000000000.00000000"  # noqa: S105  # pragma: allowlist-secret (synthetic test token)
    leaky = OSError(f"connect fail: https://eodhd.com/api/eod/AAPL.US?api_token={fake_token}&fmt=json")
    client = MagicMock()
    client.get = AsyncMock(side_effect=leaky)
    adapter = EODHDProviderAdapter(api_key=fake_token, client=client)

    captured: dict[str, object] = {}

    def _fake_warning(event: str, **kw: object) -> None:
        captured["event"] = event
        captured.update(kw)

    monkeypatch.setattr(
        "market_ingestion.infrastructure.adapters.providers.eodhd.logger.warning",
        _fake_warning,
    )

    with pytest.raises(ProviderUnavailable):
        await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    logged_error = str(captured.get("error", ""))
    assert fake_token not in logged_error, f"api_token LEAKED into log field: {logged_error!r}"
    assert "api_token=***REDACTED-0000" in logged_error
    # The real request still carried the unredacted token in its query params.
    assert client.get.call_args.kwargs["params"]["api_token"] == fake_token


# ---------------------------------------------------------------------------
# fetch_quotes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_quotes_happy_path():
    adapter, client = _make_adapter(content=b'{"bid":1.0,"ask":1.01}')

    result = await adapter.fetch_quotes("AAPL", exchange="US")

    assert result.provider == Provider.EODHD
    assert result.dataset_type == DatasetType.QUOTES
    assert result.symbol == "AAPL"
    url = client.get.call_args[0][0]
    assert "real-time" in url
    assert "AAPL.US" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_quotes_no_exchange():
    adapter, client = _make_adapter()

    await adapter.fetch_quotes("TSLA")

    url = client.get.call_args[0][0]
    assert "TSLA" in url
    assert "." not in url.split("/")[-1]


# ---------------------------------------------------------------------------
# fetch_fundamentals
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_fundamentals_annual_variant():
    adapter, client = _make_adapter(content=b'{"General":{}}')

    result = await adapter.fetch_fundamentals("AAPL", variant="annual")

    # Full response is fetched (no section filter) — variant is preserved in metadata only.
    params = client.get.call_args[1]["params"]
    assert "filter" not in params
    assert result.dataset_type == DatasetType.FUNDAMENTALS
    assert result.provider_metadata == {"variant": "annual"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_fundamentals_quarterly_variant():
    adapter, client = _make_adapter(content=b'{"General":{}}')

    result = await adapter.fetch_fundamentals("AAPL", variant="quarterly")

    # Full response is fetched regardless of variant.
    params = client.get.call_args[1]["params"]
    assert "filter" not in params
    assert result.provider_metadata == {"variant": "quarterly"}


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_true_on_200():
    adapter, _ = _make_adapter(content=b"[]")

    assert await adapter.health_check() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_auth_error():
    adapter, _ = _make_adapter(status_code=401)

    assert await adapter.health_check() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_unavailable():
    adapter, _ = _make_adapter(status_code=503)

    assert await adapter.health_check() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check_returns_false_on_network_error():
    client = MagicMock()
    client.get = AsyncMock(side_effect=OSError("timeout"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    assert await adapter.health_check() is False


# ---------------------------------------------------------------------------
# base_url injection (T-B-1-01)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eodhd_adapter_custom_base_url():
    """Adapter uses the injected base_url for all HTTP calls."""
    adapter, client = _make_adapter(base_url="https://staging.eodhd.example.com/api")

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    url: str = client.get.call_args[0][0]
    assert url.startswith("https://staging.eodhd.example.com/api"), url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eodhd_adapter_default_base_url():
    """Adapter defaults to the production EODHD base URL when none is provided."""
    client = MagicMock()
    client.get = AsyncMock(return_value=_make_response(200, b"[]"))
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    await adapter.fetch_ohlcv("AAPL", "1d", _START, _END)

    url: str = client.get.call_args[0][0]
    assert url.startswith("https://eodhd.com/api"), url


# ---------------------------------------------------------------------------
# fetch_bulk_eod — authoritative daily source (DAILY-VOLUME CORRECTION 2026-07-16)
# ---------------------------------------------------------------------------

# One representative record per the live-verified bulk response shape. The two
# fields that matter — ``volume`` (correct consolidated tape) and
# ``adjusted_close`` — are present; Alpaca's IEX daily feed gets both wrong.
_BULK_SAMPLE = (
    b'[{"code":"AAPL","exchange_short_name":"US","date":"2026-07-16","open":328.0,'
    b'"high":334.68,"low":326.79,"close":333.26,"adjusted_close":333.26,'
    b'"volume":62673782,"prev_close":327.5,"change":5.76,"change_p":1.7588},'
    b'{"code":"MSFT","exchange_short_name":"US","date":"2026-07-16","open":500.0,'
    b'"high":505.0,"low":498.0,"close":503.0,"adjusted_close":503.0,'
    b'"volume":18000000,"prev_close":499.0,"change":4.0,"change_p":0.8}]'
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_bulk_eod_whole_exchange_url_and_provider():
    """A whole-exchange bulk call hits /eod-bulk-last-day/{EXCHANGE} and is tagged EODHD_BULK."""
    adapter, client = _make_adapter(content=_BULK_SAMPLE)

    result = await adapter.fetch_bulk_eod(exchange="US")

    url: str = client.get.call_args[0][0]
    assert url == "https://eodhd.com/api/eod-bulk-last-day/US"
    # No ``symbols`` param on a whole-exchange call → flat-rate bulk.
    params = client.get.call_args.kwargs["params"]
    assert "symbols" not in params
    assert params["fmt"] == "json"
    assert result.provider is Provider.EODHD_BULK
    assert result.dataset_type is DatasetType.OHLCV
    assert result.bars_returned == 2
    assert result.raw_data == _BULK_SAMPLE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_bulk_eod_records_carry_volume_and_adjusted_close():
    """The bulk payload preserves the correct consolidated volume + adjusted_close."""
    import json as _json

    adapter, _ = _make_adapter(content=_BULK_SAMPLE)
    result = await adapter.fetch_bulk_eod(exchange="US")
    records = _json.loads(result.raw_data.decode())
    aapl = next(r for r in records if r["code"] == "AAPL")
    assert aapl["volume"] == 62673782  # consolidated, NOT the ~5% IEX figure
    assert aapl["adjusted_close"] == 333.26  # present (Alpaca stores None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_bulk_eod_date_param_forwarded():
    """A specific --date is forwarded to EODHD for historical bulk pulls."""
    adapter, client = _make_adapter(content=b"[]")
    await adapter.fetch_bulk_eod(exchange="US", date="2026-07-14")
    params = client.get.call_args.kwargs["params"]
    assert params["date"] == "2026-07-14"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_bulk_eod_credit_cost_flat_vs_per_symbol():
    """Whole-exchange = flat 100 credits; a symbols filter is billed per ticker."""
    import structlog.testing

    adapter, _ = _make_adapter(content=_BULK_SAMPLE)
    with structlog.testing.capture_logs() as logs:
        await adapter.fetch_bulk_eod(exchange="US")
    call = next(e for e in logs if e["event"] == "provider_api_call")
    assert call["credit_cost"] == 100

    adapter2, _ = _make_adapter(content=_BULK_SAMPLE)
    with structlog.testing.capture_logs() as logs2:
        await adapter2.fetch_bulk_eod(exchange="US", symbols=["AAPL", "MSFT"])
    call2 = next(e for e in logs2 if e["event"] == "provider_api_call")
    assert call2["credit_cost"] == 2  # 1 credit per named ticker


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_bulk_eod_auth_error_maps_to_domain_error():
    """A 401 from the bulk endpoint raises ProviderAuthError like the other endpoints."""
    adapter, _ = _make_adapter(status_code=401, content=b"Forbidden")
    with pytest.raises(ProviderAuthError):
        await adapter.fetch_bulk_eod(exchange="US")
