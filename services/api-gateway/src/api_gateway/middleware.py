"""Gateway middleware — OIDC auth, internal JWT issuance, rate limiting, CORS, security headers."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any, cast

import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import REGISTRY, Counter
from starlette.middleware.base import BaseHTTPMiddleware

from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── FIX-LIVE-D (PLAN-0093 Phase 5c, F-LIVE-005C-VALKEY) ───────────────────────
#
# Counter for rate-limiter degradation events. Q5/Q6/Q7 of the live chat-eval
# all returned HTTP 503 with 5-13ms latency because RateLimitMiddleware fail-
# closed instantly when Valkey hiccuped mid-run — no retry, no metric, no
# structured event for observability. This counter feeds a Grafana alert on
# rate_limiter degradation so we never have to investigate from a single 503
# again.
#
# Label ``fallback_action`` values:
#   - "retry_succeeded": first Valkey op raised but the retry succeeded → 200
#   - "503_after_retry": both attempts failed → 503 returned
#   - "503_no_retry":    Valkey client is None (lifespan never connected)
#                        OR a non-transient error (e.g. auth) — no retry made
#
# Registered at import time on the global REGISTRY (single logical counter per
# process). The duplicate-registration guard mirrors the pattern used in
# libs/observability/src/observability/metrics.py for KAFKA_CONSUMER_MESSAGES,
# so tests that reload modules or isolate registries don't crash on import.
try:
    RATE_LIMITING_UNAVAILABLE = Counter(
        "rate_limiting_unavailable_total",
        "Rate-limiter degraded to fail-closed (Valkey unavailable).",
        labelnames=("fallback_action",),
    )
except ValueError:
    _existing = REGISTRY._names_to_collectors.get("rate_limiting_unavailable_total")
    if _existing is None:
        raise
    RATE_LIMITING_UNAVAILABLE = _existing  # type: ignore[assignment]

# Transient network/timeout exception classes we will retry on. Anything else
# (e.g. ResponseError from an AUTH failure, programmer errors) is NOT
# transient — retrying just delays the inevitable 503 while burning CPU. We
# import redis exception classes lazily inside a try/except so test
# environments without a real redis install don't fail at module load.
_VALKEY_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...]
try:
    from redis.exceptions import (  # type: ignore[import-untyped]
        ConnectionError as _RedisConnectionError,
    )
    from redis.exceptions import (
        TimeoutError as _RedisTimeoutError,
    )

    _VALKEY_TRANSIENT_EXCEPTIONS = (
        _RedisConnectionError,
        _RedisTimeoutError,
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    )
except Exception:  # — best effort: redis missing in some test contexts
    _VALKEY_TRANSIENT_EXCEPTIONS = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    )

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

    from api_gateway.domain import OIDCProviderConfig

# Paths that bypass OIDC auth and rate limiting entirely.
# F-01: /health and /ready removed — only /healthz and /readyz exist on the health router.
# PLAN-0088 P2-D (2026-05-10): /v1/health added as external uptime monitor alias.
_AUTH_SKIP_PATHS: frozenset[str] = frozenset(
    [
        "/v1/auth/login",
        "/v1/auth/callback",
        "/v1/auth/refresh",
        "/v1/auth/logout",
        "/healthz",
        "/readyz",
        "/v1/health",
        "/metrics",
        "/internal/jwks",
    ],
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
        # BUG-004 / BP-480: defensively initialise ``request.state.user`` to
        # ``None`` as the very first action of every dispatch, BUT only when
        # the attribute has not already been set by an upstream middleware.
        # This guarantees the attribute ALWAYS exists with a sentinel value
        # for downstream middleware (notably ``RateLimitMiddleware``) even
        # on error paths that exit before the regular assignments below —
        # while still respecting any user dict that a test harness or
        # alternate auth middleware may legitimately have injected ahead of
        # us (e.g. ``TestAuthMiddleware`` in api-gateway's conftest). Without
        # this guard the rate limiter could see a missing attribute and fall
        # through to the IP bucket, allowing rate-limit-bypass over shared NAT.
        if not hasattr(request.state, "user"):
            request.state.user = None

        oidc_config: OIDCProviderConfig | None = getattr(request.app.state, "oidc_config", None)

        # When oidc_config is not yet loaded (dev / tests without Zitadel), try to
        # validate Bearer tokens as internal JWTs (issued by dev-login endpoint).
        # This allows the dev-login flow to work without a running Zitadel instance.
        if oidc_config is None:
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
                            audience="worldview-internal",
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

        # Real OIDC validation path — this middleware is authoritative on
        # this path, so always reset ``request.state.user`` to ``None`` (any
        # successful validation below reassigns it to the claims dict).
        # Note: this is intentionally unconditional (different from the
        # dev-mode branch above) — in production no upstream middleware
        # should be injecting user state.
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


# Financial-mutation path prefixes that get a tighter per-user sub-tier.
# These cover write operations on transaction and brokerage resources — actions
# that can have real financial consequences (creating/deleting transactions,
# syncing brokerage accounts). We intentionally omit GET paths from this set
# so read-heavy dashboard loads stay within the generous 300/min default bucket.
_FINANCIAL_MUTATION_PREFIXES: tuple[str, ...] = (
    "/v1/transactions",  # POST / PUT / DELETE transactions
    "/v1/brokerage",  # POST brokerage connections, trigger sync
    "/v1/portfolios",  # POST rebalance, PUT/DELETE portfolio entries
)
# Strict limit for financial mutations (POST/PUT/DELETE on the paths above).
# 20/min allows ~1 transaction create every 3 seconds — generous for manual
# entry but tight enough to stop accidental loops or misbehaving clients.
_FINANCIAL_MUTATION_LIMIT = 20


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Valkey.

    Authenticated requests are keyed by user_id (300/min default).
    Financial mutation endpoints (POST/PUT/DELETE on /v1/transactions,
    /v1/brokerage, /v1/portfolios) use a tighter 20/min sub-tier keyed
    separately so payment-adjacent writes are strictly controlled while
    read-heavy dashboard loads stay within the default bucket.
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
            # FIX-LIVE-D: increment the degradation counter with the
            # "503_no_retry" label so Grafana can distinguish lifespan-time
            # Valkey miss from a per-request hiccup. Without this label split
            # every 503 looks the same and we can't tell whether the gateway
            # never connected to Valkey at startup (operator config issue) or
            # Valkey is mid-flap during normal traffic (infra issue).
            RATE_LIMITING_UNAVAILABLE.labels(fallback_action="503_no_retry").inc()
            logger.warning(  # type: ignore[no-any-return]
                "rate_limiting_unavailable",
                path=str(request.url.path),
                reason="valkey_client_none",
            )
            return Response(
                content='{"detail":"Service temporarily unavailable"}',
                status_code=503,
                media_type="application/json",
            )

        # BUG-004 / BP-480: defensively read ``request.state.user`` via
        # ``getattr`` with a ``None`` default. ``OIDCAuthMiddleware.dispatch``
        # now sets ``request.state.user = None`` as its first action, so the
        # attribute should ALWAYS be present here. We still log a warning if
        # the attribute is missing — that would indicate a regression in
        # middleware ordering or a new code path that bypasses OIDCAuth,
        # which would otherwise silently fall through to the IP bucket and
        # share one shared-NAT counter across many users.
        if not hasattr(request.state, "user"):
            logger.warning(
                "rate_limit_user_attr_missing",
                path=str(request.url.path),
                method=request.method,
            )
        user = getattr(request.state, "user", None)
        path = str(request.url.path)
        method = request.method.upper()
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

        # Financial mutation sub-tier: tighter bucket (20/min) for write
        # operations on transaction and brokerage endpoints so accidental
        # loops or misbehaving clients cannot blast payment-adjacent APIs.
        # Only applies to authenticated users; unauthenticated mutations are
        # already restricted by the strict 20/min IP bucket below.
        is_financial_mutation = method in {"POST", "PUT", "DELETE", "PATCH"} and any(
            path.startswith(pfx) for pfx in _FINANCIAL_MUTATION_PREFIXES
        )

        # BUG-004 / BP-480: require ``user`` to be a dict before calling
        # ``.get("user_id")`` so a malformed value (e.g. a string slipped in
        # by future code) cannot raise AttributeError mid-dispatch. The
        # ``isinstance`` check makes the contract explicit at the call site.
        if user and isinstance(user, dict) and user.get("user_id"):
            if is_financial_mutation:
                # Separate Valkey key so the financial-mutation counter does
                # not eat the general dashboard budget. A user can perform
                # up to 20 transaction writes per minute while simultaneously
                # firing 300 read requests for charts / screener / KG data.
                key = f"rl:v1:fin:{user['user_id']}"
                limit = _FINANCIAL_MUTATION_LIMIT
            else:
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

        # FIX-LIVE-D (PLAN-0093 Phase 5c, F-LIVE-005C-VALKEY): retry-with-
        # backoff around the Valkey op. Phase 5c live chat-eval Q5/Q6/Q7 all
        # 503'd in 5-13ms because a single transient Valkey hiccup mid-run
        # caused this middleware to fail-closed instantly. We now retry ONCE
        # with a 50ms backoff on network-class exceptions before failing.
        # Auth errors and other non-transient failures skip the retry — they
        # will never recover in 50ms and the extra round-trip just delays the
        # 503 while consuming CPU under load.
        current: int | None = None
        last_exc: BaseException | None = None
        max_attempts = 2  # 1 original + 1 retry
        retry_backoff_seconds = 0.05  # 50ms
        for attempt in range(1, max_attempts + 1):
            try:
                current = await valkey.incr(key)
                # Only set EXPIRE when the key is brand-new (current == 1).
                # Setting it on every request would reset the TTL on each hit,
                # allowing a sustained flow to never expire and permanently
                # bypass the limit. If a crash occurred between INCR and
                # EXPIRE on a previous request the key is already present
                # (current > 1) but has no TTL; the next new window (new key
                # from fresh INCR) will set the TTL correctly.
                if current == 1:
                    await valkey.expire(key, self.window_seconds)
                last_exc = None
                # FIX-LIVE-D: if this was a retry success, record the win
                # so Grafana can show "retries are saving us" alongside the
                # raw 503 rate. Without this the success path is silent and
                # operators can't tell the resilience patch is doing its job.
                if attempt > 1:
                    RATE_LIMITING_UNAVAILABLE.labels(fallback_action="retry_succeeded").inc()
                    logger.info(  # type: ignore[no-any-return]
                        "valkey_op_retry_succeeded",
                        path=str(request.url.path),
                        valkey_retry_attempt=attempt,
                    )
                break
            except _VALKEY_TRANSIENT_EXCEPTIONS as exc:
                # Transient — eligible for retry. Log every attempt so we can
                # see flap rate in logs even if no request ultimately 503s.
                last_exc = exc
                logger.warning(  # type: ignore[no-any-return]
                    "valkey_op_failed",
                    path=str(request.url.path),
                    valkey_retry_attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    transient=True,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(retry_backoff_seconds)
                    continue
                # Exhausted retries — fall through to 503 branch below.
            except Exception as exc:
                # Non-transient (auth, programmer error, schema mismatch).
                # Do NOT retry — the failure won't heal in 50ms and we want
                # the 503 immediately so the upstream caller surfaces it.
                last_exc = exc
                logger.warning(  # type: ignore[no-any-return]
                    "valkey_op_failed",
                    path=str(request.url.path),
                    valkey_retry_attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    transient=False,
                )
                RATE_LIMITING_UNAVAILABLE.labels(fallback_action="503_no_retry").inc()
                return Response(
                    content='{"detail":"Service temporarily unavailable"}',
                    status_code=503,
                    media_type="application/json",
                )

        if last_exc is not None:
            # D-001: Fail-closed — Valkey operation failure returns 503 only
            # AFTER the retry budget is exhausted. The metric label
            # "503_after_retry" lets operators distinguish a single hiccup
            # (would have 503'd before this patch) from a sustained outage
            # (will 503 even with the retry).
            RATE_LIMITING_UNAVAILABLE.labels(fallback_action="503_after_retry").inc()
            return Response(
                content='{"detail":"Service temporarily unavailable"}',
                status_code=503,
                media_type="application/json",
            )

        # current is guaranteed non-None here (loop succeeded). The narrowing
        # via assert keeps mypy happy without a type-ignore.
        assert current is not None  # — invariant from loop above
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
            "is rejected by browsers. Set explicit origins in API_GATEWAY_CORS_ORIGINS.",
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
