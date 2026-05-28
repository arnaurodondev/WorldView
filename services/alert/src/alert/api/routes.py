"""Alert service REST and WebSocket routes.

Endpoints:
  POST   /api/v1/alerts                           — create a user-initiated alert rule (PLAN-0082 Wave B)
  GET    /api/v1/alerts/pending                   — list unacknowledged alerts for the authenticated user
  DELETE /api/v1/alerts/{alert_id}/ack            — acknowledge a per-user pending alert
  PATCH  /api/v1/alerts/{alert_id}/acknowledge    — tenant-level alert ack (PLAN-0051 T-D-4-02)
  PATCH  /api/v1/alerts/{alert_id}/snooze         — set snooze_until (PLAN-0051 T-D-4-02)
  GET    /api/v1/alerts/history                   — paginated tenant history (PLAN-0051 T-D-4-02)
  WS     /api/v1/alerts/stream                    — WebSocket real-time alert stream
"""

from __future__ import annotations

import contextlib
import time
from datetime import datetime
from uuid import UUID

import jwt
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from alert.api.dependencies import (
    AckAlertUseCaseDep,
    AckUseCaseDep,
    CreateAlertUseCaseDep,
    CurrentUserIdDep,
    DbSessionDep,
    GetPendingAlertsUseCaseDep,
    HistoryUseCaseDep,
    ReadDbSessionDep,
    SnoozeUseCaseDep,
    TenantUserDep,
)
from alert.api.schemas import (
    AcknowledgeAlertRequest,
    ActiveAlertFlagResponse,
    AlertCreatedResponse,
    AlertHistoryResponse,
    AlertResponse,
    CreateAlertRequest,
    PendingAlertResponse,
    PendingAlertsResponse,
    SnoozeAlertRequest,
)
from alert.application.use_cases.active_alert_flag import GetActiveAlertFlagUseCase
from alert.application.use_cases.create_alert import CreateAlertRequest as CreateAlertInput
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["alerts"])

# PLAN-0094 follow-up: a second router with the /internal/v1 prefix so the
# service-caller endpoint lives outside the public /api/v1 namespace. Both
# routers are included in app.py and share the same InternalJWTMiddleware.
internal_router = APIRouter(prefix="/internal/v1", tags=["alerts-internal"])


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


# ── REST: GET /internal/v1/users/{user_id}/alerts/pending ────────────────────
# PLAN-0094 follow-up: service-caller endpoint. The default ``/api/v1/alerts/pending``
# derives ``user_id`` from the JWT ``sub`` claim (CurrentUserIdDep) — that works
# for human callers but the rag-chat brief pre-generation worker holds a single
# service-account JWT whose ``sub`` is ``service:rag-chat-brief-scheduler``,
# not a real user UUID. This parallel endpoint accepts ``user_id`` in the path
# and is gated by an allow-list of service callers (defence-in-depth: a valid
# service token is necessary but not sufficient).
_SERVICE_BRIEF_ALLOWED: frozenset[str] = frozenset(
    {
        "rag-chat-brief-scheduler",
    },
)


@internal_router.get("/users/{user_id}/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts_for_user(
    user_id: UUID,
    request: Request,
    uc: GetPendingAlertsUseCaseDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_severity: str | None = Query(default=None),
) -> PendingAlertsResponse:
    """Return paginated unacknowledged alerts for an arbitrary user — system callers only.

    Auth requires:
      - InternalJWTMiddleware validates the X-Internal-JWT signature.
      - JWT role must be "system" AND service_name must be in
        ``_SERVICE_BRIEF_ALLOWED``.  Anything else returns 403.

    Used by the rag-chat brief pre-generation worker so a single service-account
    JWT can fetch alerts for many users without minting per-user tokens.
    """
    jwt_role = getattr(request.state, "role", "")
    jwt_service_name = getattr(request.state, "service_name", "")

    if jwt_role != "system" or jwt_service_name not in _SERVICE_BRIEF_ALLOWED:
        # Audit-log denied attempts so abuse / mis-config is visible (R12).
        logger.warning(  # type: ignore[no-any-return]
            "alert_pending_service_caller_denied",
            service_name=jwt_service_name,
            role=jwt_role,
            path_user_id=str(user_id),
        )
        raise HTTPException(status_code=403, detail="Service-token access required")

    # Audit log every successful service-caller access — small volume, high
    # signal (one record per brief generation per user).
    logger.info(  # type: ignore[no-any-return]
        "alert_pending_service_caller",
        service_name=jwt_service_name,
        path_user_id=str(user_id),
    )

    severity_filter: AlertSeverity | None = None
    if min_severity is not None:
        try:
            severity_filter = AlertSeverity(min_severity)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid min_severity: must be low|medium|high|critical",
            ) from None

    pairs = await uc.execute(
        user_id=user_id,
        limit=limit,
        offset=offset,
        min_severity=severity_filter,
    )

    # Mirror the response shape of /api/v1/alerts/pending exactly — frontend /
    # rag-chat consumers expect the same JSON contract.
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


