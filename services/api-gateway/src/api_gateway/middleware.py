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


def _extract_role(payload: dict[str, Any]) -> str:
    """Resolve the role claim from a Zitadel-shaped OIDC access token.

    F-Q2-01: Zitadel emits role assignments in three possible shapes. We
    accept all three so the gateway is forgiving across action-script
    customisations and the standard OIDC ``role``/``roles`` claims:

      1. ``urn:zitadel:iam:org:project:roles`` — Zitadel default, a dict
         keyed by role-name: ``{"admin": {"<projectId>": "<orgId>"}}``.
         The presence of an "admin" key signals the user holds the role.
      2. ``roles`` — a JSON array of role-name strings (e.g. mapped via
         a token-customisation action). Membership of "admin" wins.
      3. ``role`` — a single string claim (legacy / custom IdP).

    Priority: Zitadel-namespaced claim > ``roles`` array > ``role`` string.
    Resolves to ``"admin"`` if any shape indicates admin, otherwise
    ``"user"``. The default ``"user"`` matches issue_user_jwt's default.
    """
    # 1. Zitadel canonical role claim
    zitadel_roles = payload.get("urn:zitadel:iam:org:project:roles")
    if isinstance(zitadel_roles, dict) and "admin" in zitadel_roles:
        return "admin"

    # 2. Generic ``roles`` array claim
    roles = payload.get("roles")
    if isinstance(roles, list) and any(isinstance(r, str) and r.lower() == "admin" for r in roles):
        return "admin"

    # 3. Single ``role`` string claim
    role = payload.get("role")
    if isinstance(role, str) and role.lower() == "admin":
        return "admin"

    return "user"


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
                            # F-Q2-01: ensure dev-mode users still carry a role
                            # claim so admin endpoints work after a Valkey miss.
                            # Internal JWTs encode the role directly (issued by
                            # dev-login or the gateway), so we trust that value.
                            user_data.setdefault("role", payload.get("role", "user"))
                            request.state.user = user_data
                    except jwt.InvalidTokenError:
                        pass  # Expected: token was not meant for internal validation
                    except Exception:
                        logger.debug("dev_login_jwt_validation_error", exc_info=True)
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
            # F-Q2-01: extract the role from the Zitadel access token. The
            # Zitadel token is the only authoritative source for role on the
            # real-OIDC path — the Valkey cache may be stale or missing. We
            # always recompute from the live token claims and let the cached
            # entry fill in user_id / tenant_id / email.
            oidc_role = _extract_role(payload)

            # Try Valkey cache for full user profile
            valkey = getattr(request.app.state, "valkey", None)
            user_data_oidc: dict[str, Any] | None = None
            if valkey is not None and sub:
                try:
                    import json

                    cached = await valkey.get(f"auth:user:{sub}")
                    if cached:
                        user_data_oidc = json.loads(cached)
                except Exception:  # — fail-open: Valkey unavailable, rebuild from token claims
                    logger.warning("valkey_user_cache_read_failed", exc_info=True)

            if user_data_oidc is None:
                # F-041: log cache miss at debug level so it is visible in
                # observability without being noisy on every cold-start request.
                logger.debug(  # type: ignore[no-any-return]
                    "valkey_user_cache_miss",
                    sub=sub,
                )
                # Fall back to token claims
                user_data_oidc = {
                    "sub": sub,
                    "email": payload.get("email", ""),
                    "email_verified": payload.get("email_verified", False),
                    "user_id": payload.get("user_id", ""),
                    "tenant_id": payload.get("tenant_id", ""),
                }

            # Authoritative role from the OIDC token always wins over any
            # stale cached value — admins get downgraded if they lose the role
            # at the IdP and we must reflect that immediately.
            user_data_oidc["role"] = oidc_role
            request.state.user = user_data_oidc

        except jwt.InvalidTokenError:
            # Expected path: invalid/expired OIDC token — user gets no auth context.
            request.state.user = None
        except Exception:
            # Unexpected errors (network, config) — log for debugging but still
            # fail-open so a Valkey outage doesn't lock every user out.
            logger.debug("oidc_auth_unexpected_error", exc_info=True)
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

                    # F-Q2-05: forward the role claim resolved by
                    # OIDCAuthMiddleware (or seeded from the dev-login JWT
                    # payload). Without this, the middleware-stamped header
                    # always carries role="user" and any backend route that
                    # reads it (instead of relying on the per-route
                    # ``_auth_headers()`` re-issue) would 403 admin endpoints.
                    token = issue_user_jwt(
                        user_id=user.get("user_id", ""),
                        tenant_id=user.get("tenant_id", ""),
                        oidc_sub=user.get("sub", ""),
                        private_key=private_key,
                        kid=kid,
                        role=user.get("role") or "user",
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
        path = str(request.url.path)
        # PLAN-0052 platform-QA fix (2026-05-01): bucket public-feedback +
        # public-roadmap surfaces under a separate, more generous IP-keyed
        # bucket. The default 20/min/IP cap meant a single noisy NAT (dev
        # tab opening /feedback + a docs micro-survey + a few feature votes)
        # would 429-lock every other unauth visitor on the same IP. The
        # public surfaces are intentionally read-mostly and idempotent;
        # 120/min is roughly "1 vote + 1 list refresh per second" sustained.
        # Shape: the prefix match keeps the rule trivial — feedback features
        # listing, voting, and the docs micro-survey POST all live under
        # /v1/feedback/.
        is_public_feedback = path.startswith("/v1/feedback/")
        if user and user.get("user_id"):
            key = f"rl:v1:user:{user['user_id']}"
            limit = self.max_requests
        else:
            ip = request.client.host if request.client else "unknown"
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
            if is_public_feedback:
                # Separate bucket so the feedback-surface activity does not
                # eat the global 20/min budget for the same IP. Different
                # key prefix ensures the two counters don't collide.
                key = f"rl:v1:ip-fb:{ip_hash}"
                limit = 120
            else:
                key = f"rl:v1:ip:{ip_hash}"
                limit = 20  # stricter limit for unauthenticated

        try:
            current = await valkey.incr(key)
            # Only set EXPIRE when the key is brand-new (current == 1). Setting
            # it on every request would reset the TTL on each hit, allowing a
            # sustained flow to never expire and permanently bypass the limit.
            # If a crash occurred between INCR and EXPIRE on a previous request
            # the key is already present (current > 1) but has no TTL; the next
            # new window (new key from fresh INCR) will set the TTL correctly.
            if current == 1:
                await valkey.expire(key, self.window_seconds)
            if current > limit:
                # PLAN-0052 platform-QA fix: include Retry-After header so
                # clients (and the user) know when to retry. We use the
                # window length as a conservative upper bound — the actual
                # remaining time is window_seconds minus elapsed-in-window,
                # but Valkey doesn't surface the elapsed cheaply enough to
                # justify the extra round-trip per 429.
                return Response(
                    content='{"detail":"Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "Retry-After": str(self.window_seconds),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
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
