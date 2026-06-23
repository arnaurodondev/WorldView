"""Shared helper functions used by multiple domain route modules.

Extracted from proxy.py (PLAN-0089 B-3 split). All helpers are pure
functions or thin wrappers over request state — no route registration here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import Response

if TYPE_CHECKING:
    import httpx
    from fastapi import Request

    from api_gateway.clients import ServiceClients

from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# BUG-7 (2026-06-22 backend-e2e-coverage-gaps audit, HIGH security):
# The gateway must NEVER leak a backend service's raw 5xx response body to the
# browser. Upstream 5xx bodies routinely contain stack traces, SQL fragments,
# internal hostnames, and Pydantic validation dumps — all internal detail that
# an attacker can use for reconnaissance. The documented invariant
# (docs/services/api-gateway.md "Error Standardization": "5xx → Generic
# 'Internal server error' (never leak internals)") requires the gateway to
# replace any upstream 5xx with a generic envelope and log the real detail
# server-side instead.
#
# 4xx and 2xx are passed through verbatim: client errors (400/401/403/404/422)
# carry caller-safe, actionable detail that the frontend depends on, and 2xx is
# the normal success body.

# Generic body returned to clients in place of any upstream 5xx body. JSON so the
# frontend's error-handling (which expects {"detail": ...}) keeps working.
_SANITIZED_UPSTREAM_BODY = b'{"detail":"upstream service error"}'


def _infer_service_name(resp: httpx.Response) -> str:
    """Best-effort downstream service label from the response's request URL.

    Used only for the server-side log entry when sanitizing a 5xx — never
    surfaced to the client. The downstream httpx clients are constructed with
    per-service base URLs (e.g. ``http://portfolio:8000``), so the URL host is a
    reliable, zero-maintenance label that stays correct even for route files
    that fan out to several services. Falls back to ``"upstream"`` if the
    request URL is unavailable (e.g. a synthesised response in a unit test).
    """
    try:
        host = resp.request.url.host
        return host or "upstream"
    except (RuntimeError, AttributeError):
        # httpx raises RuntimeError if .request was never set on the response.
        return "upstream"


def proxy_json_response(
    request: Request,
    resp: httpx.Response,
    *,
    service_name: str | None = None,
    media_type: str = "application/json",
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """Forward a downstream JSON response to the client, sanitizing 5xx bodies.

    This is the single chokepoint for the ~122 thin-proxy routes that used to do
    ``return Response(content=resp.content, status_code=resp.status_code,
    media_type="application/json")`` — a raw pass-through that leaked upstream
    5xx error bodies (stack traces / SQL / internal detail) straight to the
    browser (BUG-7).

    Behaviour:

    - **2xx / 3xx / 4xx**: passed through unchanged. Client errors carry
      caller-safe detail the frontend relies on; we mirror the status code and
      body exactly (preserving existing 4xx semantics).
    - **5xx**: the real upstream body is logged server-side (structlog, with the
      request_id) and the client receives a generic ``{"detail":"upstream
      service error"}`` envelope. The status code is normalised to 502 (Bad
      Gateway) — the gateway itself is alive; the upstream is broken — except
      503 (Service Unavailable), which is forwarded as-is so clients can honour
      retry/backoff semantics.

    Args:
        request:      The incoming request (used for the X-Request-ID
                      correlation id in the server-side log).
        resp:         The ``httpx.Response`` from the downstream service.
        service_name: Optional explicit downstream name for the log entry. When
                      omitted it is inferred from the response's request URL host
                      (see ``_infer_service_name``).
        media_type:   Content-Type for the forwarded (non-5xx) body. Defaults to
                      ``application/json``; pass e.g. ``"text/csv"`` for export
                      routes. A sanitized 5xx is ALWAYS returned as JSON
                      (``{"detail":...}``) regardless of this value.
        extra_headers: Optional extra response headers (e.g. ``Cache-Control``,
                      ``Content-Disposition``) applied to non-5xx responses only.
                      They are deliberately dropped on a sanitized 5xx — an error
                      envelope must never be cached or treated as a file download.

    Returns:
        A FastAPI ``Response`` safe to return to the client.
    """
    status = resp.status_code
    if status >= 500:
        # Correlation id: same source as observability.error_capture so the
        # client-facing generic error can be tied back to this server log line.
        request_id = request.headers.get("X-Request-ID", "")
        resolved_service = service_name or _infer_service_name(resp)
        # Log the REAL upstream detail server-side only — never to the client.
        # Truncate to keep log lines bounded; the full body is in the upstream's
        # own logs if deeper forensics are needed.
        logger.warning(
            "upstream_5xx_sanitized",
            service=resolved_service,
            upstream_status=status,
            request_id=request_id,
            path=str(request.url.path),
            # resp.text decodes the body; cap at 500 chars for the log only.
            upstream_detail=resp.text[:500],
        )
        # 503 is forwarded so clients keep retry/backoff semantics; every other
        # 5xx becomes a generic 502 (the gateway is alive, the upstream is not).
        # No extra_headers / custom media_type here: a sanitized error is plain
        # JSON and must not be cached or downloaded as a file.
        client_status = 503 if status == 503 else 502
        return Response(
            content=_SANITIZED_UPSTREAM_BODY,
            status_code=client_status,
            media_type="application/json",
        )
    # 2xx/3xx/4xx — safe to forward verbatim (mirrors prior behaviour exactly).
    return Response(
        content=resp.content,
        status_code=status,
        media_type=media_type,
        headers=extra_headers or None,
    )


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
    "proxy_json_response",
]
