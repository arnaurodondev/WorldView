"""InternalJWTMiddleware — RS256 internal JWT verifier for backend services.

Validates the ``X-Internal-JWT`` header issued by S9 (api-gateway) on every
proxied request. Sets ``request.state.tenant_id``, ``request.state.user_id``,
and ``request.state.role`` for downstream route handlers.

Health/metrics paths are skipped. On missing or invalid JWT, returns HTTP 401.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
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

# ── W1-05 (BUG-005) — module-level refresh-on-miss rate limit ─────────────────
# Backends must re-fetch JWKS when an incoming JWT carries a ``kid`` not in the
# in-memory cache (so S9 key rotation propagates without restart). To prevent a
# malicious or buggy peer from amplifying every request into an outbound JWKS
# fetch (DoS the gateway), we enforce a per-process cooldown: at most one
# refresh per 60 seconds across ALL middleware instances in the process.
# Module-level state intentional — concurrent requests share the rate limit.
_refresh_lock = threading.Lock()
_last_refresh_ts: float = 0.0
_REFRESH_COOLDOWN_SECONDS = 60
_DEFAULT_KID = "v1"  # fallback when token header omits kid (pre-W1-05 S9 / legacy tests)


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
        # W1-05: kid → public key map populated by _fetch_public_key.
        # ``_public_key`` is kept for back-compat with tests that monkey-patch it.
        self._keys_by_kid: dict[str, Any] = {}
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
            # Mirror portfolio service pattern: surface the skip flag on
            # app.state so /readyz can distinguish "intentionally absent JWKS"
            # (test/dev profile with no api-gateway) from "failed to fetch"
            # (real config issue). Without this, readyz returns 503 degraded.
            with contextlib.suppress(AttributeError):
                app.state._internal_jwt_skip_verification = True

    async def startup(self) -> None:
        """Fetch JWKS from S9 at startup with up to 3 retries (3-second sleep between attempts)."""
        if self._skip_verification:
            return
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
            detail="Service will return 401 on all authenticated requests until JWKS is fetched.",
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
                logger.warning("internal_jwt_public_key_refresh_failed", error=str(exc))  # type: ignore[no-any-return]

    async def _fetch_public_key(self) -> RSAPublicKey:
        """Fetch JWKS from S9 and populate ``self._keys_by_kid``.

        W1-05: returns the first key (back-compat with the legacy single-key
        contract) and also fills ``self._keys_by_kid`` so ``dispatch`` can
        resolve any kid present in the JWKS (current key + grace-window
        previous keys). Entries without a ``kid`` field default to ``"v1"``
        so backends still verify against a pre-W1-05 S9 during the rollout
        window.
        """
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

        new_map: dict[str, Any] = {}
        first_key: RSAPublicKey | None = None
        for key_data in keys:
            try:
                pub_key = RSAAlgorithm.from_jwk(key_data)
            except Exception:  # noqa: S112 — skip malformed entries, keep good ones
                continue
            if not isinstance(pub_key, _RSAPublicKey):
                continue
            kid = key_data.get("kid") or _DEFAULT_KID
            new_map[kid] = pub_key
            if first_key is None:
                first_key = pub_key
        if first_key is None:
            raise TypeError("No usable RSA public keys in JWKS response")
        # Atomic swap under the GIL.
        self._keys_by_kid = new_map
        return first_key

    async def _refresh_jwks_if_allowed(self) -> bool:
        """W1-05: refresh JWKS on kid-miss, rate-limited to 1 fetch / 60 s / process.

        Returns ``True`` if a refresh actually ran (caller should retry the
        kid lookup), ``False`` if the cooldown is still active (caller should
        reject the request without retrying). Defense against DoS amplification.
        """
        global _last_refresh_ts  # — module-level cooldown is intentional
        now = time.monotonic()
        with _refresh_lock:
            if now - _last_refresh_ts < _REFRESH_COOLDOWN_SECONDS:
                return False
            # Reserve the cooldown slot BEFORE the await so concurrent
            # requests don't all see "cooldown elapsed" and stampede.
            _last_refresh_ts = now
        try:
            new_key = await self._fetch_public_key()
            self._public_key = new_key
            if hasattr(self, "app") and hasattr(self.app, "state"):
                self.app.state._internal_jwt_public_key = new_key
            logger.info(  # type: ignore[no-any-return]
                "internal_jwt_jwks_refreshed_on_kid_miss",
                known_kids=list(self._keys_by_kid.keys()),
            )
            return True
        except Exception as exc:  # — fault-tolerant refresh
            logger.warning(  # type: ignore[no-any-return]
                "internal_jwt_jwks_refresh_on_miss_failed",
                error=str(exc),
            )
            return False

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

        # BP-159: Read from app.state, not self — serving instance != startup instance
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

        # W1-05 (BUG-005): resolve the public key by ``kid`` from the JWT
        # header so S9 can rotate signing keys without restarting backends.
        # If the kid is not in our cache, attempt one rate-limited refresh
        # and retry the lookup. If still missing, reject with 401 (the kid
        # was never valid OR rotation grace window expired).
        # Fallback chain: kid lookup → legacy single-key path (back-compat
        # with tests that monkey-patch ``self._public_key`` without
        # populating ``_keys_by_kid``).
        verification_key = public_key
        try:
            token_kid = jwt.get_unverified_header(token).get("kid") or _DEFAULT_KID
        except jwt.DecodeError:
            token_kid = _DEFAULT_KID
        if self._keys_by_kid:
            mapped = self._keys_by_kid.get(token_kid)
            if mapped is None:
                refreshed = await self._refresh_jwks_if_allowed()
                if refreshed:
                    mapped = self._keys_by_kid.get(token_kid)
                if mapped is None:
                    logger.warning(  # type: ignore[no-any-return]
                        "internal_jwt_unknown_kid",
                        token_kid=token_kid,
                        known_kids=list(self._keys_by_kid.keys()),
                        refreshed=refreshed,
                    )
                    return Response(
                        content='{"detail":"Invalid internal JWT"}',
                        status_code=401,
                        media_type="application/json",
                    )
            verification_key = mapped

        try:
            # F-015: pass issuer= to jwt.decode so PyJWT validates iss internally.
            # DEF-002: audience= required — S9 sets aud="worldview-internal" on all
            # internal JWTs; without this, PyJWT 2.x raises InvalidAudienceError
            # for any JWT carrying an aud claim (BP-NEW-004 — pre-existing bug).
            payload = jwt.decode(
                token,
                verification_key,
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
            # Note: market-ingestion does not configure Valkey on app.state; getattr
            # returns None and the JTI check is safely skipped in production.
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
