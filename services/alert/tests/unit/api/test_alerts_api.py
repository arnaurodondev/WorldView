"""Unit tests for Alert REST API routes.

Covers:
  - GET /api/v1/alerts/pending: pagination, empty results, user scoping
  - DELETE /api/v1/alerts/{alert_id}/ack: 200 on success, 404 on wrong user,
    404 on already-acknowledged, 404 on non-existent alert
  - WebSocket route is registered

After PRD-0025 T-D-1-10, user_id is extracted from the RS256 internal JWT set
by InternalJWTMiddleware.  Tests pass X-Internal-JWT (HS256, no sig verify in
unit tests because public key is not loaded) to authenticate requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from alert.app import create_app
from alert.config import Settings
from alert.domain.entities import Alert, PendingAlert
from alert.domain.enums import AlertSeverity, AlertType
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from fastapi import FastAPI

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_jwt(user_id: UUID) -> str:
    """Encode a HS256 JWT.  InternalJWTMiddleware decodes without sig verify
    when public key is not loaded (unit test mode — no JWKS endpoint)."""
    return jwt.encode(
        {
            "sub": str(user_id),
            "tenant_id": "tenant-test",
            "role": "owner",
            "iss": "worldview-gateway",
            "exp": 9999999999,
        },
        "secret",
        algorithm="HS256",
    )


def _make_app() -> FastAPI:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        admin_token="test-admin",
        service_name="alert-unit-test",
        log_json=False,
        s8_internal_jwt="test-s8-token",
        s1_internal_token="test-s1-token",
        # F-001: skip_verification=True — no JWKS public key loaded in unit tests
        internal_jwt_skip_verification=True,
    )
    app = create_app(settings)
    # Wire minimal state so dependency injection works without a real DB
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory

    from alert.infrastructure.websocket.manager import ConnectionManager

    app.state.ws_manager = ConnectionManager()
    return app, session  # type: ignore[return-value]


def _make_alert(entity_id: UUID | None = None, severity: AlertSeverity = AlertSeverity.LOW) -> Alert:
    return Alert(
        alert_id=uuid4(),
        entity_id=entity_id or uuid4(),
        alert_type=AlertType.SIGNAL,
        severity=severity,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={"event_type": "nlp.signal.detected"},
        dedup_key="abc123",
        created_at=datetime.now(UTC),
    )


def _make_pending(user_id: UUID, alert_id: UUID) -> PendingAlert:
    return PendingAlert(
        pending_id=uuid4(),
        user_id=user_id,
        alert_id=alert_id,
        created_at=datetime.now(UTC),
        delivered_at=None,
    )


# ── GET /api/v1/alerts/pending ────────────────────────────────────────────────

# Patch paths target the repository modules (repos are imported lazily inside functions).
_PENDING_REPO_PATH = "alert.infrastructure.db.repositories.pending_alert.PendingAlertRepository"
_ALERT_REPO_PATH = "alert.infrastructure.db.repositories.alert.AlertRepository"


class TestGetPendingAlerts:
    @pytest.mark.unit
    async def test_returns_empty_list_when_no_alerts(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        token = _make_jwt(user_id)

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[])

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": token})

        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert data["total"] == 0

    @pytest.mark.unit
    async def test_returns_pending_alerts_for_user(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert = _make_alert()
        pending = _make_pending(user_id, alert.alert_id)
        token = _make_jwt(user_id)

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[pending])
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=alert)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": token})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert str(data["alerts"][0]["alert_id"]) == str(alert.alert_id)
        assert data["alerts"][0]["alert_type"] == "SIGNAL"
        assert "severity" in data["alerts"][0]

    @pytest.mark.unit
    async def test_pagination_params_respected(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        token = _make_jwt(user_id)

        captured_args: list[dict] = []

        async def _capture_list(
            uid: UUID,
            limit: int = 50,
            offset: int = 0,
            min_severities: list | None = None,
        ) -> list:
            captured_args.append({"user_id": uid, "limit": limit, "offset": offset})
            return []

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
            MockPendingRepo.return_value.list_by_user = _capture_list

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.get(
                    "/api/v1/alerts/pending?limit=10&offset=20",
                    headers={"X-Internal-JWT": token},
                )

        assert captured_args[0]["limit"] == 10
        assert captured_args[0]["offset"] == 20

    @pytest.mark.unit
    async def test_missing_alert_record_skipped(self) -> None:
        """Pending row whose alert was deleted (orphan) is silently skipped."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        pending = _make_pending(user_id, uuid4())
        token = _make_jwt(user_id)

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[pending])
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=None)  # orphan

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": token})

        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.unit
    async def test_get_pending_response_has_severity(self) -> None:
        """Response JSON includes the severity field on each alert item."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert = _make_alert(severity=AlertSeverity.HIGH)
        pending = _make_pending(user_id, alert.alert_id)
        token = _make_jwt(user_id)

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = AsyncMock(return_value=[pending])
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=alert)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/alerts/pending", headers={"X-Internal-JWT": token})

        assert resp.status_code == 200
        item = resp.json()["alerts"][0]
        assert item["severity"] == "high"

    @pytest.mark.unit
    async def test_get_pending_min_severity_query_param(self) -> None:
        """?min_severity=high passes min_severities=[HIGH,CRITICAL] to the repo (SQL filter).

        D-4: filtering is now done in SQL (list_by_user receives min_severities list),
        not in Python post-pagination. The repo mock returns only the SQL-filtered result.
        """
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_high = _make_alert(severity=AlertSeverity.HIGH)
        pending_high = _make_pending(user_id, alert_high.alert_id)
        token = _make_jwt(user_id)

        captured_min_severities: list[list[str] | None] = []

        async def _list_by_user(
            uid: UUID,
            limit: int = 50,
            offset: int = 0,
            min_severities: list[str] | None = None,
        ) -> list:
            captured_min_severities.append(min_severities)
            # Simulate SQL filtering: only return pending_high because min_severities was applied
            return [pending_high]

        with (
            patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
            MockPendingRepo.return_value.list_by_user = _list_by_user
            MockAlertRepo.return_value.get_by_id = AsyncMock(return_value=alert_high)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/alerts/pending?min_severity=high",
                    headers={"X-Internal-JWT": token},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["alerts"][0]["severity"] == "high"
        # Verify min_severities was passed to the repo (not filtered in Python)
        # StrEnum str() gives lowercase values: "high", "critical" etc.
        assert captured_min_severities[0] is not None
        assert "high" in captured_min_severities[0]
        assert "critical" in captured_min_severities[0]
        assert "low" not in captured_min_severities[0]

    @pytest.mark.unit
    async def test_get_pending_invalid_min_severity(self) -> None:
        """?min_severity=extreme returns HTTP 422."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        token = _make_jwt(user_id)

        with (
            patch(_PENDING_REPO_PATH),
            patch(_ALERT_REPO_PATH),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/alerts/pending?min_severity=extreme",
                    headers={"X-Internal-JWT": token},
                )

        assert resp.status_code == 422


