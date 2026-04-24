"""OIDC auth endpoints for the API Gateway.

Implements the PKCE auth flow (F-01..F-07) from PRD-0025:
  GET  /v1/auth/login     — generate PKCE state, redirect to Zitadel
  GET  /v1/auth/callback  — exchange code for tokens, provision user, set cookie
  POST /v1/auth/refresh   — rotate refresh_token cookie → new access_token
  POST /v1/auth/logout    — revoke token, clear cookie
  GET  /v1/auth/me        — return user profile from validated access_token
  GET  /v1/auth/register  — redirect to Zitadel self-registration (OQ-05)
  GET  /v1/auth/ws-token  — issue 30-second short-lived JWT for WebSocket auth
  POST /v1/auth/dev-login — dev-only: skip Zitadel, issue JWT for demo user
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from api_gateway.pkce import (
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
    retrieve_and_delete_pkce_state,
    store_pkce_state,
)

# SEC-003: Whitelist of valid RFC 6749 error codes.  Any error value not in this
# set is replaced with "unknown_error" before it is reflected in a JSON response.
# This prevents an attacker from injecting arbitrary strings (e.g. HTML/JS) via
# a crafted redirect URI.
_KNOWN_OIDC_ERRORS: frozenset[str] = frozenset(
    {
        "invalid_request",
        "unauthorized_client",
        "access_denied",
        "unsupported_response_type",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
        "interaction_required",
        "login_required",
        "account_selection_required",
        "consent_required",
    }
)

# SEC-003: Only alphanumeric characters plus safe punctuation are allowed in
# error_description.  Everything else is stripped.  Capped at 200 characters to
# prevent log-flooding via a crafted redirect URI.
_SAFE_DESC_RE = re.compile(r"[^a-zA-Z0-9 _.,!?()\-]")
_SAFE_DESC_MAX_LEN: int = 200


def _sanitize_oidc_error(error: str | None, description: str | None) -> tuple[str, str | None]:
    """Return (sanitized_error, sanitized_description) safe for JSON reflection.

    WHY: RFC 6749 §4.1.2.1 errors come from Zitadel query params.  An attacker
    can craft a redirect URI that injects arbitrary content into the JSON body.
    We sanitize both fields before returning them to the caller.
    """
    safe_error = error if error in _KNOWN_OIDC_ERRORS else "unknown_error"
    safe_desc: str | None = None
    if description is not None:
        # Strip disallowed characters, then truncate
        safe_desc = _SAFE_DESC_RE.sub("", description)[:_SAFE_DESC_MAX_LEN]
        if not safe_desc:
            safe_desc = None
    return safe_error, safe_desc


router = APIRouter(prefix="/v1/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_PATH = "/v1/auth/refresh"
_COOKIE_MAX_AGE = 2592000  # 30 days


def _set_refresh_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="strict",
        path=_COOKIE_PATH,
        max_age=_COOKIE_MAX_AGE,
        secure=secure,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value="",
        httponly=True,
        samesite="strict",
        path=_COOKIE_PATH,
        max_age=0,
        secure=False,
    )


@router.get("/login")
async def login(request: Request) -> Response:
    """Initiate PKCE OIDC flow — redirect browser to Zitadel (F-02)."""
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")
    settings = request.app.state.settings
    oidc_config = getattr(request.app.state, "oidc_config", None)
    valkey = getattr(request.app.state, "valkey", None)

    if oidc_config is None:
        return JSONResponse(
            status_code=502,
            content={"error": "oidc_discovery_failed", "detail": "OIDC configuration unavailable"},
        )

    state = generate_state()
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    try:
        await store_pkce_state(valkey, state, code_verifier)
    except RuntimeError:
        logger.warning("pkce_state_store_failed", action="login", result="error")
        return JSONResponse(
            status_code=503,
            content={"error": "valkey_unavailable", "detail": "Auth state storage unavailable"},
        )

    redirect_uri = f"{settings.frontend_url}/callback"
    params = (
        f"client_id={settings.oidc_client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid+profile+email+offline_access"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    auth_url = f"{oidc_config.authorization_endpoint}?{params}"
    logger.info("login_redirect", action="login")
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> Response:
    """Handle Zitadel redirect; exchange code for tokens; provision user (F-03)."""
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")
    settings = request.app.state.settings
    oidc_config = getattr(request.app.state, "oidc_config", None)
    valkey = getattr(request.app.state, "valkey", None)
    httpx_client = getattr(request.app.state, "httpx_client", None)

    # 1. Zitadel error forwarded in query params
    if error:
        # SEC-003: sanitize before reflecting — log raw values for debugging
        logger.warning(
            "callback_oidc_error",
            action="login",
            error_raw=error,
            error_description_raw=error_description,
            result="error",
        )
        safe_error, safe_desc = _sanitize_oidc_error(error, error_description)
        return JSONResponse(
            status_code=400,
            content={"error": safe_error, "error_description": safe_desc},
        )

    # 2. Required params
    if not code or not state:
        return JSONResponse(
            status_code=400,
            content={"error": "missing_params", "detail": "code and state are required"},
        )

    # 3. Retrieve (and delete) PKCE state from Valkey
    if valkey is None:
        return JSONResponse(
            status_code=503,
            content={"error": "valkey_unavailable", "detail": "Auth state storage unavailable"},
        )
    code_verifier = await retrieve_and_delete_pkce_state(valkey, state)
    if code_verifier is None:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_state", "detail": "State expired or invalid"},
        )

    # Guard against missing OIDC config / httpx client (fail-fast after PKCE)
    if oidc_config is None:
        return JSONResponse(status_code=502, content={"error": "oidc_discovery_failed"})
    if httpx_client is None:
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})

    # 4. Exchange code for tokens at Zitadel
    redirect_uri = f"{settings.frontend_url}/callback"
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret.get_secret_value(),
        "code_verifier": code_verifier,
    }
    try:
        token_resp = await httpx_client.post(
            oidc_config.token_endpoint,
            data=token_payload,
            timeout=15.0,
        )
        if token_resp.status_code != 200:
            logger.warning(
                "token_exchange_failed",
                action="login",
                status=token_resp.status_code,
                result="error",
            )
            return JSONResponse(
                status_code=400,
                content={"error": "token_exchange_failed", "detail": "Zitadel token exchange rejected"},
            )
        token_data: dict[str, Any] = token_resp.json()
    except Exception as exc:
        logger.error("token_exchange_error", action="login", error=str(exc), result="error")
        return JSONResponse(
            status_code=503,
            content={"error": "zitadel_unreachable", "detail": "Token endpoint unreachable"},
        )

    access_token: str = token_data.get("access_token", "")
    refresh_token_value: str = token_data.get("refresh_token", "")
    expires_in: int = int(token_data.get("expires_in", 900))

    # 5. Validate access_token signature using Zitadel JWKS
    try:
        unverified_header = jwt.get_unverified_header(access_token)
        kid = unverified_header.get("kid", "default")
        public_key = oidc_config.public_keys.get(kid) or next(iter(oidc_config.public_keys.values()), None)
        if public_key is None:
            raise jwt.InvalidTokenError("No matching public key found in JWKS")
        claims: dict[str, Any] = jwt.decode(  # type: ignore[no-any-return]
            access_token,
            public_key,
            algorithms=["RS256"],
            options={"require": ["sub", "exp", "iss"]},
            audience=settings.oidc_audience,
            issuer=oidc_config.issuer,
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("access_token_invalid", action="login", result="error", reason=str(exc))
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "Access token validation failed"},
        )

    # 6. Extract user claims
    sub: str = claims["sub"]
    email: str = claims.get("email", "")
    email_verified: bool = bool(claims.get("email_verified", False))
    preferred_username: str = claims.get("preferred_username", "")

    # 7. Issue system JWT and call S1 provision endpoint
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid_internal: str = getattr(request.app.state, "rsa_kid", "default")

    if private_key is None or httpx_client is None:
        return JSONResponse(
            status_code=503,
            content={"error": "service_unavailable", "detail": "Internal JWT signing unavailable"},
        )

    from api_gateway.jwt_utils import issue_system_jwt

    system_jwt = issue_system_jwt(sub, private_key, kid_internal)

    try:
        provision_resp = await httpx_client.post(
            f"{settings.portfolio_url}/internal/v1/users/provision",
            json={"sub": sub, "email": email, "username": preferred_username},
            headers={"X-Internal-JWT": system_jwt},
            timeout=10.0,
        )
        if provision_resp.status_code not in (200, 201):
            logger.error(
                "provision_failed",
                action="login",
                sub=sub,
                status=provision_resp.status_code,
                result="error",
            )
            return JSONResponse(
                status_code=503,
                content={"error": "provision_failed", "detail": "User provisioning failed"},
            )
        provision_data: dict[str, Any] = provision_resp.json()
    except Exception as exc:
        logger.error("provision_unreachable", action="login", sub=sub, error=str(exc), result="error")
        return JSONResponse(
            status_code=503,
            content={"error": "provision_unreachable", "detail": "S1 service unreachable"},
        )

    user_id: str = provision_data["user_id"]
    tenant_id: str = provision_data["tenant_id"]

    # 8. Cache user identity in Valkey (TTL=3600)
    try:
        import json

        await valkey.set(
            f"auth:user:{sub}",
            json.dumps({"user_id": user_id, "tenant_id": tenant_id}),
            ttl=3600,
        )
    except Exception:  # noqa: S110 — fail-open: cache miss handled on next request
        pass

    logger.info("login_success", action="login", sub=sub, email=email, result="success")

    # 9. Build response with httpOnly cookie
    body = {
        "access_token": access_token,
        "expires_in": expires_in,
        "token_type": "Bearer",
        "user": {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "sub": sub,
            "email_verified": email_verified,
        },
    }
    response = JSONResponse(status_code=200, content=body)
    if refresh_token_value:
        _set_refresh_cookie(response, refresh_token_value, settings.cookie_secure)
    return response


@router.post("/refresh")
async def refresh(request: Request) -> Response:
    """Exchange httpOnly refresh_token cookie for a new access_token (F-04)."""
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")
    settings = request.app.state.settings
    oidc_config = getattr(request.app.state, "oidc_config", None)
    httpx_client = getattr(request.app.state, "httpx_client", None)

    refresh_token_value = request.cookies.get(_COOKIE_NAME)
    if not refresh_token_value:
        return JSONResponse(
            status_code=401,
            content={"error": "missing_refresh_token", "detail": "refresh_token cookie required"},
        )

    if oidc_config is None:
        return JSONResponse(status_code=502, content={"error": "oidc_discovery_failed"})
    if httpx_client is None:
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})

    token_payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret.get_secret_value(),
    }
    try:
        token_resp = await httpx_client.post(
            oidc_config.token_endpoint,
            data=token_payload,
            timeout=15.0,
        )
        if token_resp.status_code != 200:
            logger.warning("refresh_rejected", action="refresh", status=token_resp.status_code, result="error")
            return JSONResponse(
                status_code=401,
                content={"error": "refresh_rejected", "detail": "Zitadel rejected the refresh token"},
            )
        token_data: dict[str, Any] = token_resp.json()
    except Exception as exc:
        logger.error("refresh_error", action="refresh", error=str(exc), result="error")
        return JSONResponse(
            status_code=503,
            content={"error": "zitadel_unreachable", "detail": "Token endpoint unreachable"},
        )

    new_access_token: str = token_data.get("access_token", "")
    new_refresh_token: str = token_data.get("refresh_token", "")
    expires_in: int = int(token_data.get("expires_in", 900))

    logger.info("refresh_success", action="refresh", result="success")

    response = JSONResponse(
        status_code=200,
        content={"access_token": new_access_token, "expires_in": expires_in, "token_type": "Bearer"},
    )
    if new_refresh_token:
        _set_refresh_cookie(response, new_refresh_token, settings.cookie_secure)
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Revoke refresh_token at Zitadel; clear cookie; invalidate Valkey cache (F-05)."""
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")
    settings = request.app.state.settings
    oidc_config = getattr(request.app.state, "oidc_config", None)
    valkey = getattr(request.app.state, "valkey", None)
    httpx_client = getattr(request.app.state, "httpx_client", None)

    refresh_token_value = request.cookies.get(_COOKIE_NAME)

    # Best-effort: revoke refresh_token at Zitadel end_session_endpoint
    if refresh_token_value and oidc_config and httpx_client:
        try:
            await httpx_client.post(
                oidc_config.end_session_endpoint,
                data={
                    "token": refresh_token_value,
                    "client_id": settings.oidc_client_id,
                    "client_secret": settings.oidc_client_secret.get_secret_value(),
                },
                timeout=5.0,
            )
        except Exception as exc:  # — best-effort; log and continue
            logger.warning("logout_revoke_failed", action="logout", error=str(exc))

    # SEC-002 fix: extract sub from the VERIFIED request.state.user (set by
    # OIDCAuthMiddleware) instead of decoding an unverified JWT.  Using
    # verify_signature=False allowed an attacker to forge a JWT with any sub
    # and invalidate another user's Valkey cache entry.  If the access token
    # was expired, request.state.user is None and we skip cache invalidation
    # — acceptable because the cache entry has its own TTL and will expire.
    user = getattr(request.state, "user", None)
    if user and valkey:
        sub = user.get("sub")
        if sub:
            with contextlib.suppress(Exception):
                await valkey.delete(f"auth:user:{sub}")

    logger.info("logout_success", action="logout", result="success")

    response = JSONResponse(status_code=200, content={"message": "Logged out successfully"})
    _clear_refresh_cookie(response)
    return response


