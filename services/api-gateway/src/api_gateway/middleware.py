"""Gateway middleware — OIDC auth, internal JWT issuance, rate limiting, CORS, security headers."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    from api_gateway.domain import OIDCProviderConfig

# Paths that bypass OIDC auth and rate limiting entirely.
# F-01: /health and /ready removed — only /healthz and /readyz exist on the health router.
_AUTH_SKIP_PATHS: frozenset[str] = frozenset(
    [
        "/v1/auth/login",
        "/v1/auth/callback",
        "/v1/auth/refresh",
        "/v1/auth/logout",
        "/healthz",
        "/readyz",
        "/metrics",
        "/internal/jwks",
    ]
)


# ── OIDC Auth ─────────────────────────────────────────────


class OIDCAuthMiddleware(BaseHTTPMiddleware):
    """Validate Zitadel RS256 access tokens; populate ``request.state.user``.

    On a valid token: looks up ``auth:user:{sub}`` in Valkey and sets
    ``request.state.user`` to ``{sub, email, email_verified, user_id, tenant_id}``.
    On missing token or validation failure: sets ``request.state.user = None``.
    Does NOT return 401 — individual routes enforce auth via dependencies.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        oidc_config: OIDCProviderConfig | None = getattr(request.app.state, "oidc_config", None)

        # When oidc_config is not yet loaded (dev / tests without Zitadel), try to
        # validate Bearer tokens as internal JWTs (issued by dev-login endpoint).
        # This allows the dev-login flow to work without a running Zitadel instance.
        if oidc_config is None:
            if not hasattr(request.state, "user"):
                request.state.user = None
            # Dev-login support: if a Bearer token is present and OIDC is unavailable,
            # try to validate it as a gateway-issued internal JWT.
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and request.state.user is None:
                token = auth[7:]
                pub_key = getattr(request.app.state, "rsa_public_key", None)
                if pub_key is not None:
                    try:
                        payload = jwt.decode(
                            token,
                            pub_key,
                            algorithms=["RS256"],
                            options={"require": ["iss", "sub", "exp"]},
                        )
                        if payload.get("iss") == "worldview-gateway":
                            # Valid internal JWT — look up user from Valkey cache
                            valkey = getattr(request.app.state, "valkey", None)
                            sub = payload.get("sub", "")
                            user_data = None
                            if valkey and sub:
                                import json as _json

                                cached = await valkey.get(f"auth:user:{sub}")
                                if cached:
                                    user_data = _json.loads(cached)
                            if user_data is None:
                                user_data = {
                                    "sub": payload.get("oidc_sub", sub),
                                    "user_id": sub,
                                    "tenant_id": payload.get("tenant_id", ""),
                                    "email": "",
                                    "email_verified": False,
                                }
                            request.state.user = user_data
                    except (jwt.InvalidTokenError, Exception):  # noqa: S110
                        pass  # Not a valid internal JWT — leave user as None
            return cast("Response", await call_next(request))

        # Real OIDC validation path — reset user first
        request.state.user = None

        # Skip auth entirely for public paths
        if request.url.path in _AUTH_SKIP_PATHS:
            return cast("Response", await call_next(request))

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return cast("Response", await call_next(request))

        token = auth[7:]
        settings = request.app.state.settings

        try:
            # Try to get the key id from the unverified header
            unverified = jwt.get_unverified_header(token)
            kid = unverified.get("kid")
            public_key = oidc_config.public_keys.get(kid) if kid else None

            if public_key is None:
                # Attempt JWKS refresh once on cache miss
                from api_gateway.oidc import refresh_oidc_jwks

                refreshed = await refresh_oidc_jwks(oidc_config, request.app.state.httpx_client)
                if refreshed is not None:
                    request.app.state.oidc_config = refreshed
                    oidc_config = refreshed
                    public_key = oidc_config.public_keys.get(kid) if kid else None

            if public_key is None:
                return cast("Response", await call_next(request))

            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=settings.oidc_audience,
                issuer=oidc_config.issuer,
                options={"require": ["iss", "sub", "exp", "aud"]},
            )

            sub = payload.get("sub")
            # Try Valkey cache for full user profile
            valkey = getattr(request.app.state, "valkey", None)
            user_data_oidc: dict[str, Any] | None = None
            if valkey is not None and sub:
                try:
                    import json

                    cached = await valkey.get(f"auth:user:{sub}")
                    if cached:
                        user_data_oidc = json.loads(cached)
                except Exception:  # noqa: S110 — fail-open: Valkey cache miss falls back to token claims
                    pass

            if user_data_oidc is None:
                # Fall back to token claims
                user_data_oidc = {
                    "sub": sub,
                    "email": payload.get("email", ""),
                    "email_verified": payload.get("email_verified", False),
                    "user_id": payload.get("user_id", ""),
                    "tenant_id": payload.get("tenant_id", ""),
                }

            request.state.user = user_data_oidc

        except (jwt.InvalidTokenError, Exception):
            request.state.user = None

        return cast("Response", await call_next(request))


