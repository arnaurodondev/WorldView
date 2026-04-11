"""Domain types for the API Gateway — no infrastructure imports (R12)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TCH003
from typing import Any


@dataclass
class OIDCProviderConfig:
    """In-memory cache of OIDC discovery document for the upstream provider (Zitadel).

    Populated at startup via `fetch_oidc_discovery` and refreshed on JWKS cache miss.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    end_session_endpoint: str
    jwks_uri: str
    public_keys: dict[str, Any]  # kid → RSAPublicKey (typed Any to avoid cryptography import in domain)
    last_refreshed_at: datetime  # UTC-aware


@dataclass(frozen=True)
class InternalJWTClaims:
    """Typed claim set for RS256 internal JWTs issued by S9.

    Invariants:
    - ``exp > iat``
    - ``iss == "worldview-gateway"``
    - ``role in ("user", "system")``
    """

    sub: str  # user_id (UUIDv7 string) or "system"
    tenant_id: str  # UUIDv7 string; "" for system calls
    oidc_sub: str  # Zitadel subject (for traceability)
    role: str  # "user" | "system"
    jti: str  # new_uuid7() string — for replay prevention
    iat: int  # Unix timestamp UTC
    exp: int  # iat + 300 (user) or iat + 60 (system)
    kid: str  # RSA key ID (sha256 thumbprint)
    iss: str = "worldview-gateway"
