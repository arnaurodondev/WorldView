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
        options={"require": ["iss", "sub", "exp", "iat", "jti"]},
        issuer=_ISSUER,
    )
