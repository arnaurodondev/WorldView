"""InternalJWTMiddleware — RS256 internal JWT verifier for backend services.

Validates the ``X-Internal-JWT`` header issued by S9 (api-gateway) on every
proxied request. Sets ``request.state.tenant_id``, ``request.state.user_id``,
and ``request.state.role`` for downstream route handlers.

Health/metrics paths are skipped. On missing or invalid JWT, returns HTTP 401.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast

import jwt
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

logger = get_logger(__name__)  # type: ignore[no-any-return]

_SKIP_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/readyz",
        "/internal/v1/health",
    }
)
_SKIP_PREFIXES: tuple[str, ...] = ("/health", "/metrics", "/readyz")

_JWKS_REFRESH_INTERVAL_SECONDS = 3600  # 1 hour


class InternalJWTMiddleware(BaseHTTPMiddleware):
    """Validate ``X-Internal-JWT`` (RS256) on every non-health S8 request.

    Usage (in ``create_app``)::

        middleware = InternalJWTMiddleware(app, jwks_url=settings.api_gateway_url + "/internal/jwks")
        # Call await middleware.startup() in lifespan before yield.
        app.add_middleware(InternalJWTMiddleware, jwks_url=...)

    The middleware stores the public key in ``app.state._internal_jwt_public_key``
    so that the refresh background task can update it without recreating the
    middleware instance.
    """

    def __init__(self, app: Any, jwks_url: str, *, skip_verification: bool = False) -> None:
        super().__init__(app)
        self._jwks_url = jwks_url
        self._public_key: RSAPublicKey | None = None
        self._refresh_task: asyncio.Task | None = None
        self._skip_verification = skip_verification

        if self._skip_verification:
            logger.warning(  # type: ignore[no-any-return]
                "internal_jwt_skip_verification_enabled",
                detail=(
                    "InternalJWTMiddleware signature verification is DISABLED. "
                    "This MUST NOT be used in production — any forged JWT will be accepted."
                ),
            )

    async def startup(self) -> None:
        """Fetch JWKS from S9 at startup with up to 3 retries (3-second sleep between attempts)."""
        for attempt in range(3):
            try:
                key = await self._fetch_public_key()
                self._public_key = key
                # BP-159: Store on app.state so the serving instance can access it
                # (Starlette BaseHTTPMiddleware creates a separate instance for dispatch)
                if hasattr(self, "app") and hasattr(self.app, "state"):
                    self.app.state._internal_jwt_public_key = key
                logger.info(  # type: ignore[no-any-return]
                    "internal_jwt_public_key_loaded",
                    jwks_url=self._jwks_url,
                )
                self._refresh_task = asyncio.ensure_future(self._background_refresh())
                return
            except Exception as exc:
                # S-010: do not log str(exc) directly when exc is an
                # httpx.HTTPStatusError — str() includes the response body
                # which may contain sensitive data.  Log only the status code.
                import httpx as _httpx

                _err_detail = (
                    f"HTTP {exc.response.status_code}"
                    if isinstance(exc, _httpx.HTTPStatusError)
                    else type(exc).__name__
                )
                logger.warning(  # type: ignore[no-any-return]
                    "internal_jwt_startup_fetch_failed",
                    attempt=attempt + 1,
                    error=_err_detail,
                )
                if attempt < 2:
                    await asyncio.sleep(3)

        logger.error(  # type: ignore[no-any-return]
            "internal_jwt_startup_failed_all_attempts",
            jwks_url=self._jwks_url,
            detail="Service will return 503 on all authenticated requests until JWKS is fetched.",
        )
        raise RuntimeError(f"JWKS startup failed after 3 attempts — cannot start without public key ({self._jwks_url})")

    async def _background_refresh(self) -> None:
        """Refresh the public key every hour in the background."""
        while True:
            await asyncio.sleep(_JWKS_REFRESH_INTERVAL_SECONDS)
            try:
                new_key = await self._fetch_public_key()
                self._public_key = new_key
                # BP-159: Also update app.state for the serving instance
                if hasattr(self, "app") and hasattr(self.app, "state"):
                    self.app.state._internal_jwt_public_key = new_key
                logger.info("internal_jwt_public_key_refreshed")  # type: ignore[no-any-return]
            except Exception as exc:
                # S-010: avoid str(exc) for HTTPStatusError — response body may be sensitive.
                import httpx as _httpx

                _ref_err = (
                    f"HTTP {exc.response.status_code}"
                    if isinstance(exc, _httpx.HTTPStatusError)
                    else type(exc).__name__
                )
                logger.warning("internal_jwt_public_key_refresh_failed", error=_ref_err)  # type: ignore[no-any-return]

    async def _fetch_public_key(self) -> RSAPublicKey:
        """Fetch JWKS from S9 and extract the first RSA public key."""
        import httpx
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey as _RSAPublicKey
        from jwt.algorithms import RSAAlgorithm

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(self._jwks_url)
            resp.raise_for_status()
            jwks = resp.json()

        keys = jwks.get("keys", [])
        if not keys:
            raise ValueError(f"No keys in JWKS response from {self._jwks_url}")

        # Use the first key; real implementations match by kid
        key_data = keys[0]
        pub_key = RSAAlgorithm.from_jwk(key_data)
        if not isinstance(pub_key, _RSAPublicKey):
            raise TypeError("Expected RSA public key from JWKS")
        return pub_key

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip health / metrics paths
        if path in _SKIP_PATHS or any(path.startswith(pfx) for pfx in _SKIP_PREFIXES):
            return cast("Response", await call_next(request))

        token = request.headers.get("X-Internal-JWT")
        if not token:
            return Response(
                content='{"detail":"Missing X-Internal-JWT header"}',
                status_code=401,
                media_type="application/json",
            )

        # F-001: skip_verification=True bypasses signature validation regardless of
        # whether the JWKS public key is loaded. This mode is used exclusively for
        # the eval stack (RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true) so that
        # eval_retrieval.py can call /v1/internal/retrieve without a signed JWT.
        # MUST NOT be used in production (validated at startup via config.py).
        if self._skip_verification:
            logger.debug(  # type: ignore[no-any-return]
                "internal_jwt_unverified_decode",
                detail="Decoding JWT WITHOUT signature verification (skip_verification=True).",
            )
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                # F-S002: Validate required claims even in skip_verification mode.
                # A structurally valid but claim-free JWT must not pass through —
                # empty sub+tenant_id means no identity context, which causes
                # silent multi-tenant isolation failures downstream.
                if not payload.get("sub") and not payload.get("tenant_id"):
                    logger.warning("internal_jwt_missing_claims_skip_verification")  # type: ignore[no-any-return]
                    return Response(
                        content='{"detail":"Malformed JWT: missing required claims"}',
                        status_code=401,
                        media_type="application/json",
                    )
                request.state.tenant_id = payload.get("tenant_id", "")
                request.state.user_id = payload.get("sub", "")
                request.state.role = payload.get("role", "")
            except jwt.DecodeError as exc:
                logger.warning("internal_jwt_malformed_skip_verification", error=str(exc))  # type: ignore[no-any-return]
                return Response(
                    content='{"detail":"Malformed JWT"}',
                    status_code=401,
                    media_type="application/json",
                )
            from rag_chat.infrastructure.clients.auth_context import set_current_jwt

            set_current_jwt(token)
            return cast("Response", await call_next(request))

        # BP-159: Read from app.state, not self — serving instance != startup instance
        public_key = getattr(request.app.state, "_internal_jwt_public_key", None) or self._public_key
        if public_key is None:
            logger.error(  # type: ignore[no-any-return]
                "internal_jwt_no_public_key",
                detail="JWKS public key not loaded — rejecting request (fail-closed).",
            )
            return Response(
                content='{"detail":"Service Unavailable — JWKS not loaded"}',
                status_code=503,
                media_type="application/json",
            )

        try:
            # F-015: pass issuer= to jwt.decode so PyJWT validates iss internally.
            # This is more robust than a manual payload.get("iss") check because
            # PyJWT raises InvalidIssuerError before we touch the payload at all.
            # DEF-002: also validate aud= so a token issued for service A cannot
            # be replayed at service B (lateral movement prevention).
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer="worldview-gateway",
                audience="worldview-internal",
                options={"require": ["sub", "tenant_id", "role", "exp", "iss", "aud"]},
            )

            # F-012: JTI replay detection — prevent token reuse within TTL window.
            # Valkey SET NX (set-if-not-exists) atomically records the JTI on first
            # use. Any subsequent request with the same JTI within the TTL window is
            # rejected. Fail-open: if Valkey is unavailable, the check is skipped
            # (JWT signature + expiry remain validated, so security degrades gracefully).
            jti = payload.get("jti")
            exp = payload.get("exp", 0)
            if jti:
                valkey = getattr(request.app.state, "valkey", None)
                if valkey is not None:
                    # TTL = remaining token lifetime + 60 s buffer (handles clock skew).
                    # max(1, ...) prevents a zero-or-negative TTL on an about-to-expire token.
                    ttl = max(1, int(exp - time.time()) + 60)
                    try:
                        was_new = await valkey.set_nx(f"jti:{jti}", "1", ex=ttl)
                        if not was_new:
                            logger.warning("jti_replay_detected", jti=jti)  # type: ignore[no-any-return]
                            return Response(
                                content='{"detail":"Token replay detected"}',
                                status_code=401,
                                media_type="application/json",
                            )
                    except Exception:
                        # F-S004: fail-open — Valkey unavailability must not block requests.
                        # JWT signature + expiry remain validated. Counter enables alerting.
                        from rag_chat.application.metrics.prometheus import rag_jti_check_bypass_total

                        rag_jti_check_bypass_total.inc()
                        logger.warning("jti_check_valkey_unavailable", jti=jti)  # type: ignore[no-any-return]

            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
            # Set ContextVar so upstream service clients can include X-Internal-JWT
            # in outgoing calls without threading the token through every method signature.
            from rag_chat.infrastructure.clients.auth_context import set_current_jwt

            set_current_jwt(token)
        except jwt.ExpiredSignatureError:
            # F-S001: opaque external body; structlog preserves internal observability.
            logger.info("internal_jwt_expired")  # type: ignore[no-any-return]
            return Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
            )
        except jwt.InvalidTokenError as exc:
            # F-S001: unified external message; debug log for internal diagnostics.
            logger.debug("internal_jwt_invalid", error=str(exc))  # type: ignore[no-any-return]
            return Response(
                content='{"detail":"Unauthorized"}',
                status_code=401,
                media_type="application/json",
            )

        return cast("Response", await call_next(request))
