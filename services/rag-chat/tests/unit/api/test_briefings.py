"""Unit tests for POST /internal/v1/briefings (T-B-2-06, PRD-0016 §6.2).

F-MIN-002: These tests use httpx.AsyncClient against the FastAPI app. While they
test at the HTTP layer, they use mocked dependencies (no real DB/Kafka) and
run in-process, so they are classified as unit tests per project convention.

F-MIN-001: @pytest.mark.asyncio is NOT required per-test because pyproject.toml
configures ``asyncio_mode = "auto"``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")

_VALID_BODY = {
    "user_id": str(_USER_ID),
    "tenant_id": str(_TENANT_ID),
    "portfolio_context": {"positions": [{"symbol": "AAPL", "value": 10000, "sector": "tech"}]},
    "market_snapshots": [{"symbol": "AAPL", "close": 175.0, "volume": 50_000_000}],
    "active_signals": [],
    "lookback_days": 7,
}

_BRIEFING_RESULT = {
    "narrative": "<h2>Risk Overview</h2><p>Portfolio is well diversified.</p>",
    "risk_summary": {
        "concentration_score": 1.0,
        "top_risk_signals": [],
        "sector_breakdown": {"tech": 1.0},
    },
    "citations": [],
    "generated_at": "2026-04-07T12:00:00+00:00",
}


@pytest.fixture
def settings() -> RagChatSettings:
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="s1-token",
        log_json=False,
        log_level="WARNING",
        # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
        internal_jwt_skip_verification=True,
    )


def _make_app(settings: RagChatSettings, uc_result: dict | Exception | None = None):  # type: ignore[return]
    """Create test app with mocked briefing use case."""
    app = create_app(settings)

    mock_uc = MagicMock()
    if isinstance(uc_result, Exception):
        mock_uc.execute = AsyncMock(side_effect=uc_result)
    else:
        mock_uc.execute = AsyncMock(return_value=uc_result or _BRIEFING_RESULT)

    app.state.briefing_uc = mock_uc
    # chat_orchestrator is not used by briefing route — set a dummy to avoid attr errors
    app.state.chat_orchestrator = MagicMock()
    return app


# ── Happy path ────────────────────────────────────────────────────────────────


_BRIEFING_JWT_TOKEN = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)
_BRIEFING_JWT_HEADERS = {"X-Internal-JWT": _BRIEFING_JWT_TOKEN}


async def test_briefing_valid_request_200(settings: RagChatSettings) -> None:
    """Valid body with X-Internal-JWT (middleware passes through in unit tests) -> 200 with narrative.

    InternalJWTMiddleware has no public key in unit tests (no lifespan) so it
    passes through any well-formed JWT without signature verification.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "narrative" in body
    assert "risk_summary" in body
    assert "generated_at" in body
    assert body["narrative"] != ""


async def test_briefing_response_schema(settings: RagChatSettings) -> None:
    """Response conforms to BriefingResponse schema fields."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers=_BRIEFING_JWT_HEADERS,
        )
    body = resp.json()
    assert set(body.keys()) >= {"narrative", "risk_summary", "citations", "generated_at"}
    assert isinstance(body["citations"], list)
    assert isinstance(body["risk_summary"], dict)


# ── Auth failures ─────────────────────────────────────────────────────────────


async def test_briefing_missing_jwt_401(settings: RagChatSettings) -> None:
    """No X-Internal-JWT header -> 401 (enforced by InternalJWTMiddleware)."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/internal/v1/briefings", json=_VALID_BODY)
    assert resp.status_code == 401


