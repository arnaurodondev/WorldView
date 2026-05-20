"""Tests for CompanyOverviewUseCase (PLAN-0089 Wave B-1).

Verifies that the use case:
  1. Returns the expected bundle shape on the happy path.
  2. Propagates DownstreamError from the underlying clients.get_company_overview.
  3. Passes make_headers through to the downstream function unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api_gateway.application.use_cases.company_overview import CompanyOverviewUseCase
from api_gateway.clients import DownstreamError, ServiceClients

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_service_clients() -> ServiceClients:
    """Build a ServiceClients dataclass where every field is a MagicMock.

    We don't need real httpx.AsyncClient objects here — the use case delegates
    all HTTP work to clients.get_company_overview which is mocked at the module
    level in each test.
    """
    import httpx

    return ServiceClients(
        **{f.name: MagicMock(spec=httpx.AsyncClient) for f in ServiceClients.__dataclass_fields__.values()}
    )


def _make_use_case(service_clients: ServiceClients | None = None) -> CompanyOverviewUseCase:
    """Construct a CompanyOverviewUseCase with mock dependencies."""
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
    return CompanyOverviewUseCase(
        http_client=mock_http,
        settings=settings,
        service_clients=clients,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

_VALID_UUID = "01900000-0000-7000-8000-000000000001"
_EXPECTED_BUNDLE = {
    "instrument": {
        "instrument_id": _VALID_UUID,
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "currency": "USD",
        "entity_id": _VALID_UUID,
    },
    "quote": {"price": 172.50, "ticker": "AAPL"},
    "fundamentals": {"market_cap": 2_700_000_000_000.0, "pe_ratio": 28.5},
    "ohlcv": {"bars": [{"timestamp": "2026-01-01", "close": 172.50}]},
}


@pytest.mark.asyncio
async def test_company_overview_happy_path() -> None:
    """execute() returns the bundle dict produced by get_company_overview.

    The use case must not alter the shape returned by the underlying function.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.company_overview.get_company_overview",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        result = await use_case.execute(company_id=_VALID_UUID)

    # The use case must delegate to get_company_overview exactly once.
    mock_fn.assert_awaited_once()

    # Shape check: all four top-level keys must be present.
    assert "instrument" in result
    assert "quote" in result
    assert "fundamentals" in result
    assert "ohlcv" in result

    # Values must pass through unchanged.
    assert result["instrument"]["ticker"] == "AAPL"
    assert result["quote"]["price"] == 172.50


@pytest.mark.asyncio
async def test_company_overview_downstream_error_propagates() -> None:
    """DownstreamError raised by get_company_overview must propagate out of execute().

    The use case must not swallow the error — the route handler catches it and
    converts it to an HTTPException.
    """
    use_case = _make_use_case()
    error = DownstreamError("market-data", 404, "Instrument not found")

    with patch(
        "api_gateway.application.use_cases.company_overview.get_company_overview",
        new=AsyncMock(side_effect=error),
    ):
        with pytest.raises(DownstreamError) as exc_info:
            await use_case.execute(company_id=_VALID_UUID)

    assert exc_info.value.status == 404
    assert exc_info.value.service == "market-data"


@pytest.mark.asyncio
async def test_company_overview_make_headers_forwarded() -> None:
    """execute() forwards the make_headers factory to get_company_overview.

    WHY this matters: get_company_overview calls make_headers() once per
    parallel downstream request so each call gets a fresh JWT with a unique JTI.
    If the use case drops the factory, all parallel calls share the same JWT and
    InternalJWTMiddleware raises 'Token replay detected'.
    """
    use_case = _make_use_case()
    header_factory = MagicMock(return_value={"X-Internal-JWT": "stub-token"})

    with patch(
        "api_gateway.application.use_cases.company_overview.get_company_overview",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(company_id=_VALID_UUID, make_headers=header_factory)

    # Verify make_headers was passed through (not dropped by the use case).
    _call_kwargs = mock_fn.call_args.kwargs
    assert "make_headers" in _call_kwargs, "make_headers not forwarded to get_company_overview"
    assert _call_kwargs["make_headers"] is header_factory
