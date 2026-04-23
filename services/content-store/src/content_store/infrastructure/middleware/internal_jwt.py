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
    """Validate ``X-Internal-JWT`` (RS256) on every non-health S1 request.

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
            logger.critical(  # type: ignore[no-any-return]
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
                # BP-159: store on app.state so the serving instance can access it
                self.app.state._internal_jwt_public_key = key  # type: ignore[attr-defined]
                logger.info(  # type: ignore[no-any-return]
                    "internal_jwt_public_key_loaded",
                    jwks_url=self._jwks_url,
                )
                self._refresh_task = asyncio.ensure_future(self._background_refresh())
                return
            except Exception as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "internal_jwt_startup_fetch_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < 2:
                    await asyncio.sleep(3)

        logger.error(  # type: ignore[no-any-return]
            "internal_jwt_startup_failed_all_attempts",
            jwks_url=self._jwks_url,
            detail="Service will return 503 on all authenticated requests until JWKS is fetched.",
        )

    async def _background_refresh(self) -> None:
        """Refresh the public key every hour in the background."""
        while True:
            await asyncio.sleep(_JWKS_REFRESH_INTERVAL_SECONDS)
            try:
                new_key = await self._fetch_public_key()
                self._public_key = new_key
                # BP-159: update app.state for the serving instance
                self.app.state._internal_jwt_public_key = new_key  # type: ignore[attr-defined]
                logger.info("internal_jwt_public_key_refreshed")  # type: ignore[no-any-return]
            except Exception as exc:
                logger.warning("internal_jwt_public_key_refresh_failed", error=str(exc))  # type: ignore[no-any-return]

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

        # BP-159: read from app.state (shared across instances), fallback to self
        public_key = getattr(request.app.state, "_internal_jwt_public_key", None) or self._public_key
        if public_key is None:
            # F-001: Fail-closed by default when JWKS public key is unavailable.
            # Without the public key we cannot verify JWT signatures, so accepting
            # tokens here would allow any forged JWT to pass through unchecked.
            if not self._skip_verification:
                logger.error(  # type: ignore[no-any-return]
                    "internal_jwt_no_public_key",
                    detail="JWKS public key not loaded — rejecting request (fail-closed).",
                )
                return Response(
                    content='{"detail":"Service Unavailable — JWKS not loaded"}',
                    status_code=503,
                    media_type="application/json",
                )

            # skip_verification=True: decode WITHOUT signature verification.
            # This path exists ONLY for E2E tests without the full S9 stack.
            logger.critical(  # type: ignore[no-any-return]
                "internal_jwt_unverified_decode",
                detail="Decoding JWT WITHOUT signature verification (skip_verification=True).",
            )
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                request.state.tenant_id = payload.get("tenant_id", "")
                request.state.user_id = payload.get("sub", "")
                request.state.role = payload.get("role", "")
            except jwt.DecodeError:
                request.state.tenant_id = ""
                request.state.user_id = ""
                request.state.role = ""
            return cast("Response", await call_next(request))

        try:
            # F-015: pass issuer= to jwt.decode so PyJWT validates iss internally.
            # This is more robust than a manual payload.get("iss") check because
            # PyJWT raises InvalidIssuerError before we touch the payload at all.
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer="worldview-gateway",
                options={"require": ["sub", "tenant_id", "role", "exp", "iss"]},
            )

            # F-012: JTI replay detection — prevent token reuse within TTL window.
            # Valkey SET NX (set-if-not-exists) atomically records the JTI on first
            # use. Any subsequent request with the same JTI within the TTL window is
            # rejected. Fail-open: if Valkey is unavailable, the check is skipped
            # (JWT signature + expiry remain validated, so security degrades gracefully).
            # Note: content-store stores the Valkey client as app.state.valkey_client.
            jti = payload.get("jti")
            exp = payload.get("exp", 0)
            if jti:
                valkey = getattr(request.app.state, "valkey_client", None)
                if valkey is not None:
                    # TTL = remaining token lifetime + 60 s buffer (handles clock skew).
                    # max(1, ...) prevents a zero-or-negative TTL on an about-to-expire token.
                    ttl = max(1, int(exp - time.time()) + 60)
                    try:
                        was_new = await valkey.set(f"jti:{jti}", "1", ex=ttl, nx=True)
                        if not was_new:
                            logger.warning("jti_replay_detected", jti=jti)  # type: ignore[no-any-return]
                            return Response(
                                content='{"detail":"Token replay detected"}',
                                status_code=401,
                                media_type="application/json",
                            )
                    except Exception:
                        # Fail-open: Valkey unavailability should not block requests.
                        # JWT signature + expiry remain validated. Log for ops visibility.
                        logger.warning("jti_check_valkey_unavailable", jti=jti)  # type: ignore[no-any-return]

            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
        except jwt.ExpiredSignatureError:
            return Response(
                content='{"detail":"Internal JWT expired"}',
                status_code=401,
                media_type="application/json",
            )
        except jwt.InvalidTokenError as exc:
            logger.debug("internal_jwt_invalid", error=str(exc))  # type: ignore[no-any-return]
            return Response(
                content='{"detail":"Invalid internal JWT"}',
                status_code=401,
                media_type="application/json",
            )

        return cast("Response", await call_next(request))
