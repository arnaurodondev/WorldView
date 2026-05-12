"""Tests for PortfolioBundleUseCase (PLAN-0089 Wave B-2).

Verifies that the use case:
  1. Returns the expected bundle shape on the happy path.
  2. Forwards portfolio_id to the underlying clients.get_portfolio_bundle.
  3. Forwards make_headers to prevent JTI replay detection.
  4. Passes static headers through when make_headers is None.
  5. Returns a partial bundle unchanged when some legs fail.
  6. Passes overall_timeout_s through to the underlying function.
  7. Returns a timed-out bundle unchanged (_meta.timed_out=True) on timeout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api_gateway.application.use_cases.portfolio_bundle import PortfolioBundleUseCase
from api_gateway.clients import ServiceClients

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_UUID = "01900000-0000-7000-8000-000000000003"


def _make_service_clients() -> ServiceClients:
    """Build a ServiceClients dataclass where every field is a MagicMock.

    We don't need real httpx.AsyncClient objects here — the use case delegates
    all HTTP work to clients.get_portfolio_bundle which is mocked at the module
    level in each test.
    """
    import httpx

    return ServiceClients(
        **{f.name: MagicMock(spec=httpx.AsyncClient) for f in ServiceClients.__dataclass_fields__.values()}
    )


def _make_use_case(service_clients: ServiceClients | None = None) -> PortfolioBundleUseCase:
    """Construct a PortfolioBundleUseCase with mock dependencies."""
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
    return PortfolioBundleUseCase(
        http_client=mock_http,
        settings=settings,
        service_clients=clients,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXPECTED_BUNDLE: dict = {
    "portfolio_id": _VALID_UUID,
    "portfolio": {
        "portfolio_id": _VALID_UUID,
        "name": "My Portfolio",
        "currency": "USD",
        "total_value": 125_000.0,
    },
    "holdings": [
        {"instrument_id": "01900000-0000-7000-8000-000000000010", "ticker": "AAPL", "quantity": 100.0},
        {"instrument_id": "01900000-0000-7000-8000-000000000011", "ticker": "MSFT", "quantity": 50.0},
    ],
    "transactions": [
        {"transaction_id": "tx-001", "type": "BUY", "ticker": "AAPL", "shares": 10},
    ],
    "value_history": {
        "period": "1Y",
        "data_points": [{"date": "2025-05-12", "value": 110_000.0}],
    },
    "_meta": {"partial": False, "legs_failed": 0},
}

_PARTIAL_BUNDLE: dict = {
    "portfolio_id": _VALID_UUID,
    "portfolio": {"portfolio_id": _VALID_UUID, "name": "My Portfolio"},
    "holdings": None,  # holdings leg failed
    "transactions": None,  # transactions leg failed
    "value_history": None,  # value_history leg failed
    "_meta": {"partial": True, "legs_failed": 3},
}

_TIMEOUT_BUNDLE: dict = {
    "portfolio_id": _VALID_UUID,
    "portfolio": None,
    "holdings": None,
    "transactions": None,
    "value_history": None,
    "_meta": {"partial": True, "legs_failed": 4, "timed_out": True},
}


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolio_bundle_happy_path() -> None:
    """execute() returns the bundle dict produced by get_portfolio_bundle.

    The use case must not alter the shape returned by the underlying function.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        result = await use_case.execute(portfolio_id=_VALID_UUID)

    # The use case must delegate to get_portfolio_bundle exactly once.
    mock_fn.assert_awaited_once()

    # Shape check: all top-level keys must be present.
    assert "portfolio_id" in result
    assert "portfolio" in result
    assert "holdings" in result
    assert "transactions" in result
    assert "value_history" in result
    assert "_meta" in result

    # Values must pass through unchanged.
    assert result["portfolio"]["name"] == "My Portfolio"
    assert result["_meta"]["partial"] is False
    assert len(result["holdings"]) == 2


@pytest.mark.asyncio
async def test_portfolio_bundle_portfolio_id_forwarded() -> None:
    """execute() forwards portfolio_id as a positional arg to get_portfolio_bundle.

    WHY: the underlying function uses portfolio_id in 4 downstream URL paths.
    If the use case drops or mangles it, all 4 calls will use the wrong ID.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(portfolio_id=_VALID_UUID)

    call_args = mock_fn.call_args.args
    assert _VALID_UUID in call_args, "portfolio_id not forwarded as positional arg"


@pytest.mark.asyncio
async def test_portfolio_bundle_make_headers_forwarded() -> None:
    """execute() forwards the make_headers factory to get_portfolio_bundle.

    WHY this matters: get_portfolio_bundle calls make_headers() once per
    parallel downstream request so each call gets a fresh JWT with a unique JTI.
    If the use case drops the factory, all 4 parallel calls share the same JWT and
    InternalJWTMiddleware raises 'Token replay detected'.
    """
    use_case = _make_use_case()
    header_factory = MagicMock(return_value={"X-Internal-JWT": "stub-token"})

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(portfolio_id=_VALID_UUID, make_headers=header_factory)

    call_kwargs = mock_fn.call_args.kwargs
    assert "make_headers" in call_kwargs, "make_headers not forwarded to get_portfolio_bundle"
    assert call_kwargs["make_headers"] is header_factory


@pytest.mark.asyncio
async def test_portfolio_bundle_static_headers_forwarded() -> None:
    """execute() forwards the static headers dict when make_headers is None."""
    use_case = _make_use_case()
    static_headers = {"X-Internal-JWT": "static-token"}

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(portfolio_id=_VALID_UUID, headers=static_headers)

    call_kwargs = mock_fn.call_args.kwargs
    assert "headers" in call_kwargs
    assert call_kwargs["headers"] is static_headers


@pytest.mark.asyncio
async def test_portfolio_bundle_partial_bundle_passthrough() -> None:
    """execute() returns a partial bundle unchanged when some legs fail.

    The frontend relies on _meta.partial to decide which widgets to show a
    skeleton for.  The use case must not suppress partial=True or None sub-fields.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_PARTIAL_BUNDLE),
    ):
        result = await use_case.execute(portfolio_id=_VALID_UUID)

    assert result["_meta"]["partial"] is True
    assert result["_meta"]["legs_failed"] == 3
    assert result["holdings"] is None
    assert result["portfolio"]["name"] == "My Portfolio"


@pytest.mark.asyncio
async def test_portfolio_bundle_timeout_bundle_passthrough() -> None:
    """execute() returns a timed-out bundle (_meta.timed_out=True) unchanged.

    get_portfolio_bundle catches TimeoutError internally and returns a minimal
    bundle rather than raising.  The use case must not alter that behaviour.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_TIMEOUT_BUNDLE),
    ):
        result = await use_case.execute(portfolio_id=_VALID_UUID)

    assert result["_meta"].get("timed_out") is True
    assert result["portfolio"] is None
    assert result["value_history"] is None


@pytest.mark.asyncio
async def test_portfolio_bundle_overall_timeout_forwarded() -> None:
    """execute() passes overall_timeout_s through to get_portfolio_bundle.

    Callers can tighten or loosen the budget; the use case must not override it
    with its own hardcoded default.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.portfolio_bundle.get_portfolio_bundle",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(portfolio_id=_VALID_UUID, overall_timeout_s=10.0)

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("overall_timeout_s") == 10.0
