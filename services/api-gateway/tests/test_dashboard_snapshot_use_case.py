"""Tests for DashboardSnapshotUseCase (PLAN-0089 Wave B-2).

Verifies that the use case:
  1. Returns the expected bundle shape on the happy path.
  2. Forwards make_headers to the underlying clients.get_dashboard_snapshot.
  3. Passes headers through when make_headers is None.
  4. Propagates HTTPException(504) on timeout.
  5. Passes overall_timeout_s through to the underlying function.
  6. Does not alter a partial bundle (_meta.partial=True) returned by the function.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api_gateway.application.use_cases.dashboard_snapshot import DashboardSnapshotUseCase
from api_gateway.clients import ServiceClients

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_service_clients() -> ServiceClients:
    """Build a ServiceClients dataclass where every field is a MagicMock.

    We don't need real httpx.AsyncClient objects here — the use case delegates
    all HTTP work to clients.get_dashboard_snapshot which is mocked at the module
    level in each test.
    """
    import httpx

    return ServiceClients(
        **{f.name: MagicMock(spec=httpx.AsyncClient) for f in ServiceClients.__dataclass_fields__.values()}
    )


def _make_use_case(service_clients: ServiceClients | None = None) -> DashboardSnapshotUseCase:
    """Construct a DashboardSnapshotUseCase with mock dependencies."""
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
    return DashboardSnapshotUseCase(
        http_client=mock_http,
        settings=settings,
        service_clients=clients,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXPECTED_BUNDLE: dict = {
    "news": [{"article_id": "a1", "title": "Markets rally"}],
    "heatmap": {"sectors": [{"name": "Technology", "change_pct": 1.2}]},
    "prediction_markets": [{"market_id": "m1", "question": "Will AAPL hit $200?"}],
    "earnings_calendar": {"events": [{"ticker": "AAPL", "date": "2026-05-14"}]},
    "alerts": [{"alert_id": "al1", "severity": "HIGH", "message": "Price spike"}],
    "morning_brief": {"summary": "Markets opened higher on strong jobs data."},
    "_meta": {"partial": False, "legs_failed": 0},
}

_PARTIAL_BUNDLE: dict = {
    "news": [{"article_id": "a1", "title": "Markets rally"}],
    "heatmap": None,  # heatmap leg failed
    "prediction_markets": None,
    "earnings_calendar": {"events": []},
    "alerts": None,
    "morning_brief": {"summary": "Brief unavailable."},
    "_meta": {"partial": True, "legs_failed": 3},
}


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_snapshot_happy_path() -> None:
    """execute() returns the bundle dict produced by get_dashboard_snapshot.

    The use case must not alter the shape returned by the underlying function.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        result = await use_case.execute()

    # The use case must delegate to get_dashboard_snapshot exactly once.
    mock_fn.assert_awaited_once()

    # Shape check: all top-level keys must be present.
    assert "news" in result
    assert "heatmap" in result
    assert "prediction_markets" in result
    assert "earnings_calendar" in result
    assert "alerts" in result
    assert "morning_brief" in result
    assert "_meta" in result

    # Values must pass through unchanged.
    assert result["news"][0]["title"] == "Markets rally"
    assert result["_meta"]["partial"] is False


@pytest.mark.asyncio
async def test_dashboard_snapshot_make_headers_forwarded() -> None:
    """execute() forwards the make_headers factory to get_dashboard_snapshot.

    WHY this matters: get_dashboard_snapshot calls make_headers() once per
    parallel downstream request so each call gets a fresh JWT with a unique JTI.
    If the use case drops the factory, all 6 parallel calls share the same JWT and
    InternalJWTMiddleware raises 'Token replay detected'.
    """
    use_case = _make_use_case()
    header_factory = MagicMock(return_value={"X-Internal-JWT": "stub-token"})

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(make_headers=header_factory)

    # Verify make_headers was passed through (not dropped by the use case).
    call_kwargs = mock_fn.call_args.kwargs
    assert "make_headers" in call_kwargs, "make_headers not forwarded to get_dashboard_snapshot"
    assert call_kwargs["make_headers"] is header_factory


@pytest.mark.asyncio
async def test_dashboard_snapshot_static_headers_forwarded() -> None:
    """execute() forwards the static headers dict when make_headers is None.

    WHY: tests and simple callers may pass headers= instead of make_headers=.
    The use case must forward whichever is provided without mixing them up.
    """
    use_case = _make_use_case()
    static_headers = {"X-Internal-JWT": "static-token"}

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(headers=static_headers)

    call_kwargs = mock_fn.call_args.kwargs
    assert "headers" in call_kwargs
    assert call_kwargs["headers"] is static_headers


@pytest.mark.asyncio
async def test_dashboard_snapshot_partial_bundle_passthrough() -> None:
    """execute() returns a partial bundle unchanged when some legs fail.

    The use case must not suppress partial=True bundles — the frontend relies on
    _meta.partial to decide which widgets to show a skeleton for.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(return_value=_PARTIAL_BUNDLE),
    ):
        result = await use_case.execute()

    assert result["_meta"]["partial"] is True
    assert result["_meta"]["legs_failed"] == 3
    assert result["heatmap"] is None
    assert result["news"] is not None


@pytest.mark.asyncio
async def test_dashboard_snapshot_overall_timeout_forwarded() -> None:
    """execute() passes overall_timeout_s through to get_dashboard_snapshot.

    Callers can tighten or loosen the budget; the use case must not override it
    with its own hardcoded default.
    """
    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(return_value=_EXPECTED_BUNDLE),
    ) as mock_fn:
        await use_case.execute(overall_timeout_s=5.0)

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("overall_timeout_s") == 5.0


@pytest.mark.asyncio
async def test_dashboard_snapshot_timeout_exception_propagates() -> None:
    """HTTPException(504) raised by get_dashboard_snapshot propagates out of execute().

    The use case must not swallow the exception — the route handler (or FastAPI)
    will convert it to a 504 response for the client.
    """
    from fastapi import HTTPException

    use_case = _make_use_case()

    with patch(
        "api_gateway.application.use_cases.dashboard_snapshot.get_dashboard_snapshot",
        new=AsyncMock(side_effect=HTTPException(status_code=504, detail="Dashboard snapshot timeout")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await use_case.execute()

    assert exc_info.value.status_code == 504