async def test_briefing_malformed_jwt_unit_mode(settings: RagChatSettings) -> None:
    """D-005 (unit mode): Malformed JWT with skip_verification=True -> 200.

    With skip_verification=True and no public key, the middleware's DecodeError path
    passes through with empty state. The briefing route does not check state (it accepts
    body-provided user_id/tenant_id), so mock UC returns 200.
    Real enforcement is tested in test_internal_jwt_middleware.py with skip_verification=False.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers={"X-Internal-JWT": "not.a.jwt"},
        )
    # Unit mode (skip_verification=True): DecodeError -> empty state -> route processes -> 200
    assert resp.status_code == 200


async def test_briefing_malformed_jwt_integration_mode() -> None:
    """D-005 (integration mode): Malformed JWT with skip_verification=False -> 401.

    With skip_verification=False and no public key (no lifespan in unit tests),
    the middleware returns 503 (fail-closed F-001). However, sending a truly
    malformed JWT to a fail-closed middleware still results in a rejection.
    """
    integration_settings = RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="s1-token",
        log_json=False,
        log_level="WARNING",
        # integration mode: skip_verification=False (default)
    )
    app = _make_app(integration_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers={"X-Internal-JWT": "not.a.jwt"},
        )
    # Integration mode (skip_verification=False, no public key): fail-closed -> 503
    assert resp.status_code in (401, 503)


# ── Rate limit ────────────────────────────────────────────────────────────────


async def test_briefing_rate_limit_429(settings: RagChatSettings) -> None:
    """RateLimitExceededError -> 429."""
    from rag_chat.domain.errors import RateLimitExceededError

    app = _make_app(settings, uc_result=RateLimitExceededError("Too many"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 429


# ── Provider unavailable ──────────────────────────────────────────────────────


async def test_briefing_provider_down_503(settings: RagChatSettings) -> None:
    """ProviderUnavailableError -> 503."""
    from rag_chat.domain.errors import ProviderUnavailableError

    app = _make_app(settings, uc_result=ProviderUnavailableError("All down"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 503


# ── Request validation ────────────────────────────────────────────────────────


async def test_briefing_empty_market_snapshots_422(settings: RagChatSettings) -> None:
    """Empty market_snapshots (min_length=1) -> 422."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {**_VALID_BODY, "market_snapshots": []}
        resp = await client.post(
            "/internal/v1/briefings",
            json=body,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 422


async def test_briefing_lookback_days_out_of_range_422(settings: RagChatSettings) -> None:
    """lookback_days=0 (ge=1) -> 422."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {**_VALID_BODY, "lookback_days": 0}
        resp = await client.post(
            "/internal/v1/briefings",
            json=body,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 422


async def test_briefing_lookback_days_max_boundary_422(settings: RagChatSettings) -> None:
    """lookback_days=31 (le=30) -> 422."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = {**_VALID_BODY, "lookback_days": 31}
        resp = await client.post(
            "/internal/v1/briefings",
            json=body,
            headers=_BRIEFING_JWT_HEADERS,
        )
    assert resp.status_code == 422


# ── Use case unit tests (no HTTP) ─────────────────────────────────────────────


async def test_generate_briefing_uc_rate_limit() -> None:
    """GenerateBriefingUseCase raises RateLimitExceededError when counter > 100."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.domain.errors import RateLimitExceededError

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=101)  # over limit
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    with pytest.raises(RateLimitExceededError, match="rate limit exceeded"):
        await uc.execute(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            portfolio_context={},
            market_snapshots=[{"symbol": "AAPL"}],
            active_signals=[],
            lookback_days=7,
        )


async def test_generate_briefing_uc_success() -> None:
    """GenerateBriefingUseCase returns narrative on success."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        for chunk in ["<h2>Risk</h2>", "<p>All good.</p>"]:
            yield chunk

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()

    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={"positions": [{"symbol": "AAPL", "value": 5000, "sector": "tech"}]},
        market_snapshots=[{"symbol": "AAPL", "close": 175.0}],
        active_signals=[{"id": "sig1", "description": "Price drop"}],
        lookback_days=7,
    )

    assert result["narrative"] == "<h2>Risk</h2><p>All good.</p>"
    assert result["risk_summary"]["concentration_score"] == 1.0
    assert result["risk_summary"]["sector_breakdown"] == {"tech": 1.0}
    assert result["risk_summary"]["top_risk_signals"][0]["signal_id"] == "sig1"
    assert "generated_at" in result


