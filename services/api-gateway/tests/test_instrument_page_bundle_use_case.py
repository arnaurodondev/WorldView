"""Tests for InstrumentPageBundleUseCase (PLAN-0089 Wave B-2).

Verifies that the use case:
  1. Returns the expected bundle shape on the happy path.
  2. Forwards instrument_id to the underlying clients.get_instrument_page_bundle.
  3. Forwards make_headers to prevent JTI replay detection.
  4. Passes static headers through when make_headers is None.
  5. Returns a partial bundle unchanged when some legs fail.
  6. Passes overall_timeout_s through to the underlying function.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api_gateway.application.use_cases.instrument_page_bundle import InstrumentPageBundleUseCase
from api_gateway.clients import ServiceClients

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_UUID = "01900000-0000-7000-8000-000000000002"


def _make_service_clients() -> ServiceClients:
    """Build a ServiceClients dataclass where every field is a MagicMock.

    We don't need real httpx.AsyncClient objects here — the use case delegates
    all HTTP work to clients.get_instrument_page_bundle which is mocked at the
    module level in each test.
    """
    import httpx

    return ServiceClients(
        **{f.name: MagicMock(spec=httpx.AsyncClient) for f in ServiceClients.__dataclass_fields__.values()}
    )


def _make_use_case(service_clients: ServiceClients | None = None) -> InstrumentPageBundleUseCase:
    """Construct an InstrumentPageBundleUseCase with mock dependencies."""
    import httpx
    from api_gateway.config import Settings

    settings = Settings(
        valkey_url="redis://localhost:6379/0",
        oidc_issuer_url="https://example.zitadel.cloud",
        oidc_client_id="client-id",
        oidc_client_secret="secret",
        oidc_audience="client-id",
        internal_jwt_private_key="stub-private-key",
        internal_jwt_public_key="stub-public-key",
    )
    mock_http = MagicMock(spec=httpx.AsyncClient)
    clients = service_clients or _make_service_clients()
    return InstrumentPageBundleUseCase(
        http_client=mock_http,
        settings=settings,
        service_clients=clients,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXPECTED_BUNDLE: dict = {
    "instrument_id": _VALID_UUID,
    "entity_id": _VALID_UUID,
    "overview": {
        "instrument": {"instrument_id": _VALID_UUID, "ticker": "AAPL"},
        "quote": {"price": 172.50, "ticker": "AAPL"},
        "fundamentals": {"market_cap": 2_700_000_000_000.0},
        "ohlcv": {"bars": [{"timestamp": "2026-01-01", "close": 172.50}]},
    },
    "fundamentals": {"sections": {"Highlights": {"MarketCap": 2_700_000_000_000.0}}},
    "technicals": {"RSI": 58.4, "MACD": 0.42},
    "insider": {"transactions": [{"name": "Tim Cook", "shares": -10000}]},
    "top_news": {"articles": [{"title": "Apple reports record earnings"}]},
}

_PARTIAL_BUNDLE: dict = {
    "instrument_id": _VALID_UUID,
    "entity_id": _VALID_UUID,
    "overview": None,  # overview leg failed
    "fundamentals": None,
    "technicals": None,
    "insider": None,
    "top_news": None,
}


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_instrument_page_bundle_happy_path() -> None:
    """execute() returns the bundle dict produced by get_instrument_page_bundle.

    The use case must not alter the shape returned by the underlying function.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        result = await use_case.execute(instrument_id=_VALID_UUID)

    # The use case must delegate to get_instrument_page_bundle exactly once.
    mock_fn.assert_awaited_once()

    # Shape check: all top-level keys must be present.
    assert "instrument_id" in result
    assert "entity_id" in result
    assert "overview" in result
    assert "fundamentals" in result
    assert "technicals" in result
    assert "insider" in result
    assert "top_news" in result

    # Values must pass through unchanged.
    assert result["overview"]["instrument"]["ticker"] == "AAPL"
    assert result["instrument_id"] == _VALID_UUID


@pytest.mark.asyncio
async def test_instrument_page_bundle_instrument_id_forwarded() -> None:
    """execute() forwards instrument_id as a positional arg to get_instrument_page_bundle.

    WHY: the underlying function uses instrument_id in 4 downstream URL paths.
    If the use case drops or mangles it, all phase-2 calls will use the wrong ID.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(instrument_id=_VALID_UUID)

    # instrument_id is the second positional arg after clients.
    call_args = mock_fn.call_args.args
    assert _VALID_UUID in call_args, "instrument_id not forwarded as positional arg"


@pytest.mark.asyncio
async def test_instrument_page_bundle_make_headers_forwarded() -> None:
    """execute() forwards the make_headers factory to get_instrument_page_bundle.

    WHY this matters: get_instrument_page_bundle calls make_headers() once per
    parallel downstream request so each call gets a fresh JWT with a unique JTI.
    If the use case drops the factory, all parallel calls share the same JWT and
    InternalJWTMiddleware raises 'Token replay detected'.
    """
    use_case = _make_use_case()
    header_factory = MagicMock(return_value={"X-Internal-JWT": "stub-token"})

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(instrument_id=_VALID_UUID, make_headers=header_factory)

    call_kwargs = mock_fn.call_args.kwargs
    assert "make_headers" in call_kwargs, "make_headers not forwarded to get_instrument_page_bundle"
    assert call_kwargs["make_headers"] is header_factory


@pytest.mark.asyncio
async def test_instrument_page_bundle_static_headers_forwarded() -> None:
    """execute() forwards the static headers dict when make_headers is None."""
    use_case = _make_use_case()
    static_headers = {"X-Internal-JWT": "static-token"}

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(instrument_id=_VALID_UUID, headers=static_headers)

    call_kwargs = mock_fn.call_args.kwargs
    assert "headers" in call_kwargs
    assert call_kwargs["headers"] is static_headers


@pytest.mark.asyncio
async def test_instrument_page_bundle_partial_bundle_passthrough() -> None:
    """execute() returns a partial bundle (all legs None) unchanged when phase 1 fails.

    The use case must not suppress None sub-resources — the frontend relies on
    null fields to render its own 'not found' / skeleton UIs.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_PARTIAL_BUNDLE),
    ):
        result = await use_case.execute(instrument_id=_VALID_UUID)

    assert result["overview"] is None
    assert result["fundamentals"] is None
    assert result["instrument_id"] == _VALID_UUID


@pytest.mark.asyncio
async def test_instrument_page_bundle_overall_timeout_forwarded() -> None:
    """execute() passes overall_timeout_s through to get_instrument_page_bundle.

    Callers can tighten or loosen the budget; the use case must not override it
    with its own hardcoded default.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.instrument_page_bundle.get_instrument_page_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(instrument_id=_VALID_UUID, overall_timeout_s=8.0)

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("overall_timeout_s") == 8.0
