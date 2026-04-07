"""Unit tests for POST /internal/v1/briefings (T-B-2-06, PRD-0016 §6.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")
_VALID_TOKEN = "test-internal-token"  # noqa: S105

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
        internal_service_token=_VALID_TOKEN,
        log_json=False,
        log_level="WARNING",
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


async def test_briefing_valid_token_200(settings: RagChatSettings) -> None:
    """Valid token + valid body -> 200 with narrative."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers={"X-Internal-Token": _VALID_TOKEN},
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
            headers={"X-Internal-Token": _VALID_TOKEN},
        )
    body = resp.json()
    assert set(body.keys()) >= {"narrative", "risk_summary", "citations", "generated_at"}
    assert isinstance(body["citations"], list)
    assert isinstance(body["risk_summary"], dict)


# ── Auth failures ─────────────────────────────────────────────────────────────


async def test_briefing_missing_token_401(settings: RagChatSettings) -> None:
    """No X-Internal-Token header -> 401."""
    from rag_chat.domain.errors import BriefingAuthError

    app = _make_app(settings, uc_result=BriefingAuthError("Invalid token"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/internal/v1/briefings", json=_VALID_BODY)
    assert resp.status_code == 401


async def test_briefing_wrong_token_401(settings: RagChatSettings) -> None:
    """Wrong X-Internal-Token -> 401."""
    from rag_chat.domain.errors import BriefingAuthError

    app = _make_app(settings, uc_result=BriefingAuthError("Invalid token"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/briefings",
            json=_VALID_BODY,
            headers={"X-Internal-Token": "wrong-token"},
        )
    assert resp.status_code == 401


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
            headers={"X-Internal-Token": _VALID_TOKEN},
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
            headers={"X-Internal-Token": _VALID_TOKEN},
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
            headers={"X-Internal-Token": _VALID_TOKEN},
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
            headers={"X-Internal-Token": _VALID_TOKEN},
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
            headers={"X-Internal-Token": _VALID_TOKEN},
        )
    assert resp.status_code == 422


# ── Use case unit tests (no HTTP) ─────────────────────────────────────────────


async def test_generate_briefing_uc_auth_failure() -> None:
    """GenerateBriefingUseCase raises BriefingAuthError for wrong token."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.domain.errors import BriefingAuthError

    mock_valkey = MagicMock()
    mock_chain = MagicMock()
    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        internal_service_token="correct-token",
        valkey=mock_valkey,
    )

    with pytest.raises(BriefingAuthError):
        await uc.execute(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            portfolio_context={},
            market_snapshots=[{"symbol": "AAPL"}],
            active_signals=[],
            lookback_days=7,
            token="wrong-token",
        )


async def test_generate_briefing_uc_empty_token_auth_failure() -> None:
    """GenerateBriefingUseCase raises BriefingAuthError for empty token."""
    from rag_chat.application.use_cases.generate_briefing import GenerateBriefingUseCase
    from rag_chat.domain.errors import BriefingAuthError

    mock_valkey = MagicMock()
    mock_chain = MagicMock()
    uc = GenerateBriefingUseCase(
        llm_chain=mock_chain,
        internal_service_token="correct-token",
        valkey=mock_valkey,
    )

    with pytest.raises(BriefingAuthError):
        await uc.execute(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            portfolio_context={},
            market_snapshots=[{"symbol": "AAPL"}],
            active_signals=[],
            lookback_days=7,
            token="",
        )


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
        internal_service_token="correct-token",
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
            token="correct-token",
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
        internal_service_token="correct-token",
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={"positions": [{"symbol": "AAPL", "value": 5000, "sector": "tech"}]},
        market_snapshots=[{"symbol": "AAPL", "close": 175.0}],
        active_signals=[{"id": "sig1", "description": "Price drop"}],
        lookback_days=7,
        token="correct-token",
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
        internal_service_token="tok",
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={
            "positions": [
                {"symbol": "AAPL", "value": 5000, "sector": "tech"},
                {"symbol": "MSFT", "value": 5000, "sector": "tech"},
            ]
        },
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
        token="tok",
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
        internal_service_token="tok",
        valkey=mock_valkey,
    )

    result = await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={"positions": positions},
        market_snapshots=[],
        active_signals=[],
        lookback_days=7,
        token="tok",
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
        internal_service_token="tok",
        valkey=mock_valkey,
    )

    await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={},
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
        token="tok",
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
        internal_service_token="tok",
        valkey=mock_valkey,
    )

    await uc.execute(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        portfolio_context={},
        market_snapshots=[{"symbol": "AAPL"}],
        active_signals=[],
        lookback_days=7,
        token="tok",
    )

    mock_valkey.expire.assert_not_called()
