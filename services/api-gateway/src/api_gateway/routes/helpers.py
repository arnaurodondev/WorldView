"""Shared helper functions used by multiple domain route modules.

Extracted from proxy.py (PLAN-0089 B-3 split). All helpers are pure
functions or thin wrappers over request state — no route registration here.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import HTTPException, Response
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

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

# NEW-5 (2026-07-06 r1-final-exhaustive-qa, LOW resilience): the gateway must
# convert *transport-level* failures to an upstream service (connection refused,
# DNS "Name or service not known" during a container recreate, read/connect
# timeout) into a graceful 503/504 — NOT an unhandled 500 that leaks a full
# ``httpx.ConnectError`` traceback to the browser. This is distinct from BUG-7,
# which sanitizes upstream *responses* (5xx bodies): here there is no upstream
# response at all because the connection never completed.
#
# Mapping: ``httpx.TimeoutException`` → 504 Gateway Timeout (the upstream was
# reachable but too slow); every other ``httpx.NetworkError`` (ConnectError,
# ReadError, name-resolution failure) → 503 Service Unavailable (the upstream
# was momentarily unreachable — the client should retry with backoff).

# SSE frame emitted when the upstream connection drops *mid-stream*. Once a
# StreamingResponse has begun, the 200 response-start is already committed and
# the HTTP status can no longer be changed — so a clean ``event: error`` frame
# (no traceback, stable machine code) is the only way to signal the drop.
_SSE_UPSTREAM_DROP_FRAME = (
    b"event: error\n"
    b'data: {"code":"UPSTREAM_UNAVAILABLE",'
    b'"message":"The chat service connection was interrupted. Please try again."}\n\n'
)

# Explicit SSE cache headers (PLAN-0099 W4) — mirror the rag-chat service so the
# gateway middleware stack (Prometheus, RequestId) does not buffer the upstream
# chunks. Without these, the frontend receives the entire answer in a single
# chunk instead of token-by-token. Shared by every rag-chat SSE proxy route.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _transport_error_to_http(exc: Exception, service_name: str) -> HTTPException:
    """Map a transport-level httpx error to a graceful ``HTTPException`` (NEW-5).

    ``httpx.TimeoutException`` → 504 (upstream reachable but too slow); any other
    ``httpx.NetworkError`` (ConnectError / name-resolution / ReadError) → 503
    (upstream momentarily unreachable). The detail is a generic, caller-safe
    string — the raw exception (which may contain internal hostnames / the DNS
    error) is never surfaced to the client.
    """
    if isinstance(exc, httpx.TimeoutException):
        return HTTPException(status_code=504, detail=f"{service_name} timed out")
    return HTTPException(status_code=503, detail=f"{service_name} unavailable")


async def rag_chat_request(
    clients: ServiceClients,
    method: str,
    path: str,
    *,
    service_name: str = "rag-chat",
    **kwargs: Any,
) -> httpx.Response:
    """Call an S8 rag-chat endpoint, mapping transport failures to 503/504 (NEW-5).

    Thin wrapper over ``clients.rag_chat.<method>(path, **kwargs)`` that catches
    connection/resolution/timeout errors and re-raises them as a graceful
    ``HTTPException`` (503 unavailable / 504 timeout) instead of letting the raw
    ``httpx.ConnectError`` propagate to FastAPI as an unhandled 500 with a leaked
    traceback (NEW-5, 2026-07-06 QA).

    Genuine 4xx/5xx *responses* from rag-chat are returned unchanged — the caller
    still routes them through ``proxy_json_response`` (which applies the BUG-7 5xx
    sanitisation), so error-passthrough semantics are preserved.

    Args:
        clients:      The request-scoped ``ServiceClients`` (from ``_clients``).
        method:       httpx verb name: ``"get"``, ``"post"``, ``"delete"``,
                      ``"patch"``.
        path:         Absolute path on rag-chat (e.g. ``/api/v1/chat``).
        service_name: Human-readable name used in the graceful error detail.
        **kwargs:     Forwarded verbatim to the httpx method (``content``,
                      ``headers``, ``params`` ...).
    """
    client_method = getattr(clients.rag_chat, method)
    try:
        return cast("httpx.Response", await client_method(path, **kwargs))
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise _transport_error_to_http(exc, service_name) from exc


async def proxy_rag_chat_stream(
    clients: ServiceClients,
    path: str,
    *,
    content: bytes,
    headers: dict[str, str],
    rewrite: Callable[[bytes], bytes] | None = None,
    service_name: str = "rag-chat",
) -> StreamingResponse:
    """Proxy an S8 rag-chat SSE endpoint with airtight transport-error handling.

    NEW-5 root fix for ``routes/chat.py:79``: the previous streaming proxy opened
    the upstream connection *inside* the ``StreamingResponse`` body generator.
    Starlette commits the 200 response-start before the generator runs, so a
    ``httpx.ConnectError`` raised on the first ``async with client.stream(...)``
    (rag-chat momentarily unresolvable during a recreate) escaped as an unhandled
    500 with a full traceback.

    Here we **pre-open** the stream (send the request, receive the response
    headers) *before* constructing the ``StreamingResponse``:

    - Connect/resolve/timeout failure at open time → surfaces as a graceful 503
      (unavailable) or 504 (timeout) ``HTTPException`` — the client gets a clean
      JSON error, no traceback, the 200 is never sent.
    - A drop *mid-stream* (after tokens have started) can no longer change the
      status; we emit a single clean ``event: error`` SSE frame and stop.

    Args:
        clients:      Request-scoped ``ServiceClients``.
        path:         Absolute rag-chat SSE path (e.g. ``/api/v1/chat/stream``).
        content:      Raw request body bytes to forward.
        headers:      Headers to forward (auth + Content-Type).
        rewrite:      Optional per-chunk transform (e.g. the Theme-E injection
                      block re-wording). ``None`` = pass chunks through verbatim.
        service_name: Human-readable name used in the graceful error detail.

    Returns:
        A ``StreamingResponse`` (``text/event-stream``) once the upstream stream
        is open.

    Raises:
        HTTPException(503|504): if the upstream connection cannot be established.
    """
    # AsyncExitStack lets us enter the stream context here (surfacing connect
    # errors synchronously) yet hand ownership to the body generator, which
    # closes it via ``async with stack`` when iteration finishes.
    stack = AsyncExitStack()
    try:
        resp = await stack.enter_async_context(clients.rag_chat.stream("POST", path, content=content, headers=headers))
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        # Nothing was opened successfully — release the (empty) stack and map the
        # transport error to a clean 503/504 BEFORE any StreamingResponse exists.
        await stack.aclose()
        raise _transport_error_to_http(exc, service_name) from exc

    async def _body() -> AsyncIterator[bytes]:
        async with stack:
            try:
                async for chunk in resp.aiter_bytes():
                    yield rewrite(chunk) if rewrite is not None else chunk
            except (httpx.TimeoutException, httpx.NetworkError):
                # Mid-stream drop: the 200 is already committed so we cannot
                # change the status. Emit a clean, traceback-free SSE error frame
                # and stop iterating — the frontend surfaces "please try again".
                yield _SSE_UPSTREAM_DROP_FRAME

    return StreamingResponse(
        _body(),
        media_type="text/event-stream",
        headers=dict(_SSE_HEADERS),
    )


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
    "proxy_rag_chat_stream",
    "rag_chat_request",
]