@router.get("/me")
async def me(request: Request) -> Response:
    """Return current user identity from validated access_token (F-06)."""
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")
    settings = request.app.state.settings
    oidc_config = getattr(request.app.state, "oidc_config", None)
    valkey = getattr(request.app.state, "valkey", None)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "missing_token", "detail": "Authorization: Bearer <token> required"},
        )

    access_token = auth_header[7:]

    if oidc_config is None:
        return JSONResponse(status_code=503, content={"error": "oidc_unavailable"})

    try:
        unverified_header = jwt.get_unverified_header(access_token)
        kid = unverified_header.get("kid", "default")
        public_key = oidc_config.public_keys.get(kid) or next(iter(oidc_config.public_keys.values()), None)
        if public_key is None:
            raise jwt.InvalidTokenError("No matching public key in JWKS")
        claims: dict[str, Any] = jwt.decode(  # type: ignore[no-any-return]
            access_token,
            public_key,
            algorithms=["RS256"],
            options={"require": ["sub", "exp", "iss"]},
            audience=settings.oidc_audience,
            issuer=oidc_config.issuer,
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("me_invalid_token", action="me", result="error", reason=str(exc))
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_token", "detail": "Access token validation failed"},
        )

    sub: str = claims["sub"]
    email: str = claims.get("email", "")
    email_verified: bool = bool(claims.get("email_verified", False))

    # Look up internal identity from Valkey cache
    user_id: str = ""
    tenant_id: str = ""
    if valkey:
        try:
            import json

            cached = await valkey.get(f"auth:user:{sub}")
            if cached:
                user_data: dict[str, str] = json.loads(cached)
                user_id = user_data.get("user_id", "")
                tenant_id = user_data.get("tenant_id", "")
        except Exception:  # noqa: S110 — fail-open on Valkey error
            pass

    logger.info("me_success", action="me", sub=sub, result="success")

    return JSONResponse(
        status_code=200,
        content={
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "sub": sub,
            "email_verified": email_verified,
        },
    )