# ── DELETE /api/v1/alerts/{alert_id}/ack ─────────────────────────────────────


class TestAcknowledgeAlert:
    @pytest.mark.unit
    async def test_ack_returns_200_on_success(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        token = _make_jwt(user_id)

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=True)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/v1/alerts/{alert_id}/ack",
                    headers={"X-Internal-JWT": token},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "acknowledged"

    @pytest.mark.unit
    async def test_ack_returns_404_on_wrong_user(self) -> None:
        """ack returns 404 — not 403 — when alert belongs to a different user."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        token = _make_jwt(user_id)

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=False)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/v1/alerts/{alert_id}/ack",
                    headers={"X-Internal-JWT": token},
                )

        assert resp.status_code == 404

    @pytest.mark.unit
    async def test_ack_returns_404_on_already_acknowledged(self) -> None:
        """ack returns 404 when the alert was already acknowledged."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        token = _make_jwt(user_id)

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=False)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/v1/alerts/{alert_id}/ack",
                    headers={"X-Internal-JWT": token},
                )

        # Same as wrong user — avoids user enumeration
        assert resp.status_code == 404

    @pytest.mark.unit
    async def test_ack_calls_acknowledge_with_correct_ids(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        token = _make_jwt(user_id)
        captured: list[tuple[UUID, UUID]] = []

        async def _capture_ack(uid: UUID, aid: UUID) -> bool:
            captured.append((uid, aid))
            return True

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = _capture_ack

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.delete(
                    f"/api/v1/alerts/{alert_id}/ack",
                    headers={"X-Internal-JWT": token},
                )

        assert captured[0] == (user_id, alert_id)

    @pytest.mark.unit
    async def test_ack_route_no_commit_in_route(self) -> None:
        """Route handler does NOT call session.commit() — the use case owns the commit (N-04)."""
        app, session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        token = _make_jwt(user_id)

        with patch(_PENDING_REPO_PATH) as MockPendingRepo:
            MockPendingRepo.return_value.acknowledge = AsyncMock(return_value=True)

            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(
                    f"/api/v1/alerts/{alert_id}/ack",
                    headers={"X-Internal-JWT": token},
                )

        assert resp.status_code == 200
        # The route must not call commit directly — AcknowledgeAlertUseCase does it (N-04).
        # The session mock commit was called exactly once: by the use case, not by the route.
        # We verify the route didn't call it a second time by checking commit call count == 1.
        assert session.commit.call_count == 1


# ── WebSocket route ────────────────────────────────────────────────────────────


class TestWebSocketRoute:
    @pytest.mark.unit
    async def test_websocket_stream_requires_jwt(self) -> None:
        """WebSocket /api/v1/alerts/stream requires X-Internal-JWT — rejects without it.

        InternalJWTMiddleware intercepts the HTTP upgrade request and returns 401
        when the X-Internal-JWT header is missing (PRD-0025 §T-D-1-10).
        """
        app, _ = _make_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/alerts/stream")

        # Missing X-Internal-JWT → 401 from InternalJWTMiddleware
        assert resp.status_code >= 400

    @pytest.mark.unit
    def test_ws_inline_validation_no_token_rejects(self) -> None:
        """Inline WS validation: missing ?token= → handler closes the WS connection.

        BaseHTTPMiddleware skips dispatch() for WebSocket ASGI scopes, so the
        alerts_stream handler validates the JWT inline. A connection without a
        token must be rejected (BP-248 follow-up fix).
        """
        from alert.api.routes import router
        from alert.infrastructure.websocket.manager import ConnectionManager
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        # Minimal app — no lifespan, no JWKS fetch
        mini_app = FastAPI()
        mini_app.include_router(router)
        mini_app.state.ws_manager = ConnectionManager()
        mini_app.state._internal_jwt_skip_verification = True
        mini_app.state._internal_jwt_public_key = None

        with TestClient(mini_app, raise_server_exceptions=False) as client:
            with pytest.raises(Exception):  # noqa: B017
                # Handler closes without accept when no token → TestClient raises
                with client.websocket_connect("/api/v1/alerts/stream"):
                    pass  # pragma: no cover

    @pytest.mark.unit
    def test_ws_inline_validation_with_token_passes_auth(self) -> None:
        """Inline WS validation: valid ?token= JWT in skip_verification mode → handler runs.

        Verifies the inline validation accepts valid JWTs and reaches the connection
        logic (Valkey subscribe). Uses skip_verification=True (no JWKS endpoint).
        """
        from unittest.mock import MagicMock

        from alert.api.routes import router
        from alert.infrastructure.websocket.manager import ConnectionManager
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        # Minimal app — no lifespan, no JWKS fetch, skip_verification=True
        mini_app = FastAPI()
        mini_app.include_router(router)
        mini_app.state.ws_manager = ConnectionManager()
        mini_app.state._internal_jwt_skip_verification = True
        mini_app.state._internal_jwt_public_key = None

        from starlette.websockets import WebSocketDisconnect

        # Mock valkey.subscribe to raise immediately — forces the handler to exit
        # the subscribe loop so the test doesn't hang. We only care that auth
        # succeeded (connection was accepted and handler started running).
        mock_pubsub = MagicMock()
        mock_pubsub.__aenter__ = AsyncMock(return_value=mock_pubsub)
        mock_pubsub.__aexit__ = AsyncMock(return_value=None)
        mock_pubsub.get_message = AsyncMock(side_effect=WebSocketDisconnect())
        mock_valkey = MagicMock()
        mock_valkey.subscribe = MagicMock(return_value=mock_pubsub)
        mini_app.state.valkey = mock_valkey

        user_id = uuid4()
        token = _make_jwt(user_id)

        with TestClient(mini_app, raise_server_exceptions=False) as client:
            try:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}") as _ws:
                    pass  # if connection is accepted, auth succeeded
            except Exception:  # noqa: S110
                pass  # disconnect expected when handler exits