# ── Internal JWT Issuance ─────────────────────────────────


class InternalJWTIssuerMiddleware(BaseHTTPMiddleware):
    """Sign and attach ``X-Internal-JWT`` to every proxied backend request.

    Only active for proxied paths (i.e. paths with an authenticated user).
    Skipped if ``request.state.user`` is None.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        user = getattr(request.state, "user", None)
        if user is not None:
            private_key: RSAPrivateKey | None = getattr(request.app.state, "rsa_private_key", None)
            kid: str | None = getattr(request.app.state, "rsa_kid", None)
            if private_key is not None and kid is not None:
                try:
                    from api_gateway.jwt_utils import issue_user_jwt

                    token = issue_user_jwt(
                        user_id=user.get("user_id", ""),
                        tenant_id=user.get("tenant_id", ""),
                        oidc_sub=user.get("sub", ""),
                        private_key=private_key,
                        kid=kid,
                    )
                    # Mutate the existing headers list IN PLACE so that the
                    # cached request._headers (Headers._list) sees the change.
                    headers_list: list = request.scope["headers"]
                    headers_list[:] = [(k, v) for k, v in headers_list if k.lower() != b"x-internal-jwt"]
                    headers_list.append((b"x-internal-jwt", token.encode()))
                except Exception:  # — fail-open: JWT issuance failure must not block proxy
                    logger.error(
                        "internal_jwt_issuance_failed",
                        user_id=user.get("user_id", ""),
                        path=str(request.url.path),
                        exc_info=True,
                    )

        return cast("Response", await call_next(request))


# ── Security Headers ──────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on every response (SEC-007)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = cast("Response", await call_next(request))
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        settings = getattr(request.app.state, "settings", None)
        if settings is not None and getattr(settings, "cookie_secure", False):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# ── Rate Limiting ─────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Valkey.

    Authenticated requests are keyed by user_id (100/min).
    Unauthenticated requests are keyed by sha256(IP)[:16] (20/min).
    Fail-closed (D-001): returns 503 if Valkey is unavailable.
    """

    def __init__(
        self,
        app: FastAPI,
        valkey_client: Any,  # redis.asyncio.Redis | None
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.valkey = valkey_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # F-05: Skip rate limiting for health probes, metrics, and internal endpoints.
        # These paths are high-frequency infrastructure calls (k8s probes, Prometheus scrape)
        # that should never be throttled or cause a 503 when Valkey is unavailable.
        if request.url.path in _AUTH_SKIP_PATHS or request.url.path.startswith("/internal/"):
            return cast("Response", await call_next(request))

        # Read Valkey from app.state at request time (set during lifespan after startup).
        # Fall back to self.valkey for test overrides; None means Valkey is unavailable.
        valkey = getattr(request.app.state, "valkey", None) or self.valkey
        if valkey is None:
            # D-001: Fail-closed — return 503 when Valkey is unavailable.
            logger.warning(  # type: ignore[no-any-return]
                "rate_limiting_unavailable",
                path=str(request.url.path),
            )
            return Response(
                content='{"detail":"Service temporarily unavailable"}',
                status_code=503,
                media_type="application/json",
            )

        user = getattr(request.state, "user", None)
        if user and user.get("user_id"):
            key = f"rl:v1:user:{user['user_id']}"
            limit = self.max_requests
        else:
            ip = request.client.host if request.client else "unknown"
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
            key = f"rl:v1:ip:{ip_hash}"
            limit = 20  # stricter limit for unauthenticated

        try:
            current = await valkey.incr(key)
            if current == 1:
                await valkey.expire(key, self.window_seconds)
            if current > limit:
                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                )
        except Exception:
            # D-001: Fail-closed — Valkey operation failure returns 503.
            logger.warning(  # type: ignore[no-any-return]
                "rate_limiting_unavailable",
                reason="valkey_operation_failed",
                path=str(request.url.path),
            )
            return Response(
                content='{"detail":"Service temporarily unavailable"}',
                status_code=503,
                media_type="application/json",
            )

        return cast("Response", await call_next(request))


# ── CORS setup ────────────────────────────────────────────


def add_cors(app: FastAPI, origins: str) -> None:
    """Add CORS middleware with explicit method/header allowlist (SEC-003/004).

    Raises ValueError if ``origins`` contains ``"*"`` — combining a wildcard
    with ``allow_credentials=True`` is rejected by all modern browsers (F-016).
    """
    origin_list = [o.strip() for o in origins.split(",") if o.strip()]
    if "*" in origin_list:
        raise ValueError(
            "CORS misconfiguration: allow_origins=['*'] with allow_credentials=True "
            "is rejected by browsers. Set explicit origins in API_GATEWAY_CORS_ORIGINS."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Cookie"],
    )


# ── Auth helpers (kept for backward compat with test_routes etc.) ─────────────


def get_current_user(request: Request) -> dict | None:
    """Extract user from request state (set by OIDCAuthMiddleware).

    Returns ``None`` if no user is authenticated (public route).
    """
    return getattr(request.state, "user", None)