# ── REST: GET /internal/v1/instruments/{instrument_id}/active-alert-flag ──────
# PLAN-0089 Wave L-5a T-WL5A-02: per-entity active-alert summary for the
# screener S3-side sync worker (Wave L-5b). Aggregates across all users —
# "active" means any non-acked, non-snoozed alert row exists for the entity.
# Read-only (R27) → uses ReadDbSessionDep. Auth: InternalJWTMiddleware
# already gates anything under /internal/v1 — no service-account allow-list
# is needed here because no user-scoped data leaves the service.


@internal_router.get(
    "/instruments/{instrument_id}/active-alert-flag",
    response_model=ActiveAlertFlagResponse,
)
async def get_active_alert_flag(
    instrument_id: UUID,
    session: ReadDbSessionDep,
) -> ActiveAlertFlagResponse:
    """Return whether any user has an active alert for ``instrument_id``.

    Endpoint is non-failing: instruments with no alert rows return
    ``has_active_alert=False`` + ``active_alert_count=0`` with HTTP 200.
    The L-5b nightly sync worker treats absence as "no signal".
    """
    flag = await GetActiveAlertFlagUseCase().execute(
        session=session,
        instrument_id=instrument_id,
    )
    return ActiveAlertFlagResponse(
        instrument_id=instrument_id,
        has_active_alert=flag.has_active_alert,
        active_alert_count=flag.active_alert_count,
    )


# ── REST: POST /api/v1/alerts ────────────────────────────────────────────────


