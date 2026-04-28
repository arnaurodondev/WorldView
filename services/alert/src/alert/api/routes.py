"""Alert service REST and WebSocket routes.

Endpoints:
  GET  /api/v1/alerts/pending          — list unacknowledged alerts for the authenticated user
  DELETE /api/v1/alerts/{alert_id}/ack — acknowledge (mark delivered) an alert for the user
  WS   /api/v1/alerts/stream           — WebSocket real-time alert stream
"""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from alert.api.dependencies import AckUseCaseDep, CurrentUserIdDep, GetPendingAlertsUseCaseDep
from alert.api.schemas import PendingAlertResponse, PendingAlertsResponse
from alert.domain.enums import AlertSeverity
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["alerts"])


# ── REST: GET /api/v1/alerts/pending ─────────────────────────────────────────


@router.get("/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts(
    request: Request,
    uc: GetPendingAlertsUseCaseDep,
    user_id: CurrentUserIdDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_severity: str | None = Query(default=None, description="Minimum severity: low|medium|high|critical"),
) -> PendingAlertsResponse:
    """Return paginated unacknowledged alerts for the authenticated user.

    ``user_id`` is extracted from the RS256 internal JWT set by InternalJWTMiddleware
    (PRD-0025 §T-D-1-10). The caller must not pass user_id as a query parameter.

    Optional ``min_severity`` filter returns only alerts at or above the
    given tier (e.g. ``?min_severity=high`` returns HIGH and CRITICAL only).
    """
    severity_filter: AlertSeverity | None = None
    if min_severity is not None:
        try:
            severity_filter = AlertSeverity(min_severity)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid min_severity: must be low|medium|high|critical",
            ) from None

    pairs = await uc.execute(user_id=user_id, limit=limit, offset=offset, min_severity=severity_filter)

    alert_responses = [
        PendingAlertResponse(
            pending_id=p.pending_id,
            alert_id=p.alert_id,
            entity_id=alert.entity_id,
            alert_type=str(alert.alert_type),
            source_topic=alert.source_topic,
            payload=alert.payload,
            created_at=p.created_at,
            severity=str(alert.severity),
            # PLAN-0049 T-D-4-04: pass enrichment columns through so the frontend
            # never has to fall back to "<SEVERITY> signal" labels (F-D-006).
            title=alert.title,
            ticker=alert.ticker,
            entity_name=alert.entity_name,
            signal_label=alert.signal_label,
        )
        for p, alert in pairs
    ]

    return PendingAlertsResponse(
        alerts=alert_responses,
        total=len(alert_responses),
        limit=limit,
        offset=offset,
    )


# ── REST: DELETE /api/v1/alerts/{alert_id}/ack ───────────────────────────────


@router.delete("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: UUID,
    request: Request,
    uc: AckUseCaseDep,
    user_id: CurrentUserIdDep,
) -> dict[str, str]:
    """Acknowledge (mark delivered) an alert for the authenticated user.

    ``user_id`` is extracted from the RS256 internal JWT set by InternalJWTMiddleware
    (PRD-0025 §T-D-1-10).

    Returns 200 on success.  Returns 404 — not 403 — when the alert
    does not exist OR belongs to a different user (avoids user enumeration).

    The use case commits the DB session on success (N-04); the route must NOT
    call ``session.commit()``.
    """
    updated = await uc.execute(user_id, alert_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")

    logger.debug(  # type: ignore[no-any-return]
        "alert_acknowledged",
        alert_id=str(alert_id),
        user_id=str(user_id),
    )
    return {"status": "acknowledged"}


# ── WebSocket: /api/v1/alerts/stream ─────────────────────────────────────────


@router.websocket("/alerts/stream")
async def alerts_stream(
    websocket: WebSocket,
) -> None:
    """WebSocket endpoint — pushes real-time alerts to a connected user.

    ``user_id`` is extracted from ``websocket.state.user_id`` set by
    InternalJWTMiddleware on the HTTP upgrade request (PRD-0025 §T-D-1-10).
    The JWT must be passed via the ``X-Internal-JWT`` header on the upgrade
    request (S9 injects this after validating the client token).

    Architecture (cross-process fan-out):
    - The standalone ``intelligence_consumer_main`` process publishes alerts to
      Valkey channel ``alert:{user_id}`` via ``ValkeyNotificationPublisher``.
    - This handler subscribes to that channel and forwards each message to the
      connected WebSocket client.
    - The in-process ``ConnectionManager`` is retained for direct pushes from
      within the API process (e.g., integration tests, future in-process paths).

    Delivery is best-effort: if no client is connected when a message arrives,
    the message is dropped.  On reconnect, clients catch up via GET /alerts/pending.
    """
    # WHY inline JWT validation: BaseHTTPMiddleware skips dispatch() for WebSocket
    # ASGI scopes (scope["type"] != "http"), so InternalJWTMiddleware never runs
    # for WS connections. websocket.state.user_id is therefore never populated.
    # We validate the ws-token directly here instead.
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    public_key = getattr(websocket.app.state, "_internal_jwt_public_key", None)
    skip_verification = getattr(websocket.app.state, "_internal_jwt_skip_verification", False)

    if public_key is None and not skip_verification:
        # Fail-closed: JWKS not yet loaded (only possible during startup race).
        await websocket.close(code=1011)
        return

    try:
        if skip_verification:
            # Test/dev mode only — InternalJWTMiddleware was configured with
            # skip_verification=True (no JWKS endpoint available).
            payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256"])
        else:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer="worldview-gateway",
                options={"require": ["sub", "exp", "iss"]},
            )
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        await websocket.close(code=4001)
        return

    manager = websocket.app.state.ws_manager
    valkey = websocket.app.state.valkey
    channel = f"alert:{user_id}"

    await manager.connect(user_id, websocket)
    try:
        async with valkey.subscribe(channel) as pubsub:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message is None:
                    # 30 s elapsed with no alert — send a ping to detect stale connections.
                    # If the client has disconnected, send_text raises and we exit cleanly.
                    try:
                        await websocket.send_text('{"type":"ping"}')
                    except (WebSocketDisconnect, Exception):
                        break
                elif message.get("type") == "message":
                    try:
                        await websocket.send_text(message["data"])
                    except WebSocketDisconnect:
                        break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning(  # type: ignore[no-any-return]
            "websocket_subscribe_failed",
            user_id=str(user_id),
            exc_info=True,
        )
        # Inform the client before closing; suppress errors if already disconnected.
        try:
            await websocket.send_json({"error": "service_unavailable", "code": 1011})
            await websocket.close(code=1011)
        except Exception:  # noqa: S110
            pass
    finally:
        manager.disconnect(user_id)
