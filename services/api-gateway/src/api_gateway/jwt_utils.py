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


def issue_user_jwt(
    user_id: str,
    tenant_id: str,
    oidc_sub: str,
    private_key: RSAPrivateKey,
    kid: str,
) -> str:
    """Issue a user-scoped RS256 internal JWT (valid 5 min)."""
    iat = int(utc_now().timestamp())
    payload = {
        "iss": _ISSUER,
        "sub": user_id,
        "tenant_id": tenant_id,
        "oidc_sub": oidc_sub,
        "role": "user",
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
