"""Alert service REST and WebSocket routes.

Endpoints:
  GET  /api/v1/alerts/pending          — list unacknowledged alerts for the authenticated user
  DELETE /api/v1/alerts/{alert_id}/ack — acknowledge (mark delivered) an alert for the user
  WS   /api/v1/alerts/stream           — WebSocket real-time alert stream
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from alert.api.dependencies import DbSessionDep
from alert.api.schemas import PendingAlertResponse, PendingAlertsResponse
from alert.application.use_cases.pending_alerts import (
    AcknowledgeAlertUseCase,
    GetPendingAlertsUseCase,
)
from alert.infrastructure.db.repositories.alert import AlertRepository
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["alerts"])


# ── REST: GET /api/v1/alerts/pending ─────────────────────────────────────────


@router.get("/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts(
    request: Request,
    session: DbSessionDep,
    user_id: UUID = Query(..., description="Authenticated user UUID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingAlertsResponse:
    """Return paginated unacknowledged alerts for the given user.

    In production this user_id should come from a JWT/session; for the
    current deployment the caller passes it as a query parameter (S9
    API gateway will inject it from the auth token).
    """
    pending_repo = PendingAlertRepository(session)
    alert_repo = AlertRepository(session)
    pairs = await GetPendingAlertsUseCase().execute(pending_repo, alert_repo, user_id, limit=limit, offset=offset)  # type: ignore[arg-type]

    alert_responses = [
        PendingAlertResponse(
            pending_id=p.pending_id,
            alert_id=p.alert_id,
            entity_id=alert.entity_id,
            alert_type=str(alert.alert_type),
            source_topic=alert.source_topic,
            payload=alert.payload,
            created_at=p.created_at,
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
    session: DbSessionDep,
    user_id: UUID = Query(..., description="Authenticated user UUID"),
) -> dict[str, str]:
    """Acknowledge (mark delivered) an alert for the given user.

    Returns 200 on success.  Returns 404 — not 403 — when the alert
    does not exist OR belongs to a different user (avoids user enumeration).
    """
    pending_repo = PendingAlertRepository(session)
    updated = await AcknowledgeAlertUseCase().execute(pending_repo, user_id, alert_id)  # type: ignore[arg-type]
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    await session.commit()

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
    user_id: UUID = Query(..., description="Authenticated user UUID"),
) -> None:
    """WebSocket endpoint — pushes real-time alerts to a connected user.

    The client must pass ``user_id`` as a query parameter on connect.

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