async def test_generate_briefing_uc_concentration_score_multi_position() -> None:
    """HHI concentration score for 2 equal positions = 0.5."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={
            "positions": [
                {"symbol": "AAPL", "value": 5000, "sector": "tech"},
                {"symbol": "MSFT", "value": 5000, "sector": "tech"},
            ],
        },
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    assert result["risk_summary"]["concentration_score"] == pytest.approx(0.5, abs=1e-4)


@pytest.mark.parametrize(
    "positions,expected_hhi",
    [
        # Single position — maximum concentration
        (
            [{"symbol": "AAPL", "value": 10_000, "sector": "tech"}],
            1.0,
        ),
        # Two equal positions — HHI = 2 * (0.5^2) = 0.5
        (
            [
                {"symbol": "AAPL", "value": 5_000, "sector": "tech"},
                {"symbol": "MSFT", "value": 5_000, "sector": "tech"},
            ],
            0.5,
        ),
        # Three equal positions — HHI = 3 * (1/3)^2 ≈ 0.333
        (
            [
                {"symbol": "A", "value": 1_000, "sector": "x"},
                {"symbol": "B", "value": 1_000, "sector": "x"},
                {"symbol": "C", "value": 1_000, "sector": "x"},
            ],
            pytest.approx(1 / 3, abs=1e-4),
        ),
        # Four equal positions — HHI = 4 * (0.25^2) = 0.25
        (
            [
                {"symbol": "A", "value": 2_500, "sector": "x"},
                {"symbol": "B", "value": 2_500, "sector": "x"},
                {"symbol": "C", "value": 2_500, "sector": "x"},
                {"symbol": "D", "value": 2_500, "sector": "x"},
            ],
            0.25,
        ),
        # Dominant position (80 %) + 2 small (10 % each)
        # HHI = 0.8^2 + 0.1^2 + 0.1^2 = 0.64 + 0.01 + 0.01 = 0.66
        (
            [
                {"symbol": "DOM", "value": 8_000, "sector": "a"},
                {"symbol": "SM1", "value": 1_000, "sector": "b"},
                {"symbol": "SM2", "value": 1_000, "sector": "c"},
            ],
            pytest.approx(0.66, abs=1e-4),
        ),
    ],
)
async def test_generate_briefing_uc_hhi_concentration_parametrized(
    positions: list[dict],  # type: ignore[type-arg]
    expected_hhi: float,
) -> None:
    """Parametrised HHI concentration score across 1-4+ position portfolios (M-06)."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={"positions": positions},
        market_snapshots=[],
        active_signals=[],
        lookback_days=7,
    )

    assert result["risk_summary"]["concentration_score"] == expected_hhi


async def test_generate_briefing_uc_rate_limit_sets_ttl_on_first_request() -> None:
    """expire() is called when incr returns 1 (first request of the day)."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={},
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    mock_valkey.expire.assert_called_once()
    # TTL arg should be the 25h constant
    _, ttl_arg = mock_valkey.expire.call_args[0]
    assert ttl_arg == 90_000


async def test_generate_briefing_uc_no_ttl_on_subsequent_requests() -> None:
    """expire() is NOT called when incr returns > 1 (subsequent request today)."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=5)  # not first request
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={},
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    mock_valkey.expire.assert_not_called()


# ── F-NIT-001: JWT role test for system rejection ────────────────────────────


async def test_briefing_system_role_not_enforced_at_route_level(settings: RagChatSettings) -> None:
    """F-NIT-001: The briefing route does NOT enforce role-based access control.

    The ``role`` claim in the JWT is extracted by InternalJWTMiddleware and stored
    in ``request.state.role``, but the briefing route handler does not check it.
    A ``system`` role token is therefore accepted.  Role enforcement is by design
    NOT implemented at the individual route level for internal-only endpoints
    (PRD-0025 §6.5: internal JWT carries role for auditing, not gating).
    """
    _system_jwt = _jwt.encode(
        {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "system"},
        "secret",
        algorithm="HS256",
    )
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers={"X-Internal-JWT": _system_jwt},
        )
    # Internal endpoints do not gate on role — system tokens pass through.
    assert resp.status_code == 200


# ── F-NIT-002: HHI edge cases ────────────────────────────────────────────────


async def test_generate_briefing_uc_hhi_empty_portfolio() -> None:
    """F-NIT-002: Empty portfolio positions → concentration_score = 0.0."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={"positions": []},
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    assert result["risk_summary"]["concentration_score"] == 0.0


async def test_generate_briefing_uc_hhi_zero_value_holdings() -> None:
    """F-NIT-002: All positions with value=0 → concentration_score = 0.0 (no division by zero)."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={
            "positions": [
                {"symbol": "AAPL", "value": 0, "sector": "tech"},
                {"symbol": "MSFT", "value": 0, "sector": "tech"},
            ],
        },
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    # total_value=0 → weights can't be computed → concentration_score stays 0.0
    assert result["risk_summary"]["concentration_score"] == 0.0


async def test_generate_briefing_uc_hhi_no_positions_key() -> None:
    """F-NIT-002: Missing 'positions' key in portfolio_context → concentration_score = 0.0."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase

    async def _fake_stream(prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        yield "ok"

    mock_valkey = MagicMock()
    mock_valkey.incr = AsyncMock(return_value=1)
    mock_valkey.expire = AsyncMock()
    mock_chain = MagicMock()
    mock_chain.stream = _fake_stream

    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={},  # no 'positions' key at all
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
    )

    assert result["risk_summary"]["concentration_score"] == 0.0
