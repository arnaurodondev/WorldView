"""RS256 internal JWT utilities for the API Gateway.

Issues and validates internal JWTs used by backend services to authenticate
requests proxied through S9.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

_ISSUER = "worldview-gateway"
_USER_TTL = 300  # 5 minutes
_SYSTEM_TTL = 60  # 1 minute
_SERVICE_TTL = 300  # 5 minutes — service-account JWTs minted by /internal/v1/service-token
_PUBLIC_TTL = 60  # 1 minute — short-lived JWT for public proxy routes
_WS_TTL = 30  # 30 seconds — short-lived for WebSocket URL token exposure

# Nil UUID used as user_id and tenant_id for public/anonymous proxy requests.
# Backends recognise this as a system-level request with no real user context.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def issue_user_jwt(
    user_id: str,
    tenant_id: str,
    oidc_sub: str,
    private_key: RSAPrivateKey,
    kid: str,
    role: str | None = None,
) -> str:
    """Issue a user-scoped RS256 internal JWT (valid 5 min).

    F-Q1-02: ``role`` is optional and defaults to ``"user"``. Callers that
    have determined the user is an admin (e.g. via the OIDC payload or a
    dev-admin allow-list) pass ``role="admin"`` so backends can authorize
    admin-only endpoints (``request.state.role`` is set by the InternalJWT
    middleware from this claim).
    """
    iat = int(utc_now().timestamp())
    payload = {
        "iss": _ISSUER,
        "aud": "worldview-internal",  # DEF-002: audience claim prevents cross-service token reuse
        "sub": user_id,
        "tenant_id": tenant_id,
        "oidc_sub": oidc_sub,
        "role": role or "user",
        "jti": str(new_uuid7()),
        "iat": iat,
        "exp": iat + _USER_TTL,
        "kid": kid,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})  # type: ignore[no-any-return]


def issue_system_jwt(
    oidc_sub: str,
    private_key: RSAPrivateKey,
    kid: str,
) -> str:
    """Issue a system-scoped RS256 internal JWT for S9→S1 provisioning (valid 60 s)."""
    iat = int(utc_now().timestamp())
    payload = {
        "iss": _ISSUER,
        "aud": "worldview-internal",  # DEF-002: audience claim prevents cross-service token reuse
        "sub": "system",
        "tenant_id": "",
        "oidc_sub": oidc_sub,
        "role": "system",
        "jti": str(new_uuid7()),
        "iat": iat,
        "exp": iat + _SYSTEM_TTL,
        "kid": kid,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})  # type: ignore[no-any-return]


def issue_service_jwt(
    service_name: str,
    private_key: RSAPrivateKey,
    kid: str,
    *,
    ttl_seconds: int = _SERVICE_TTL,
) -> str:
    """Issue a service-account RS256 internal JWT (default TTL 5 min).

    PLAN-0057 Wave A-1 / BP-303: replaces the worker → ``POST /v1/auth/dev-login``
    bootstrap path that fails in production (dev-login is hard-blocked when
    ``app_env == 'production'``). Background workers authenticate to S9 with a
    shared service-account secret and receive an RS256 JWT that other backends
    verify against the gateway JWKS exactly the same way they verify a user
    token — preserving the PRD-0025 invariant that S9 is the only signer.

    The minted JWT carries:
      - ``sub = "service:<service_name>"`` so downstream logs surface the caller
      - ``tenant_id = "system"``           — system-scope, never a real tenant
      - ``role = "system"``                — backends recognise as system traffic
      - ``oidc_sub = "service:<service_name>"`` for log continuity with user JWTs
    """
    iat = int(utc_now().timestamp())
    sub_value = f"service:{service_name}"
    payload = {
        "iss": _ISSUER,
        "aud": "worldview-internal",  # DEF-002: audience claim prevents cross-service token reuse
        "sub": sub_value,
        "tenant_id": "system",
        "oidc_sub": sub_value,
        "role": "system",
        "service_name": service_name,
        "jti": str(new_uuid7()),
        "iat": iat,
        "exp": iat + ttl_seconds,
        "kid": kid,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})  # type: ignore[no-any-return]


def issue_public_jwt(
    private_key: RSAPrivateKey,
    kid: str,
) -> str:
    """Issue a system-level RS256 JWT for public proxy routes (valid 60 s).

    Used when the gateway proxies a public (no-auth) endpoint to a backend
    service that still requires a valid ``X-Internal-JWT``.  The JWT carries
    a nil UUID for user_id/tenant_id and ``role: "system"`` so backends can
    distinguish system-level traffic from real user requests.
    """
    iat = int(utc_now().timestamp())
    payload = {
        "iss": _ISSUER,
        "aud": "worldview-internal",  # DEF-002: audience claim prevents cross-service token reuse
        "sub": "system:api-gateway",
        "user_id": _NIL_UUID,
        "tenant_id": _NIL_UUID,
        "role": "system",
        "jti": str(new_uuid7()),
        "iat": iat,
        "exp": iat + _PUBLIC_TTL,
        "kid": kid,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})  # type: ignore[no-any-return]


def issue_ws_jwt(
    user_id: str,
    tenant_id: str,
    private_key: RSAPrivateKey,
    kid: str,
) -> str:
    """Issue a 30-second short-lived RS256 JWT for WebSocket authentication.

    Why 30s TTL (not 15 min like the access token):
    - The token appears in the WebSocket URL (?token=) and therefore in server logs
    - Short TTL limits log-based token exposure to a narrow window
    - Frontend fetches a fresh token before each WebSocket connection attempt
    """
    iat = int(utc_now().timestamp())
    payload = {
        "iss": _ISSUER,
        "aud": "worldview-internal",  # DEF-002: audience claim prevents cross-service token reuse
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": "user",
        "scope": "alerts:stream",
        "jti": str(new_uuid7()),
        "iat": iat,
        "exp": iat + _WS_TTL,
        "kid": kid,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})  # type: ignore[no-any-return]


def decode_internal_jwt(token: str, public_key: RSAPublicKey) -> dict[str, Any]:
    """Decode and validate an RS256 internal JWT.

    Raises ``jwt.InvalidTokenError`` on any failure (expired, bad issuer, etc.).
    """
    return jwt.decode(  # type: ignore[no-any-return]
        token,
        public_key,
        algorithms=["RS256"],
        # DEF-002: require aud claim and validate it matches the internal audience.
        # This prevents a valid JWT intended for one service from being replayed at another.
        options={"require": ["iss", "sub", "exp", "iat", "jti", "aud"]},
        issuer=_ISSUER,
        audience="worldview-internal",
    )
