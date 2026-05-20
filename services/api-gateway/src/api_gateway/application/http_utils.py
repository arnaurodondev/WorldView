"""Shared HTTP utilities for api-gateway route files and use cases.

Provides a thin facade over the retry/error-mapping primitives that live in
``api_gateway.clients``.  Route modules and use-case classes import from here
so they don't need to depend on the private ``_checked_get``/``_checked_post``
functions directly.

Provides:
- ``proxy_get``  — GET with automatic retry and DownstreamError → HTTPException mapping
- ``proxy_post`` — POST with optional retry and error mapping
- ``map_upstream_error``  — translate ``httpx.HTTPStatusError`` to ``HTTPException``
- ``map_network_error``   — translate ``httpx.TimeoutException``/``NetworkError`` to 503

WHY a separate module instead of putting this in clients.py:
    ``clients.py`` owns the raw ``_checked_get``/``_checked_post`` logic and the
    ``DownstreamError`` exception.  Route files and use cases should NOT import
    FastAPI primitives (``HTTPException``) from ``clients.py`` because that would
    couple the transport layer to the web framework.  ``http_utils.py`` is the
    translation boundary: it converts transport errors into HTTP responses.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from api_gateway.clients import DownstreamError, _checked_get, _checked_post

# ── Public API ─────────────────────────────────────────────────────────────────


async def proxy_get(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """GET a downstream service path with automatic retry and error mapping.

    Delegates to ``_checked_get`` which implements exponential-backoff retry
    on HTTP 500/503 (up to 3 attempts: initial + 2 retries as configured by
    ``_RETRY_DELAYS``).  4xx errors are never retried.

    Args:
        client:       Configured ``httpx.AsyncClient`` for the target service.
        service_name: Human-readable service name used in log messages and
                      ``DownstreamError.service`` (e.g. "market-data").
        path:         Absolute path on the target service (e.g. "/api/v1/quotes/123").
        headers:      Optional dict forwarded with the request (e.g. auth headers).
        params:       Optional query-string parameters.
        timeout:      Ignored — timeout is set on the ``httpx.AsyncClient`` at
                      construction time (app.py lifespan). Kept for API
                      compatibility so callers can document their intent.
        retries:      Ignored — retry count is governed by ``_RETRY_DELAYS`` in
                      clients.py (3 attempts total). Kept for API compatibility.

    Returns:
        Parsed JSON dict from the successful response.

    Raises:
        HTTPException(502): on ``DownstreamError`` (upstream returned 5xx after
            all retries, or any other non-transient error status).
        HTTPException(N): where N mirrors the upstream status code for 4xx errors
            (404 → 404, 403 → 403, etc.).
        HTTPException(503): on ``httpx.TimeoutException`` or ``httpx.NetworkError``.
    """
    # Build kwargs for _checked_get (params forwarded as a kwarg; headers
    # already has its own dedicated parameter).
    kwargs: dict[str, Any] = {}
    if params is not None:
        kwargs["params"] = params
    try:
        return await _checked_get(client, service_name, path, headers=headers, **kwargs)
    except DownstreamError as exc:
        raise _downstream_to_http(exc) from exc
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail=f"{service_name} unavailable") from exc


async def proxy_post(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    allow_retry: bool = False,
) -> dict[str, Any]:
    """POST to a downstream service path with error mapping.

    By default POST is NOT retried because POST may not be idempotent
    (create-on-retry → duplicate records). Pass ``allow_retry=True`` only
    for POST endpoints that are guaranteed idempotent (upsert-style with a
    caller-supplied key). See BP-025.

    Args:
        client:       Configured ``httpx.AsyncClient`` for the target service.
        service_name: Human-readable service name (e.g. "rag-chat").
        path:         Absolute path on the target service.
        json:         Optional body serialised as JSON.
        headers:      Optional dict forwarded with the request.
        timeout:      Ignored — timeout is set on the ``httpx.AsyncClient``
                      at construction time. Kept for API compatibility.
        allow_retry:  When ``True`` applies the same exponential-backoff retry
                      as ``proxy_get`` (only on 500/503). Default ``False``.

    Returns:
        Parsed JSON dict from the successful response.

    Raises:
        HTTPException(502): on ``DownstreamError`` for 5xx errors.
        HTTPException(N):   mirrors upstream status code for 4xx errors.
        HTTPException(503): on timeout or network failure.
    """
    kwargs: dict[str, Any] = {}
    if json is not None:
        kwargs["json"] = json
    try:
        return await _checked_post(
            client,
            service_name,
            path,
            headers=headers,
            allow_retry=allow_retry,
            **kwargs,
        )
    except DownstreamError as exc:
        raise _downstream_to_http(exc) from exc
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail=f"{service_name} unavailable") from exc


def map_upstream_error(exc: httpx.HTTPStatusError) -> HTTPException:
    """Translate an ``httpx.HTTPStatusError`` to a FastAPI ``HTTPException``.

    Used in routes that bypass ``_checked_get``/``_checked_post`` and call
    ``httpx.AsyncClient`` directly (thin-proxy routes that use
    ``resp.raise_for_status()``).

    Mapping rules:
        - 4xx upstream → same status code forwarded (the client's fault).
        - 5xx upstream → 502 Bad Gateway (upstream is broken, but our gateway
          is alive — 500 would imply *our* code crashed).

    Args:
        exc: The ``httpx.HTTPStatusError`` raised by ``response.raise_for_status()``.

    Returns:
        A ``fastapi.HTTPException`` with an appropriate status code and detail.
    """
    status = exc.response.status_code
    # 5xx from upstream → 502 (gateway received a bad response from upstream)
    if status >= 500:
        return HTTPException(
            status_code=502,
            detail=f"Upstream service error (HTTP {status})",
        )
    # 4xx → mirror the status code so the client gets the correct semantics
    return HTTPException(
        status_code=status,
        detail=exc.response.text[:200],
    )


def map_network_error(
    exc: httpx.TimeoutException | httpx.NetworkError,
    service_name: str = "upstream",
) -> HTTPException:
    """Translate an httpx network-level exception to ``HTTPException(503)``.

    Use this in thin-proxy routes that call httpx directly and need to convert
    transport errors into an HTTP response the frontend understands.

    Args:
        exc:          The ``httpx.TimeoutException`` or ``httpx.NetworkError``.
        service_name: Human-readable name used in the detail message.

    Returns:
        ``HTTPException(503)`` — Service Unavailable.
    """
    return HTTPException(
        status_code=503,
        detail=f"{service_name} unavailable",
    )


# ── Internal helpers ───────────────────────────────────────────────────────────


def _downstream_to_http(exc: DownstreamError) -> HTTPException:
    """Convert a ``DownstreamError`` raised by ``_checked_get``/``_checked_post``
    into the appropriate ``HTTPException``.

    Mapping:
        - 4xx → forward the same status code (client error).
        - 5xx → 502 Bad Gateway (upstream is broken; gateway itself is fine).

    The detail string is truncated by ``_checked_get``/``_checked_post`` to 200
    chars (F-005) before the exception is raised, so we don't truncate again.
    """
    if exc.status >= 500:
        return HTTPException(status_code=502, detail=exc.detail)
    return HTTPException(status_code=exc.status, detail=exc.detail)


__all__: list[str] = [
    "map_network_error",
    "map_upstream_error",
    "proxy_get",
    "proxy_post",
]
