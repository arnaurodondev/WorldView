"""Alert and email-preference routes for the API Gateway.

Handles /v1/alerts/* and /v1/email/preferences — proxies to S10 Alert service.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from api_gateway.clients import (
    create_alert_rule,
    delete_alert_rule,
    get_alert_rule,
    list_alert_rules,
    update_alert_rule,
)
from api_gateway.routes.helpers import _auth_headers, _clients
from api_gateway.schemas import AlertResponse

router = APIRouter(prefix="/v1")


# ── Email preferences ─────────────────────────────────────────────────────────


@router.get("/email/preferences")
async def get_email_preferences(request: Request) -> Any:
    """Proxy GET /api/v1/email/preferences → S10 Alert service.

    Passes X-Tenant-Id and X-User-Id headers derived from the JWT payload
    so S10 can enforce per-user isolation.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/email/preferences",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.put("/email/preferences")
async def update_email_preferences(request: Request) -> Any:
    """Proxy PUT /api/v1/email/preferences → S10 Alert service.

    Passes request body unchanged; forwards X-Tenant-Id and X-User-Id headers.
    S10 returns 400 on invalid preference values (e.g., send_day_of_week > 6).
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.put(
        "/api/v1/email/preferences",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Alert endpoints (PRD-0025 T-D-1-10) ──────────────────────────────────────


@router.get("/alerts/pending", response_model=list[AlertResponse], response_model_exclude_none=True)
async def get_pending_alerts(request: Request) -> Any:
    """Proxy GET /api/v1/alerts/pending → S10 Alert service.

    Requires authentication. Forwards X-Internal-JWT so S10's InternalJWTMiddleware
    can extract user_id from the JWT (PRD-0025 §T-D-1-10).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/alerts/pending",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/alerts/{alert_id}/ack", status_code=200)
async def acknowledge_alert(alert_id: str, request: Request) -> Any:
    """Proxy DELETE /api/v1/alerts/{alert_id}/ack → S10 Alert service.

    Requires authentication. Forwards X-Internal-JWT so S10 can verify the user
    owns the alert before acknowledging it (PRD-0025 §T-D-1-10).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.delete(
        f"/api/v1/alerts/{alert_id}/ack",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# TODO: WebSocket /alerts/stream proxying requires a dedicated WS proxy implementation.
# S9 does not yet support transparent WebSocket proxying — clients must connect
# directly to S10 (alert-delivery:8010) using a short-lived token from S9.


@router.get("/alerts/stream/ws-url")
async def get_alerts_ws_url(request: Request) -> dict[str, str | int]:
    """Issue a short-lived WS token and return the full WebSocket URL.

    Replaces the client-side pattern of calling /v1/auth/ws-token then
    constructing the URL manually.  Returns ws_url ready for new WebSocket().
    Auth: requires Bearer access token.  Token TTL: 30 s (hardcoded in jwt_utils._WS_TTL).
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authentication_required")

    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        raise HTTPException(status_code=503, detail="jwt_signing_unavailable")

    user_id = user.get("user_id") or user.get("sub")
    tenant_id = user.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="incomplete_auth_claims")

    from api_gateway.jwt_utils import issue_ws_jwt

    token = issue_ws_jwt(user_id=user_id, tenant_id=tenant_id, private_key=private_key, kid=kid)
    settings = request.app.state.settings
    ws_url = f"{settings.alert_ws_url}/api/v1/alerts/stream?token={token}"
    return {"ws_url": ws_url, "token": token, "expires_in": 30}


# ── Alert ack/snooze/history proxies (PLAN-0051 T-D-4-02) ────────────────────
#
# Cache-Control: no-store on every response — these are user-specific, mutate
# state (ack/snooze) or expose tenant-scoped lists (history). A shared CDN
# must never cache them.


@router.patch("/alerts/{alert_id}/acknowledge", status_code=200)
async def acknowledge_alert_entity(alert_id: str, request: Request) -> Response:
    """Proxy PATCH /api/v1/alerts/{alert_id}/acknowledge → S10.

    Forwards the (optional) JSON body and X-Internal-JWT. ``Cache-Control:
    no-store`` prevents any intermediary from caching the mutation response.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {**_auth_headers(request)}
    if body:
        headers["Content-Type"] = "application/json"
    clients = _clients(request)
    resp = await clients.alert.patch(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/alerts/{alert_id}/snooze", status_code=200)
async def snooze_alert_entity(alert_id: str, request: Request) -> Response:
    """Proxy PATCH /api/v1/alerts/{alert_id}/snooze → S10."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {"Content-Type": "application/json", **_auth_headers(request)}
    clients = _clients(request)
    resp = await clients.alert.patch(
        f"/api/v1/alerts/{alert_id}/snooze",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/alerts/history")
async def list_alert_history(request: Request) -> Response:
    """Proxy GET /api/v1/alerts/history → S10 with query params forwarded verbatim."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/alerts/history",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


# ── Alert creation proxy (PLAN-0082 Wave B) ──────────────────────────────────


@router.post("/alerts", status_code=201)
async def create_alert(request: Request) -> Response:
    """Proxy POST /api/v1/alerts → S10 Alert service.

    Creates a user-initiated alert rule.  Requires authentication.  Forwards
    the JSON body and X-Internal-JWT so S10's InternalJWTMiddleware can extract
    the user_id and tenant_id from the JWT (PRD-0025 §T-D-1-10).

    Cache-Control: no-store — this is a write mutation, must never be cached.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {"Content-Type": "application/json", **_auth_headers(request)}
    clients = _clients(request)
    resp = await clients.alert.post(
        "/api/v1/alerts",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


# ── Alert-rule CRUD proxies (PLAN-0113) ──────────────────────────────────────
#
# /v1/alert-rules → S10 /api/v1/alert-rules. Auth-gated; the verified internal
# JWT is forwarded so S10 derives tenant_id/user_id from the token. Mutations
# carry Cache-Control: no-store (user-specific writes must never be cached).


@router.post("/alert-rules", status_code=201)
async def create_rule(request: Request) -> Response:
    """Proxy POST /api/v1/alert-rules → S10 (create a standing rule)."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    resp = await create_alert_rule(_clients(request), body=body, headers=_auth_headers(request))
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/alert-rules")
async def list_rules(request: Request) -> Response:
    """Proxy GET /api/v1/alert-rules → S10 (list the caller's rules)."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    resp = await list_alert_rules(
        _clients(request), params=dict(request.query_params), headers=_auth_headers(request)
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/alert-rules/{rule_id}")
async def get_rule(rule_id: str, request: Request) -> Response:
    """Proxy GET /api/v1/alert-rules/{rule_id} → S10."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    resp = await get_alert_rule(_clients(request), rule_id=rule_id, headers=_auth_headers(request))
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/alert-rules/{rule_id}")
async def update_rule(rule_id: str, request: Request) -> Response:
    """Proxy PATCH /api/v1/alert-rules/{rule_id} → S10 (partial update)."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    resp = await update_alert_rule(_clients(request), rule_id=rule_id, body=body, headers=_auth_headers(request))
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, request: Request) -> Response:
    """Proxy DELETE /api/v1/alert-rules/{rule_id} → S10."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    resp = await delete_alert_rule(_clients(request), rule_id=rule_id, headers=_auth_headers(request))
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