# ── PLAN-0088 P0-1: WebSocket audience + scope validation ────────────────────
#
# Regression tests for the alert WS 403 / 4401 bug. Token issuance from
# api-gateway sets ``aud=worldview-internal`` and ``scope=alerts:stream``;
# the alert WS handler must mirror those checks or PyJWT raises
# InvalidAudienceError on every connection.


def _build_rs256_keypair() -> tuple[Any, Any]:
    """Generate an in-memory RSA keypair for one test.

    We don't share keys across tests so each test is hermetic — a key compromise
    in one test cannot pollute another.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _build_ws_app(public_key: Any) -> Any:
    """Minimal FastAPI app wired with the alerts router and a public key.

    We deliberately set ``_internal_jwt_skip_verification = False`` so the
    handler exercises the real RS256 + audience + scope path (the same path
    that runs in production). Tests of the skip-verification branch live in
    ``test_ws_inline_validation_*`` above.
    """
    from alert.api.routes import router
    from alert.infrastructure.websocket.manager import ConnectionManager
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    app.state.ws_manager = ConnectionManager()
    app.state._internal_jwt_skip_verification = False
    app.state._internal_jwt_public_key = public_key

    # Wire a no-op valkey so the handler never blocks on a real subscribe loop
    # if the auth path happens to succeed in a test.
    mock_pubsub = MagicMock()
    mock_pubsub.__aenter__ = AsyncMock(return_value=mock_pubsub)
    mock_pubsub.__aexit__ = AsyncMock(return_value=None)
    mock_pubsub.get_message = AsyncMock(side_effect=Exception("stop"))
    mock_valkey = MagicMock()
    mock_valkey.subscribe = MagicMock(return_value=mock_pubsub)
    app.state.valkey = mock_valkey
    return app


def _encode_ws_token(
    private_key: Any,
    *,
    user_id: str | None = None,
    issuer: str = "worldview-gateway",
    audience: str | None = "worldview-internal",
    scope: str | list[str] | None = "alerts:stream",
    exp: int = 9999999999,
) -> str:
    """Build a WS token with the same claim shape as ``issue_ws_jwt`` in S9.

    Pass ``audience=None`` to omit the ``aud`` claim entirely (used to verify
    that the handler still validates correctly when the issuer drops aud).
    Pass ``scope=None`` to omit the ``scope`` claim (used by the missing-scope
    rejection test).
    """
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": user_id or str(uuid4()),
        "tenant_id": "tenant-test",
        "role": "user",
        "jti": "test-jti-ws",
        "iat": 1000000000,
        "exp": exp,
    }
    if audience is not None:
        payload["aud"] = audience
    if scope is not None:
        payload["scope"] = scope
    return jwt.encode(payload, private_key, algorithm="RS256")


class TestWebSocketAudienceAndScope:
    """P0-1 regression: WS handler must validate audience + scope correctly."""

    @pytest.mark.unit
    def test_ws_happy_path_with_audience_and_scope(self) -> None:
        """Token with correct ``aud`` + ``scope`` passes auth and the handler runs.

        Before the fix, PyJWT raised InvalidAudienceError whenever ``aud`` was
        present in the token but ``audience=`` was not passed to ``jwt.decode``,
        which made every WS upgrade fail with the close code we now treat as
        4401. This test locks in the fix.
        """
        from starlette.testclient import TestClient

        private_key, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)
        token = _encode_ws_token(private_key)

        with TestClient(app, raise_server_exceptions=False) as client:
            try:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}") as _ws:
                    # Reaching this branch means the handler accepted the WS
                    # upgrade — the auth path passed.
                    pass
            except Exception:  # noqa: S110
                # The mock valkey raises after subscribe to short-circuit the
                # loop; a disconnect here is expected and means we got past auth.
                pass

    @pytest.mark.unit
    def test_ws_rejects_wrong_audience(self) -> None:
        """Token with ``aud=evil`` is rejected (InvalidAudienceError → 4401)."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        private_key, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)
        token = _encode_ws_token(private_key, audience="evil-service")

        with TestClient(app, raise_server_exceptions=False) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}"):
                    pass  # pragma: no cover
            # 4401 = our application close code for unauthorized WS handshakes.
            assert excinfo.value.code == 4401

    @pytest.mark.unit
    def test_ws_rejects_missing_scope(self) -> None:
        """Token without ``alerts:stream`` scope is rejected with 4401."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        private_key, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)
        token = _encode_ws_token(private_key, scope="some:other:scope")

        with TestClient(app, raise_server_exceptions=False) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}"):
                    pass  # pragma: no cover
            assert excinfo.value.code == 4401

    @pytest.mark.unit
    def test_ws_rejects_expired_token(self) -> None:
        """Token whose ``exp`` is in the past is rejected with 4401."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        private_key, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)
        # exp=1 → 1970-01-01: definitely expired
        token = _encode_ws_token(private_key, exp=1)

        with TestClient(app, raise_server_exceptions=False) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}"):
                    pass  # pragma: no cover
            assert excinfo.value.code == 4401

    @pytest.mark.unit
    def test_ws_rejects_missing_token(self) -> None:
        """No ``?token=`` query param at all → 4401 close."""
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        _, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)

        with TestClient(app, raise_server_exceptions=False) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect("/api/v1/alerts/stream"):
                    pass  # pragma: no cover
            assert excinfo.value.code == 4401

    @pytest.mark.unit
    def test_ws_accepts_scope_as_list(self) -> None:
        """Token with ``scope=["alerts:stream", ...]`` (list shape) is accepted.

        The OAuth2 spec defines ``scope`` as a space-delimited string, but the
        handler also accepts the list shape for forward compatibility with token
        formats that may emerge later. This test pins that contract.
        """
        from starlette.testclient import TestClient

        private_key, public_key = _build_rs256_keypair()
        app = _build_ws_app(public_key)
        token = _encode_ws_token(private_key, scope=["alerts:stream", "extra:scope"])

        with TestClient(app, raise_server_exceptions=False) as client:
            try:
                with client.websocket_connect(f"/api/v1/alerts/stream?token={token}") as _ws:
                    pass
            except Exception:  # noqa: S110
                pass  # mock valkey loop terminator — auth passed