@router.post("/alerts", response_model=AlertCreatedResponse, status_code=201)
async def create_alert(
    body: CreateAlertRequest,
    uc: CreateAlertUseCaseDep,
    session: DbSessionDep,
    tenant_user: TenantUserDep,
) -> AlertCreatedResponse:
    """Create a user-initiated alert rule (PLAN-0082 Wave B).

    Writes an Alert row + OutboxEvent in a single transaction (R8 outbox
    pattern).  The OutboxDispatcher publishes ``alert.created.v1`` to Kafka
    asynchronously so the response does not wait on Kafka availability.

    ``tenant_id`` and ``user_id`` are extracted from the RS256 internal JWT
    set by InternalJWTMiddleware (PRD-0025 §T-D-1-10).  Callers must never
    pass them in the request body — they are injected from the verified JWT.

    Returns 201 + AlertCreatedResponse on success.
    Returns 409 if a duplicate alert rule exists for the same entity + condition
    within the dedup window (5 minutes).
    """
    from alert.domain.errors import DuplicateAlertError

    tenant_id, user_id = tenant_user

    try:
        result = await uc.execute(
            CreateAlertInput(
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                entity_id=str(body.entity_id),
                condition=body.condition,
                threshold=dict(body.threshold),
                severity=body.severity,
                source="llm_tool",  # REST path — same source label as LLM tool path
            )
        )
    except DuplicateAlertError:
        raise HTTPException(
            status_code=409,
            detail="A duplicate alert rule for this entity and condition already exists",
        ) from None

    # Commit both the Alert row and OutboxEvent row atomically (R8). The use case
    # flushes but does not commit — commit ownership stays in the route layer so
    # the transaction boundary is explicit and visible to the caller.
    await session.commit()

    logger.info(  # type: ignore[no-any-return]
        "alert_rule_created_via_api",
        alert_id=result.alert_id,
        entity_id=result.entity_id,
        condition=result.condition,
        user_id=str(user_id),
        tenant_id=str(tenant_id),
    )
    return AlertCreatedResponse(
        alert_id=UUID(result.alert_id),
        entity_id=UUID(result.entity_id),
        condition=result.condition,
        threshold=result.threshold,
        severity=result.severity,
        created_at=result.created_at,
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _alert_to_response(alert: Alert) -> AlertResponse:
    """Map a domain Alert to the wire AlertResponse schema.

    Centralised so ack/snooze/history routes all serialise consistently.
    """
    return AlertResponse(
        alert_id=alert.alert_id,
        entity_id=alert.entity_id,
        alert_type=str(alert.alert_type),
        source_topic=alert.source_topic,
        payload=alert.payload,
        created_at=alert.created_at,
        severity=str(alert.severity),
        tenant_id=alert.tenant_id,
        title=alert.title,
        ticker=alert.ticker,
        entity_name=alert.entity_name,
        signal_label=alert.signal_label,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by_user_id=alert.acknowledged_by_user_id,
        snooze_until=alert.snooze_until,
    )


# ── REST: PATCH /api/v1/alerts/{alert_id}/acknowledge (PLAN-0051 T-D-4-02) ───


@router.patch("/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert_entity(
    alert_id: UUID,
    uc: AckAlertUseCaseDep,
    tenant_user: TenantUserDep,
    body: AcknowledgeAlertRequest | None = None,
) -> AlertResponse:
    """Acknowledge an alert at the tenant level (sets ``acknowledged_at``).

    Idempotent: re-acking returns the existing acknowledged_at + user_id
    untouched (no overwrite). Returns 404 if the alert is missing or belongs
    to a different tenant (we collapse 403 → 404 to avoid alert-existence
    enumeration).
    """
    # body is currently informational; reserved for a future audit log table.
    _ = body
    tenant_id, user_id = tenant_user
    outcome, alert = await uc.execute(alert_id, user_id, tenant_id)

    if outcome == "not_found" or outcome == "forbidden":
        # Collapse 403 → 404: don't leak alert existence to other tenants.
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert is None:
        # Defensive — should be unreachable when outcome is "ok"/"already".
        raise HTTPException(status_code=500, detail="Alert vanished mid-request")

    logger.debug(  # type: ignore[no-any-return]
        "alert_entity_acknowledged",
        alert_id=str(alert_id),
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        outcome=outcome,
    )
    return _alert_to_response(alert)


# ── REST: PATCH /api/v1/alerts/{alert_id}/snooze (PLAN-0051 T-D-4-02) ────────


@router.patch("/alerts/{alert_id}/snooze", response_model=AlertResponse)
async def snooze_alert_entity(
    alert_id: UUID,
    body: SnoozeAlertRequest,
    uc: SnoozeUseCaseDep,
    tenant_user: TenantUserDep,
) -> AlertResponse:
    """Snooze an alert until a future timestamp (max 30 days out).

    Returns 422 when ``until`` is in the past, naive (no tz), or > 30 days
    out. Returns 404 when the alert is missing OR belongs to a different
    tenant (same enumeration-avoidance policy as acknowledge).
    """
    tenant_id, _user_id = tenant_user
    outcome, alert = await uc.execute(alert_id, body.until, tenant_id)

    if outcome == "invalid":
        raise HTTPException(
            status_code=422,
            detail="snooze_until must be timezone-aware, in the future, and <= 30 days out",
        )
    if outcome == "not_found" or outcome == "forbidden":
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert is None:
        raise HTTPException(status_code=500, detail="Alert vanished mid-request")

    logger.debug(  # type: ignore[no-any-return]
        "alert_entity_snoozed",
        alert_id=str(alert_id),
        snooze_until=body.until.isoformat(),
        tenant_id=str(tenant_id),
    )
    return _alert_to_response(alert)


# ── REST: GET /api/v1/alerts/history (PLAN-0051 T-D-4-02) ────────────────────


@router.get("/alerts/history", response_model=AlertHistoryResponse)
async def list_alert_history(
    uc: HistoryUseCaseDep,
    tenant_user: TenantUserDep,
    severity: str | None = Query(default=None, description="low|medium|high|critical"),
    entity_id: UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    status: str = Query(default="all", description="active|acknowledged|snoozed|all"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AlertHistoryResponse:
    """Return paginated, tenant-scoped alert history.

    Read-only — uses ``ReadOnlyUnitOfWork`` (R27) via the read replica.
    Tenant filtering is enforced by the use case using the JWT-derived
    ``tenant_id`` (never a header — F-CRIT-001 / PRD-0025).
    """
    tenant_id, _user_id = tenant_user

    # Validate severity enum; keep a helpful 422 instead of silently filtering
    # out everything when the caller mistypes a tier.
    severity_filter: AlertSeverity | None = None
    if severity is not None:
        try:
            severity_filter = AlertSeverity(severity)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Invalid severity: must be low|medium|high|critical",
            ) from None

    # Validate status enum the same way (forward-compat: use case will fall
    # back to "all" but we surface a 422 here to give callers explicit feedback).
    if status not in ("active", "acknowledged", "snoozed", "all"):
        raise HTTPException(
            status_code=422,
            detail="Invalid status: must be active|acknowledged|snoozed|all",
        )

    alerts, total = await uc.execute(
        tenant_id,
        status=status,
        severity=severity_filter,
        entity_id=entity_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )

    # WHY total is the universe (not page size): QA-iter1 C-3 — the frontend
    # computes ``hasMore = rows.length < total`` to decide whether to render
    # "Load more". With page-size semantics that condition is always False
    # and pagination was unreachable. ``has_more`` is now derived consistently
    # from offset + page rows vs the universe size.
    return AlertHistoryResponse(
        alerts=[_alert_to_response(a) for a in alerts],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(alerts) < total,
    )


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
    #
    # P0-1 (PLAN-0088): The api-gateway issues this token via ``issue_ws_jwt`` with
    # ``aud=worldview-internal`` and ``scope=alerts:stream``. PyJWT >= 2.0 raises
    # ``InvalidAudienceError`` whenever a token contains an ``aud`` claim and the
    # ``jwt.decode`` call does NOT pass ``audience=`` — that bug was making every
    # WebSocket upgrade close with 4001/403. We now mirror the canonical decode
    # parameters from ``InternalJWTMiddleware.dispatch`` exactly: same issuer,
    # same audience, same algorithm. We additionally enforce the ``alerts:stream``
    # scope so a token issued for a different purpose cannot subscribe to the
    # alert WebSocket.
    token = websocket.query_params.get("token")
    if not token:
        # 4401 = unauthorized application close code (see RFC 6455 §7.4.2 +
        # IANA WebSocket Close Code registry). Distinct from 4001 so that
        # operators / tests can tell "no token" apart from "service down (1011)".
        await websocket.close(code=4401, reason="missing token")
        return

    public_key = getattr(websocket.app.state, "_internal_jwt_public_key", None)
    skip_verification = getattr(websocket.app.state, "_internal_jwt_skip_verification", False)

    if public_key is None and not skip_verification:
        # Fail-closed: JWKS not yet loaded (only possible during startup race).
        await websocket.close(code=1011, reason="jwks not loaded")
        return

    try:
        if skip_verification:
            # Test/dev mode only — InternalJWTMiddleware was configured with
            # skip_verification=True (no JWKS endpoint available).
            payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256"])
        else:
            # public_key is fetched from the JWKS cache as Any | None; in this
            # branch we already verified it is not None, but mypy can't narrow
            # ``Any | None`` to the cryptography union type pyjwt expects.
            payload = jwt.decode(
                token,
                public_key,  # type: ignore[arg-type]
                algorithms=["RS256"],
                issuer="worldview-gateway",
                # P0-1: audience=worldview-internal must match the ``aud`` claim
                # set by ``issue_ws_jwt`` in api-gateway/jwt_utils.py. Without
                # this, PyJWT raises InvalidAudienceError → close(4401).
                audience="worldview-internal",
                options={"require": ["sub", "exp", "iss", "aud"]},
            )
        user_id = UUID(payload["sub"])

        # P0-1: enforce the OAuth2-style ``scope`` claim. ws-tokens are issued with
        # exactly ``scope="alerts:stream"``; reject anything else so a token minted
        # for an unrelated purpose can't subscribe to the alert stream.
        # We accept either the OAuth2 ``scope`` (space-delimited string) or the
        # less-common ``scopes`` (list) shape so we stay compatible with future
        # token formats.
        raw_scope = payload.get("scope")
        scope_list: list[str]
        if isinstance(raw_scope, str):
            scope_list = raw_scope.split()
        elif isinstance(raw_scope, list):
            scope_list = [str(s) for s in raw_scope]
        else:
            # Skip-verification path historically uses tokens with no scope claim;
            # we keep the dev/test path permissive there to avoid breaking unit
            # tests. In production (skip_verification=False) the token always
            # has scope=alerts:stream because issue_ws_jwt sets it unconditionally.
            scope_list = []
        if not skip_verification and "alerts:stream" not in scope_list:
            logger.warning(  # type: ignore[no-any-return]
                "ws_scope_missing",
                user_id=str(user_id),
                scopes=scope_list,
            )
            await websocket.close(code=4401, reason="missing scope")
            return

        # BUG-007 (TASK-W2-02): Capture the token expiry now so the dispatch loop
        # can detect mid-session expiry. PyJWT already validated ``exp`` against
        # the current time at decode (raising ``ExpiredSignatureError`` if past),
        # but a long-lived WS connection can outlive its token. We snapshot the
        # Unix timestamp here and re-check before every send below.
        # The ``require=["...exp..."]`` option above guarantees ``exp`` is present.
        token_exp: int = int(payload["exp"])
    except jwt.InvalidAudienceError:
        # Surface this as its own log so the P0-1 regression is visible if
        # the token issuer ever changes audience again.
        logger.warning("ws_invalid_audience", token_prefix=token[:12])  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="invalid audience")
        return
    except jwt.ExpiredSignatureError:
        logger.debug("ws_token_expired", token_prefix=token[:12])  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="token expired")
        return
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        logger.debug("ws_token_invalid", error=str(exc))  # type: ignore[no-any-return]
        await websocket.close(code=4401, reason="invalid token")
        return

    manager = websocket.app.state.ws_manager
    valkey = websocket.app.state.valkey
    channel = f"alert:{user_id}"

    await manager.connect(user_id, websocket)
    try:
        async with valkey.subscribe(channel) as pubsub:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)

                # BUG-007 (TASK-W2-02): mid-stream token-expiry check.
                # PyJWT only validates ``exp`` at handshake. A WS connection can
                # easily outlive a short-lived ws-token (default 60-300 s). If
                # the token has expired since handshake, push an ``auth_expired``
                # notification and close with 4401 so the client can re-auth.
                # We check here — after the pubsub wake — so the next send below
                # never goes out under an expired token.
                if time.time() >= token_exp:
                    # Best-effort notify — peer may already be gone. ``suppress``
                    # matches the convention used by
                    # ``alert/infrastructure/websocket/manager.py`` for peer-side
                    # send failures and lets the unconditional ``close()`` below
                    # always terminate the loop.
                    with contextlib.suppress(Exception):
                        await websocket.send_json(
                            {
                                "type": "auth_expired",
                                "message": "Session token expired",
                            },
                        )
                    await websocket.close(code=4401)
                    return

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
        except Exception as exc:
            # BUG-007 (TASK-W2-02): replaced bare ``except Exception: pass`` with
            # a structured warning. Disconnect errors during loop teardown are
            # expected (the peer is often already gone by the time we try to
            # notify them) so we still swallow — we just want them observable.
            # exc_info=False keeps the log line concise; the message is enough
            # to spot trends without polluting logs on every disconnect.
            logger.warning(  # type: ignore[no-any-return]
                "websocket_dispatch_error",
                user_id=str(user_id),
                error=str(exc),
                exc_info=False,
            )
    finally:
        manager.disconnect(user_id)
