"""Shared helper functions used by multiple domain route modules.

Extracted from proxy.py (PLAN-0089 B-3 split). All helpers are pure
functions or thin wrappers over request state — no route registration here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from fastapi import Request

    from api_gateway.clients import ServiceClients

from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _clients(request: Request) -> ServiceClients:
    """Shortcut to get ServiceClients from app state."""
    return cast("ServiceClients", request.app.state.clients)


def _auth_headers(request: Request) -> dict[str, str]:
    """Issue a fresh RS256 internal JWT for a single downstream call.

    Called once per downstream request (not shared across parallel calls) so
    that each JWT has a unique JTI — this prevents ``InternalJWTMiddleware``
    on backend services from raising "Token replay detected" when a single
    gateway request fans out to multiple backend calls in parallel.

    Falls back to reading the pre-issued ``X-Internal-JWT`` header if RSA keys
    are not configured (e.g. unit tests that don't run the full lifespan).
    """
    user = getattr(request.state, "user", None)
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if user is not None and private_key is not None and kid is not None:
        # F-Q1-02: forward the role claim from the OIDC/dev-login payload
        # into the internal JWT. Without this, every admin endpoint on every
        # backend service returned 403 because the role defaulted to "user".
        role = user.get("role") or "user"
        token = issue_user_jwt(
            user_id=user.get("user_id", ""),
            tenant_id=user.get("tenant_id", ""),
            oidc_sub=user.get("sub", ""),
            private_key=private_key,
            kid=kid,
            role=role,
        )
        return {"X-Internal-JWT": token}
    # Fallback: read the pre-issued JWT (tests without RSA keys / system routes)
    internal_jwt = request.headers.get("X-Internal-JWT")
    return {"X-Internal-JWT": internal_jwt} if internal_jwt else {}


def _system_headers(request: Request) -> dict[str, str]:
    """Issue a system-level JWT for public proxy routes.

    Backend services require ``X-Internal-JWT`` on every API request
    (InternalJWTMiddleware).  For public endpoints that don't have a real
    user, the gateway issues a short-lived system JWT (nil-UUID user/tenant,
    role=system) so the backend can authenticate the request.

    Returns an empty dict if RSA keys are not configured (tests without
    lifespan) — the downstream mock will not check for the header.
    """
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        return {}
    token = issue_public_jwt(private_key, kid)
    return {"X-Internal-JWT": token}


def _portfolio_headers(request: Request) -> dict[str, str]:
    """Auth headers for S1 Portfolio service.

    S1 now reads tenant_id/user_id from the JWT (InternalJWTMiddleware).
    Only X-Internal-JWT is forwarded (F-MAJOR-013 remediation).
    """
    return _auth_headers(request)


def _document_headers(request: Request) -> dict[str, str]:
    """Build headers for S4 document requests.

    Extends _auth_headers() with X-Tenant-ID and X-User-ID so S4's
    header-based dependency extractors receive the tenant/user identity
    in addition to the internal JWT payload.

    WHY explicit headers: S4's documents router defines Depends(tenant_id_dep)
    and Depends(user_id_dep) which first try X-Tenant-ID / X-User-ID headers,
    then fall back to request.state (populated by InternalJWTMiddleware).
    Forwarding both is belt-and-suspenders and makes the S4 dep resolution
    independent of whether S4's own middleware ran.
    """
    headers = _auth_headers(request)
    user = getattr(request.state, "user", None) or {}
    if isinstance(user, dict):
        tenant_id = user.get("tenant_id", "")
        user_id = user.get("user_id", "") or user.get("sub", "")
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id
        if user_id:
            headers["X-User-ID"] = user_id
    return headers


__all__: list[str] = [
    "_auth_headers",
    "_clients",
    "_document_headers",
    "_portfolio_headers",
    "_system_headers",
]
