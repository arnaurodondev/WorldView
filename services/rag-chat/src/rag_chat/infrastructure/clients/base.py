"""BaseUpstreamClient — shared httpx wrapper for all upstream service adapters (T-E-3-01).

PLAN-0103 W2 (BP-623): transport-layer failures (connect refused, DNS, timeout,
upstream 5xx) are NO LONGER silently collapsed to ``{}``.  They now raise
``UpstreamTransportError``, a ``BaseException`` subclass (not ``Exception``) so
the per-handler ``except Exception: return []`` guards do NOT catch it.  The
exception is intercepted centrally by ``ToolExecutor.execute`` which converts it
into a ``TransportErrorMarker`` sentinel — that downstream pipeline turns the
SSE ``tool_result`` ``status`` into ``"transport_error"`` (instead of
``"empty"``) and injects a structured ``role="tool"`` message so the LLM can
correctly say "I cannot reach <upstream> right now" instead of "no data found".

Legitimate HTTP 4xx (client error) responses continue to return ``{}`` — those
indicate the caller's request was malformed or the resource genuinely does not
exist, which is closer to "no rows" than to "upstream is down".  Promoting 4xx
to transport_error would over-trigger the user-facing outage messaging.
"""

from __future__ import annotations

import time

import httpx
import structlog  # type: ignore[import-untyped]

# ``UpstreamTransportError`` lives in the application layer so that the
# orchestrator and ``ToolExecutor`` can ``except`` it without crossing the
# LAYER-APP-ISOLATION boundary (R12 / IG-LAYER-002). Re-exported here so
# existing infrastructure call sites that ``raise UpstreamTransportError``
# (and external callers that import it from ``infrastructure/clients/base``)
# keep working unchanged. See ``application/pipeline/transport_error.py``
# for the actual class definition.
#
# WHY the class is a BaseException (not Exception): every tool handler in
# ``rag_chat/application/pipeline/handlers/*`` wraps upstream calls in
# ``try/except Exception: return []`` for R9 safe-degradation.  If
# ``UpstreamTransportError`` inherited from ``Exception``, those guards would
# swallow it before it ever reached ``ToolExecutor.execute`` — re-introducing
# the exact BP-623 silent-collapse pattern we are fixing here.  BaseException
# bypasses ``except Exception`` (same mechanism used by KeyboardInterrupt and
# SystemExit) but is still caught by the executor's explicit
# ``except UpstreamTransportError`` branch.
from rag_chat.application.pipeline.transport_error import UpstreamTransportError

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _raise_transport_error_from_httpx(
    exc: BaseException,
    *,
    path: str,
    elapsed_ms: int,
) -> None:
    """Translate an httpx exception into ``UpstreamTransportError`` and raise.

    Centralised so hand-rolled clients (market_tape, earnings, s1) can share
    the exact same reason taxonomy as ``BaseUpstreamClient._get / _post``.

    Why split ConnectTimeout from TimeoutException: connect-timeout is closer
    to "host unreachable" (often DNS or network partition) and benefits from
    the same user-facing copy as ``upstream_unreachable``; the read/write
    timeout shape is meaningfully different (upstream is up but slow to
    respond) so we keep ``upstream_timeout`` for those.
    """
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.RemoteProtocolError):
        raise UpstreamTransportError(
            "upstream_unreachable",
            path=path,
            elapsed_ms=elapsed_ms,
        ) from exc
    if isinstance(exc, httpx.TimeoutException):
        raise UpstreamTransportError(
            "upstream_timeout",
            path=path,
            elapsed_ms=elapsed_ms,
        ) from exc
    if isinstance(exc, httpx.HTTPStatusError):
        sc = exc.response.status_code
        if sc >= 500:
            raise UpstreamTransportError(
                "upstream_5xx",
                path=path,
                elapsed_ms=elapsed_ms,
                status_code=sc,
            ) from exc
        # 4xx falls through — caller decides how to surface it.
        return
    if isinstance(exc, httpx.RequestError):
        # Any other RequestError (e.g. network, SSL) — treat as unreachable.
        raise UpstreamTransportError(
            "upstream_unreachable",
            path=path,
            elapsed_ms=elapsed_ms,
        ) from exc
    # Not an httpx error — let the caller decide.
    return