# ── Registration + WebSocket token (PRD-0028 Wave S9-2) ─────────────────────


@router.get("/register")
async def register(request: Request) -> Response:
    """Redirect browser to Zitadel self-registration page (OQ-05).

    Public endpoint — no authentication required.
    Zitadel self-registration URL: {oidc_issuer_url}/ui/console/register.
    """
    settings = request.app.state.settings
    registration_url = f"{settings.oidc_issuer_url}/ui/console/register"
    return RedirectResponse(url=registration_url, status_code=302)


@router.get("/ws-token")
async def ws_token(request: Request) -> Response:
    """Issue a 30-second short-lived internal JWT for WebSocket authentication.

    Called by the frontend immediately before opening the alert stream WebSocket.
    The returned token goes in ?token= on the WS URL (browser WS API cannot set headers).

    Auth: requires Bearer access token (normal OIDC flow).
    """
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")

    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"error": "authentication_required"})

    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        return JSONResponse(status_code=503, content={"error": "jwt_signing_unavailable"})

    # Validate required claims before issuing token (F-004: reject incomplete auth state)
    user_id = user.get("sub") or user.get("user_id")
    tenant_id = user.get("tenant_id")
    if not user_id or not tenant_id:
        logger.warning("ws_token_incomplete_claims", action="ws_token", result="error")
        return JSONResponse(status_code=401, content={"error": "incomplete_auth_claims"})

    from api_gateway.jwt_utils import issue_ws_jwt

    token = issue_ws_jwt(
        user_id=user_id,
        tenant_id=tenant_id,
        private_key=private_key,
        kid=kid,
    )

    logger.info("ws_token_issued", action="ws_token", result="success")
    return JSONResponse(status_code=200, content={"token": token, "expires_in": 30})


