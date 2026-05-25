"""BaseUpstreamClient — shared httpx wrapper for all upstream service adapters (T-E-3-01).

All errors (timeout, HTTP 4xx/5xx, connection refused) are caught and logged.
Methods return empty dicts or lists — never raise to the caller (R9 safe degradation).
"""

from __future__ import annotations

import httpx
import structlog  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BaseUpstreamClient:
    """Thin async HTTP wrapper with structured-log error handling.

    Sub-classes call ``_post`` / ``_get`` and map the raw dict response
    into typed domain objects.  Any network or HTTP error returns an empty
    dict so callers always receive a safe value.
    """

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _post(
        self,
        path: str,
        payload: dict,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """POST *path* with JSON *payload*.  Returns ``{}`` on any error."""
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

        try:
            resp = await self._client.post(path, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "upstream_http_error",
                path=path,
                status=exc.response.status_code,
            )
            return {}
        except httpx.RequestError as exc:
            logger.warning("upstream_request_error", path=path, error=str(exc))
            return {}

    async def _get(
        self,
        path: str,
        params: dict | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """GET *path* with optional query *params*.  Returns ``{}`` on any error."""
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

        try:
            resp = await self._client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "upstream_http_error",
                path=path,
                status=exc.response.status_code,
            )
            return {}
        except httpx.RequestError as exc:
            logger.warning("upstream_request_error", path=path, error=str(exc))
            return {}

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