class BaseUpstreamClient:
    """Thin async HTTP wrapper with structured-log error handling.

    Sub-classes call ``_post`` / ``_get`` and map the raw dict response
    into typed domain objects.  HTTP 4xx errors return ``{}`` so handlers
    receive a safe empty value; transport failures (connect / timeout / 5xx)
    raise ``UpstreamTransportError`` (BaseException) which propagates past
    handler-level ``except Exception`` guards up to ``ToolExecutor.execute``.
    """

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _post(
        self,
        path: str,
        payload: dict,
        *,
        extra_headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | float | None = None,
    ) -> dict:
        """POST *path* with JSON *payload*.

        Returns ``{}`` on HTTP 4xx (client error / not found).  Raises
        ``UpstreamTransportError`` on connect failure, timeout, or HTTP 5xx.

        ``timeout`` (EMBED-RESIL 2026-07-07): optional per-request override of
        the client-level timeout. Pass an explicit ``httpx.Timeout`` (BP-235 —
        distinct connect/read/write/pool) for hops whose read latency differs
        from the shared default (e.g. the embed hop's slow remote-model call).
        ``None`` keeps the client's construction-time default unchanged.
        """
        # WHY: Propagate X-Internal-JWT from the current request context to upstream
        # service calls (S6, S7). Without this, S6/S7 return 401 since they validate
        # X-Internal-JWT via InternalJWTMiddleware (PRD-0025).
        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = dict(extra_headers or {})
        jwt = get_current_jwt()
        if jwt and "X-Internal-JWT" not in headers:
            headers["X-Internal-JWT"] = jwt
        # FIX-LIVE-S (2026-05-25): S9-proxied gateway routes (e.g.
        # /v1/fundamentals/economic-calendar, top-movers) gate behind
        # ``request.state.user`` populated by OIDCAuthMiddleware from the
        # ``Authorization: Bearer`` header.  In dev mode the gateway also
        # accepts our internal JWT as Bearer (validates iss=worldview-gateway
        # + aud=worldview-internal).  Without this, rag-chat's calls to those
        # routes returned 401 (Q5 macro-Tesla USELESS verdict).  In prod the
        # gateway silently ignores invalid bearers (sets user=None), so this
        # is a no-op for production until a service-to-service auth path is
        # added.  Only set when caller did not already provide one.
        if jwt and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {jwt}"

        t0 = time.monotonic()
        try:
            # Only pass ``timeout`` when a caller supplied an explicit override,
            # so every existing hop keeps its construction-time client timeout.
            if timeout is None:
                resp = await self._client.post(path, json=payload, headers=headers)
            else:
                resp = await self._client.post(path, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            sc = exc.response.status_code
            if sc >= 500:
                logger.warning("upstream_5xx", path=path, status=sc, elapsed_ms=elapsed)
                _raise_transport_error_from_httpx(exc, path=path, elapsed_ms=elapsed)
            logger.warning("upstream_4xx", path=path, status=sc, elapsed_ms=elapsed)
            return {}
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning(
                "upstream_transport_error",
                path=path,
                elapsed_ms=elapsed,
                exc_type=type(exc).__name__,
            )
            _raise_transport_error_from_httpx(exc, path=path, elapsed_ms=elapsed)
            return {}  # pragma: no cover — unreachable; raise above always fires

    async def _get(
        self,
        path: str,
        params: dict | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """GET *path* with optional query *params*.

        Returns ``{}`` on HTTP 4xx.  Raises ``UpstreamTransportError`` on
        connect failure, timeout, or HTTP 5xx (BP-623 disambiguation).
        """
        # WHY: Propagate X-Internal-JWT from the current request context to upstream
        # service calls (S6, S7). Without this, S6/S7 return 401 since they validate
        # X-Internal-JWT via InternalJWTMiddleware (PRD-0025).
        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = dict(extra_headers or {})
        jwt = get_current_jwt()
        if jwt and "X-Internal-JWT" not in headers:
            headers["X-Internal-JWT"] = jwt
        # FIX-LIVE-S (2026-05-25): see ``_post`` for the rationale — S9-proxied
        # gateway routes require Bearer auth populating request.state.user.
        if jwt and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {jwt}"

        t0 = time.monotonic()
        try:
            resp = await self._client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            sc = exc.response.status_code
            if sc >= 500:
                logger.warning("upstream_5xx", path=path, status=sc, elapsed_ms=elapsed)
                _raise_transport_error_from_httpx(exc, path=path, elapsed_ms=elapsed)
            logger.warning("upstream_4xx", path=path, status=sc, elapsed_ms=elapsed)
            return {}
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            logger.warning(
                "upstream_transport_error",
                path=path,
                elapsed_ms=elapsed,
                exc_type=type(exc).__name__,
            )
            _raise_transport_error_from_httpx(exc, path=path, elapsed_ms=elapsed)
            return {}  # pragma: no cover

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()


__all__ = [
    "BaseUpstreamClient",
    "UpstreamTransportError",
    "_raise_transport_error_from_httpx",
]