# ── Dev-login (development only — no Zitadel required) ─────────────────────

# Fixed UUIDs for the demo user.  Must match scripts/seed-dev-data.sql so
# the demo user already exists in portfolio_db when make seed has been run.
_DEV_USER_ID = "01900000-0000-7000-8000-000000000010"
_DEV_TENANT_ID = "01900000-0000-7000-8000-000000000001"
_DEV_SUB = "dev-user"
_DEV_EMAIL = "demo@worldview.dev"


@router.post("/dev-login")
async def dev_login(request: Request) -> Response:
    """Issue an access token for the demo user WITHOUT Zitadel.

    SECURITY GATE: This endpoint is ONLY available when ``oidc_config is None``
    (i.e., OIDC discovery was skipped because Zitadel is not running AND
    ``API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=true``).  In production, OIDC
    discovery succeeds, ``oidc_config`` is populated, and this endpoint
    returns 403.

    Returns the same response shape as ``GET /v1/auth/callback`` so the
    frontend can use an identical ``setTokens()`` call.
    """
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.auth")

    # ── Guard 1: production environment hard-block (SEC-003) ──────────────
    # Block dev-login in production regardless of OIDC configuration.
    # This prevents accidental exposure if OIDC_DISCOVERY_OPTIONAL is ever
    # mistakenly set to true in a production deployment.
    settings = getattr(request.app.state, "settings", None)
    app_env: str = getattr(settings, "app_env", "development") if settings else "development"
    if app_env == "production":
        logger.warning("dev_login_blocked_production", action="dev_login", app_env=app_env, result="error")
        return JSONResponse(
            status_code=403,
            content={
                "error": "dev_login_disabled",
                "detail": "Dev login is not available in production",
            },
        )

    # ── Guard 2: only allow when Zitadel is NOT configured ────────────────
    oidc_config = getattr(request.app.state, "oidc_config", None)
    if oidc_config is not None:
        logger.warning("dev_login_blocked", action="dev_login", result="error")
        return JSONResponse(
            status_code=403,
            content={
                "error": "dev_login_disabled",
                "detail": "Dev login is only available when OIDC is not configured",
            },
        )

    # ── Guard: RSA key must be available for JWT signing ──────────────────
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid: str = getattr(request.app.state, "rsa_kid", "default")
    if private_key is None:
        return JSONResponse(
            status_code=503,
            content={"error": "jwt_signing_unavailable"},
        )

    # ── Issue an internal JWT for the demo user ───────────────────────────
    from api_gateway.jwt_utils import issue_user_jwt

    access_token = issue_user_jwt(
        user_id=_DEV_USER_ID,
        tenant_id=_DEV_TENANT_ID,
        oidc_sub=_DEV_SUB,
        private_key=private_key,
        kid=kid,
    )

    # ── Cache demo user identity in Valkey (same as real login) ───────────
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        try:
            import json

            await valkey.set(
                f"auth:user:{_DEV_SUB}",
                json.dumps({"user_id": _DEV_USER_ID, "tenant_id": _DEV_TENANT_ID}),
                ttl=86400,  # 24 h — generous for local dev
            )
        except Exception:  # noqa: S110 — fail-open: cache miss handled on next request
            pass

    logger.info("dev_login_success", action="dev_login", user_id=_DEV_USER_ID, result="success")

    return JSONResponse(
        status_code=200,
        content={
            "access_token": access_token,
            "expires_in": 300,
            "token_type": "Bearer",
            "user": {
                "user_id": _DEV_USER_ID,
                "tenant_id": _DEV_TENANT_ID,
                "email": _DEV_EMAIL,
                "sub": _DEV_SUB,
                "email_verified": True,
            },
        },
    )
