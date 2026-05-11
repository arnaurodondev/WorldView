"""Internal routes — JWKS endpoint for backend service JWT verification.

Also exposes ``POST /internal/v1/service-token`` (PLAN-0057 Wave A-1 / BP-303),
which lets background workers authenticate via a shared service-account secret
and receive a short-lived RS256 JWT signed by S9. This replaces the previous
worker → ``POST /v1/auth/dev-login`` bootstrap path that fails in production
(dev-login is hard-blocked when ``app_env == 'production'``).
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/internal")


@router.get(
    "/jwks",
    summary="Internal JWKS — public key for RS256 internal JWT verification",
    tags=["internal"],
)
async def get_jwks(request: Request) -> JSONResponse:
    """Return the JWKS for S9's internal RS256 signing key.

    Backend services fetch this endpoint at startup to verify X-Internal-JWT tokens.
    Response is cached for 1 hour (``Cache-Control: public, max-age=3600``).
    """
    jwks: dict[str, Any] | None = getattr(request.app.state, "internal_jwks", None)
    if jwks is None:
        return JSONResponse(
            content={"detail": "JWKS not available — service not fully initialized"},
            status_code=503,
        )
    return JSONResponse(content=jwks, headers={"Cache-Control": "public, max-age=3600"})


# ── Service-account JWT minting (PLAN-0057 Wave A-1 / BP-303) ────────────────

# Allow-list of service identities permitted to mint a service JWT. Adding a
# new caller requires both (a) appending the canonical name here AND (b)
# distributing the shared ``WORLDVIEW_SERVICE_ACCOUNT_TOKEN`` secret to the
# caller's deployment. We deliberately keep the list short and explicit
# rather than accepting any identity the caller declares — defence-in-depth
# against an attacker who somehow learns the shared secret.
_ALLOWED_SERVICE_NAMES: frozenset[str] = frozenset(
    {
        "nlp-pipeline-price-impact",
    }
)


class ServiceTokenRequest(BaseModel):
    """Request body for POST /internal/v1/service-token.

    Both fields are required and validated server-side. The Pydantic v2 ``min_length``
    constraints reject the trivially-empty payloads that an attacker is most
    likely to try first; the real authorization check is the ``compare_digest``
    on ``secret`` below.
    """

    service_name: str = Field(..., min_length=1, max_length=64)
    secret: str = Field(..., min_length=1)


@router.post(
    "/v1/service-token",
    summary="Mint a service-account RS256 internal JWT",
    tags=["internal"],
)
async def issue_service_token(request: Request, body: ServiceTokenRequest) -> JSONResponse:
    """Authenticate a worker via shared service-account secret; issue an RS256 JWT.

    Background workers (e.g. the nlp-pipeline price-impact worker) use this
    endpoint instead of ``POST /v1/auth/dev-login`` so they can authenticate
    in production deployments where dev-login is hard-blocked.

    Behaviour:
      - **200**: ``service_name`` is on the allow-list AND ``secret`` matches
        ``settings.service_account_token`` → returns
        ``{"access_token": <jwt>, "expires_in": 300, "token_type": "Bearer"}``.
      - **401**: wrong secret OR service_name not on the allow-list. Both
        conditions return the same error to avoid leaking which check failed.
      - **503**: ``settings.service_account_token`` is unset (deployment
        misconfiguration) OR the RSA private key is missing.

    SECURITY:
      - Constant-time comparison via ``secrets.compare_digest``.
      - Endpoint is **NOT** guarded by ``app_env == 'production'`` — that's
        the entire point. The shared secret IS the auth boundary.
      - Each successful mint logs ``service_token_issued`` with the
        ``service_name`` (never the secret nor the JWT itself).
    """
    from observability import get_logger  # type: ignore[import-untyped]

    logger = get_logger("api_gateway.internal")

    # ── Guard 1: settings populated and shared secret configured ──────────────
    settings = getattr(request.app.state, "settings", None)
    configured_secret_obj = getattr(settings, "service_account_token", None) if settings else None
    configured_secret: str = configured_secret_obj.get_secret_value() if configured_secret_obj is not None else ""
    if not configured_secret:
        logger.warning(
            "service_token_unconfigured",
            action="service_token",
            result="error",
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_account_unconfigured",
                "detail": "Service-account secret is not configured on the gateway",
            },
        )

    # ── Guard 2: RSA signing material available ───────────────────────────────
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid: str = getattr(request.app.state, "rsa_kid", "default")
    if private_key is None:
        return JSONResponse(
            status_code=503,
            content={"error": "jwt_signing_unavailable"},
        )

    # ── Authn: constant-time secret comparison + allow-list membership ────────
    # Combine both predicates into a single 401 response to avoid revealing
    # which check failed (per OWASP guidance for credential validation).
    secret_ok = secrets.compare_digest(body.secret, configured_secret)
    name_ok = body.service_name in _ALLOWED_SERVICE_NAMES
    if not (secret_ok and name_ok):
        # Log the candidate service_name (not the secret!) so legitimate
        # configuration errors (e.g. typo in service_name) are debuggable.
        logger.warning(
            "service_token_unauthorized",
            action="service_token",
            service_name=body.service_name,
            secret_match=secret_ok,
            name_allowed=name_ok,
            result="error",
        )
        return JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "detail": "Invalid service credentials",
            },
        )

    # ── Mint the RS256 JWT ────────────────────────────────────────────────────
    from api_gateway.jwt_utils import _SERVICE_TTL, issue_service_jwt

    access_token = issue_service_jwt(body.service_name, private_key, kid)

    logger.info(
        "service_token_issued",
        action="service_token",
        service_name=body.service_name,
        ttl_seconds=_SERVICE_TTL,
        result="success",
    )

    return JSONResponse(
        status_code=200,
        content={
            "access_token": access_token,
            "expires_in": _SERVICE_TTL,
            "token_type": "Bearer",
        },
    )
