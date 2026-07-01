"""InternalJWTMiddleware — shared RS256 internal JWT verifier for backend services.

Extracted from 9 per-service copies (REF-001 / TASK-W2-05).  The middleware
validates the ``X-Internal-JWT`` header issued by S9 (api-gateway) on every
proxied request and sets ``request.state.tenant_id``, ``request.state.user_id``,
and ``request.state.role`` for downstream handlers.

Per-service behaviour differences are absorbed through constructor kwargs and
overridable hook methods (``_post_validate``, ``_unverified_decode``,
``_load_token`` and a few logging-level knobs).  Each service's
``infrastructure/middleware/internal_jwt.py`` becomes a thin subclass that
specialises only what truly differs (e.g. rag-chat's ``set_current_jwt`` call,
alert's WebSocket-upgrade query-param token, market-data's skip-verification
ordering).

PRD-0025 §6.5 (InternalJWTMiddleware spec).
W1-05 (BUG-005) — JWKS refresh-on-miss with module-level cooldown.
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

from observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

logger = get_logger(__name__)

# ── Canonical internal-JWT identity constants ─────────────────────────────────
# These MUST match what ``InternalJWTMiddleware`` validates below
# (issuer="worldview-gateway", audience="worldview-internal") and what the S9
# api-gateway ``jwt_utils`` mints.  Centralised here so every service-to-service
# minter emits a token that is correct-by-construction.
INTERNAL_JWT_ISSUER = "worldview-gateway"
INTERNAL_JWT_AUDIENCE = "worldview-internal"

# Nil UUID used as user_id/tenant_id for system-to-system (no real user) calls.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def build_internal_jwt_claims(
    *,
    sub: str,
    tenant_id: str = _NIL_UUID,
    role: str = "system",
    ttl_seconds: int,
    user_id: str | None = _NIL_UUID,
    service_name: str | None = None,
    scope: str | None = None,
    issuer: str = INTERNAL_JWT_ISSUER,
    audience: str = INTERNAL_JWT_AUDIENCE,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a correctly-claimed internal-JWT payload (single source of truth).

    DEF-002 GAP FIX: every internal-JWT minter previously omitted the ``aud``
    claim (and usually ``jti``).  ``InternalJWTMiddleware`` REQUIRES both
    ``aud`` (validated == ``worldview-internal``) and, when present, uses
    ``jti`` for replay protection.  Those tokens "worked" only because their
    target services ran ``skip_verification=True``; the moment real
    verification is enabled every one of them 401s.  This helper guarantees
    the ``aud`` + ``jti`` + ``iss`` + timestamps are always present and
    consistent.

    Repo rules honoured: ``jti`` is a UUIDv7 (``common.ids.new_uuid7``) and
    ``iat``/``exp`` derive from ``common.time.utc_now`` (UTC-only).
    """
    # Local imports keep ``observability`` importable in minimal environments
    # (pure-logger consumers) that don't need JWT minting.
    from common.ids import new_uuid7  # type: ignore[import-untyped]
    from common.time import utc_now  # type: ignore[import-untyped]

    iat = int(utc_now().timestamp())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,  # DEF-002: required by InternalJWTMiddleware
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "jti": str(new_uuid7()),  # F-012: enables JTI replay protection
        "iat": iat,
        "exp": iat + ttl_seconds,
    }
    if user_id is not None:
        claims["user_id"] = user_id
    if service_name is not None:
        claims["service_name"] = service_name
    if scope is not None:
        claims["scope"] = scope
    if extra_claims:
        claims.update(extra_claims)
    return claims


def mint_internal_jwt(
    *,
    sub: str,
    tenant_id: str = _NIL_UUID,
    role: str = "system",
    ttl_seconds: int = 300,
    private_key_pem: str = "",
    dev_hs256_secret: str = "",
    user_id: str | None = _NIL_UUID,
    service_name: str | None = None,
    scope: str | None = None,
    kid: str | None = None,
    issuer: str = INTERNAL_JWT_ISSUER,
    audience: str = INTERNAL_JWT_AUDIENCE,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a correctly-claimed internal JWT (``aud`` + ``jti`` guaranteed).

    Signing mode mirrors every existing service-to-service minter:

    * ``private_key_pem`` non-empty  → RS256, signed with the same key S9 uses
      so backends verify it against the gateway JWKS.
    * ``private_key_pem`` empty       → HS256 dev fallback using
      ``dev_hs256_secret`` (only accepted when the target runs
      ``skip_verification=True``).

    This does NOT change key management — callers keep their own per-service
    private key / dev secret.  It only makes the *claims* correct so a future
    verification-enable rollout is safe.
    """
    claims = build_internal_jwt_claims(
        sub=sub,
        tenant_id=tenant_id,
        role=role,
        ttl_seconds=ttl_seconds,
        user_id=user_id,
        service_name=service_name,
        scope=scope,
        issuer=issuer,
        audience=audience,
        extra_claims=extra_claims,
    )
    headers = {"kid": kid} if kid else None
    if private_key_pem:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(private_key_pem.encode(), password=None)
        return str(jwt.encode(claims, private_key, algorithm="RS256", headers=headers))  # type: ignore[arg-type]
    return str(jwt.encode(claims, dev_hs256_secret, algorithm="HS256", headers=headers))


# ── Default skip lists (overridable per service via constructor) ──────────────
DEFAULT_SKIP_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/readyz",
        "/internal/v1/health",
    }
)
DEFAULT_SKIP_PREFIXES: tuple[str, ...] = ("/health", "/metrics", "/readyz")

_JWKS_REFRESH_INTERVAL_SECONDS = 3600  # 1 hour

# ── W1-05 (BUG-005) — module-level refresh-on-miss rate limit ─────────────────
# Backends must re-fetch JWKS when an incoming JWT carries a ``kid`` not in the
# in-memory cache (so S9 key rotation propagates without restart).  To prevent a
# malicious or buggy peer from amplifying every request into an outbound JWKS
# fetch (DoS the gateway), we enforce a per-process cooldown: at most one
# refresh per 60 seconds across ALL middleware instances in the process.
# Module-level state intentional — concurrent requests share the rate limit.
_refresh_lock = threading.Lock()
_last_refresh_ts: float = 0.0
_REFRESH_COOLDOWN_SECONDS = 60
_DEFAULT_KID = "v1"  # fallback when token header omits kid (pre-W1-05 S9 / legacy tests)


class InternalJWTMiddleware(BaseHTTPMiddleware):
    """Validate ``X-Internal-JWT`` (RS256) on every non-skipped request.

    Usage in ``create_app``::

        middleware = InternalJWTMiddleware(
            app,
            jwks_url=f"{settings.api_gateway_url}/internal/jwks",
            service_name=settings.service_name,
        )
        # Call await middleware.startup() in lifespan before yield.
        app.add_middleware(InternalJWTMiddleware, jwks_url=..., service_name=...)

    The middleware stores the public key in ``app.state._internal_jwt_public_key``
    so the dispatch-side instance (which Starlette creates separately from the
    startup-side instance) can read the same key.

    Per-service customisation
    -------------------------
    Subclasses can override:

    * ``_load_token(request)`` — extract token (e.g. alert reads ``?token=`` on
      WebSocket-upgrade requests).
    * ``_unverified_decode(request, token)`` — implement skip_verification path
      (e.g. rag-chat enforces minimum claims and calls ``set_current_jwt``).
    * ``_post_validate(request, token, payload)`` — runs after successful
      decode + JTI check (e.g. rag-chat stores token in ContextVar; nlp-pipeline
      stores ``request.state.internal_jwt``).
    * ``_jti_replay_check(request, jti, exp)`` — full JTI logic
      (key shape, on-bypass metric, etc.).
    * ``_invalid_token_response()`` / ``_expired_token_response()`` — error
      response shape (rag-chat returns opaque ``"Unauthorized"``).
    """

    # ── Constructor ───────────────────────────────────────────────────────────
    def __init__(
        self,
        app: Any,
        jwks_url: str,
        *,
        issuer: str = "worldview-gateway",
        audience: str = "worldview-internal",
        service_name: str = "unknown",
        skip_verification: bool = False,
        jti_replay_check_enabled: bool = True,
        skip_paths: Iterable[str] = DEFAULT_SKIP_PATHS,
        skip_prefixes: Iterable[str] = DEFAULT_SKIP_PREFIXES,
        valkey_attr: str = "valkey",
        jti_key_includes_service_name: bool = False,
        skip_verification_log_level: str = "warning",
        # W2-05 follow-up: default flipped False → True (2026-05-20) because all
        # currently-known readyz handlers across the 9 backends read
        # ``app.state._internal_jwt_skip_verification`` to decide whether the
        # absent ``_internal_jwt_public_key`` is intentional (dev/test skip
        # mode) or a real failure. Defaulting to False meant 6 of 9 backends
        # reported readyz=503 ``jwks_not_loaded`` whenever skip_verification
        # was enabled — the W2-05 refactor wired the flag in 3 subclasses
        # (content-store, knowledge-graph, nlp-pipeline) but missed
        # portfolio / alert / content-ingestion / market-ingestion /
        # market-data / rag-chat. Flipping the default fixes all 6 at once
        # and matches the readyz contract every existing handler expects.
        # Any service that explicitly does NOT want this side effect can
        # opt out via set_skip_verification_on_state=False.
        set_skip_verification_on_state: bool = True,
        skip_verification_takes_precedence: bool = False,
    ) -> None:
        super().__init__(app)
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience
        self._service_name = service_name
        self._public_key: RSAPublicKey | None = None
        # W1-05: kid → public key map populated by _fetch_public_key.
        # ``_public_key`` kept for back-compat with tests that monkey-patch it.
        self._keys_by_kid: dict[str, Any] = {}
        self._refresh_task: asyncio.Task | None = None
        self._skip_verification = skip_verification
        self._jti_replay_check_enabled = jti_replay_check_enabled
        self._skip_paths = frozenset(skip_paths)
        self._skip_prefixes = tuple(skip_prefixes)
        self._valkey_attr = valkey_attr
        self._jti_key_includes_service_name = jti_key_includes_service_name
        self._skip_verification_log_level = skip_verification_log_level
        self._set_skip_verification_on_state = set_skip_verification_on_state
        self._skip_verification_takes_precedence = skip_verification_takes_precedence

        if self._skip_verification:
            # Some services use CRITICAL, rag-chat uses WARNING — controlled
            # by skip_verification_log_level kwarg.
            log_fn = getattr(logger, skip_verification_log_level, logger.critical)
            log_fn(
                "internal_jwt_skip_verification_enabled",
                detail=(
                    "InternalJWTMiddleware signature verification is DISABLED. "
                    "This MUST NOT be used in production — any forged JWT will be accepted."
                ),
            )
            if self._set_skip_verification_on_state:
                with contextlib.suppress(AttributeError):
                    app.state._internal_jwt_skip_verification = True

    # ── Lifecycle: JWKS fetch + background refresh ───────────────────────────
    async def startup(self) -> None:
        """Fetch JWKS from S9 at startup with up to 3 retries (3-second back-off)."""
        if self._skip_verification:
            return
        for attempt in range(3):
            try:
                key = await self._fetch_public_key()
                self._public_key = key
                # BP-159: store on app.state so the dispatch-side instance reads
                # the same key (Starlette creates a separate instance for dispatch).
                if hasattr(self, "app") and hasattr(self.app, "state"):
                    self.app.state._internal_jwt_public_key = key
                logger.info(
                    "internal_jwt_public_key_loaded",
                    jwks_url=self._jwks_url,
                )
                self._refresh_task = asyncio.ensure_future(self._background_refresh())
                return
            except Exception as exc:
                self._log_startup_failure(attempt, exc)
                if attempt < 2:
                    await asyncio.sleep(3)

        logger.error(
            "internal_jwt_startup_failed_all_attempts",
            jwks_url=self._jwks_url,
            detail="Service will return 503 on all authenticated requests until JWKS is fetched.",
        )
        raise RuntimeError(f"JWKS startup failed after 3 attempts — cannot start without public key ({self._jwks_url})")

    def _log_startup_failure(self, attempt: int, exc: Exception) -> None:
        """Hook: log a startup-fetch failure.

        Default: log ``str(exc)`` at WARNING.  Subclasses (rag-chat) can sanitise
        the HTTP body before logging.
        """
        logger.warning(
            "internal_jwt_startup_fetch_failed",
            attempt=attempt + 1,
            error=str(exc),
        )

    async def _background_refresh(self) -> None:
        """Refresh the public key every hour in the background."""
        while True:
            await asyncio.sleep(_JWKS_REFRESH_INTERVAL_SECONDS)
            try:
                new_key = await self._fetch_public_key()
                self._public_key = new_key
                if hasattr(self, "app") and hasattr(self.app, "state"):
                    self.app.state._internal_jwt_public_key = new_key
                logger.info("internal_jwt_public_key_refreshed")
            except Exception as exc:
                self._log_background_refresh_failure(exc)

    def _log_background_refresh_failure(self, exc: Exception) -> None:
        """Hook: log a background-refresh failure (subclass can sanitise)."""
        logger.warning("internal_jwt_public_key_refresh_failed", error=str(exc))

    async def _fetch_public_key(self) -> RSAPublicKey:
        """Fetch JWKS from S9 and populate ``self._keys_by_kid``.

        Returns the first key (back-compat with the legacy single-key contract).
        W1-05: also fills ``self._keys_by_kid`` so dispatch can resolve any kid
        present in the JWKS (current key + grace-window previous keys).  Entries
        without a ``kid`` field default to ``"v1"`` so backends still verify
        against a pre-W1-05 S9 during the rollout window.
        """
        # Imports are local to keep observability importable in environments
        # without httpx/cryptography (e.g. pure-logger consumers).
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
        # Atomic swap under the GIL — concurrent dispatchers see either the old
        # or new map, never a half-populated one.
        self._keys_by_kid = new_map
        return first_key

    async def _refresh_jwks_if_allowed(self) -> bool:
        """W1-05: refresh JWKS on kid-miss, rate-limited to 1 fetch / 60 s / process.

        Returns ``True`` if a refresh actually ran (caller should retry the
        kid lookup), ``False`` if the cooldown is still active (caller should
        reject the request without retrying).  Defense against DoS amplification.
        """
        global _last_refresh_ts  # — module-level cooldown is intentional
        now = time.monotonic()
        with _refresh_lock:
            if now - _last_refresh_ts < _REFRESH_COOLDOWN_SECONDS:
                return False
            # Reserve the cooldown slot BEFORE the await so concurrent requests
            # don't all see "cooldown elapsed" and stampede.
            _last_refresh_ts = now
        try:
            new_key = await self._fetch_public_key()
            self._public_key = new_key
            if hasattr(self, "app") and hasattr(self.app, "state"):
                self.app.state._internal_jwt_public_key = new_key
            logger.info(
                "internal_jwt_jwks_refreshed_on_kid_miss",
                known_kids=list(self._keys_by_kid.keys()),
            )
            return True
        except Exception as exc:  # — fault-tolerant refresh
            # On fetch failure (network blip, S9 5xx) the up-front cooldown
            # reservation would otherwise lock us out for the full 60 s even
            # though no refresh succeeded. Reset the timestamp so the next
            # attempt is allowed after a short back-off (5 s) — preserves the
            # stampede defense (concurrent callers in the window still see the
            # reserved slot) while giving the user a fast retry on transient
            # errors. Post-audit code-review SF #1.
            with _refresh_lock:
                _last_refresh_ts = now - _REFRESH_COOLDOWN_SECONDS + 5
            logger.warning("internal_jwt_jwks_refresh_on_miss_failed", error=str(exc))
            return False

    # ── Request handling ─────────────────────────────────────────────────────
    def _load_token(self, request: Request) -> str | None:
        """Hook: extract the JWT from a request.

        Default: read ``X-Internal-JWT`` header.  Alert overrides this to read
        ``?token=`` on WebSocket-upgrade requests (browsers can't set custom
        headers via ``new WebSocket(url)``).
        """
        return request.headers.get("X-Internal-JWT")  # type: ignore[no-any-return]

    def _invalid_token_response(self) -> Response:
        """Hook: build the 401 response body for an invalid token.

        Default: ``{"detail": "Invalid internal JWT"}``.  rag-chat returns an
        opaque ``"Unauthorized"`` to avoid leaking validation details
        externally (F-S001).
        """
        return Response(
            content='{"detail":"Invalid internal JWT"}',
            status_code=401,
            media_type="application/json",
        )

    def _expired_token_response(self) -> Response:
        """Hook: build the 401 response body for an expired token."""
        return Response(
            content='{"detail":"Internal JWT expired"}',
            status_code=401,
            media_type="application/json",
        )

    def _missing_token_response(self) -> Response:
        return Response(
            content='{"detail":"Missing X-Internal-JWT header"}',
            status_code=401,
            media_type="application/json",
        )

    def _no_public_key_response(self) -> Response:
        return Response(
            content='{"detail":"Service Unavailable — JWKS not loaded"}',
            status_code=503,
            media_type="application/json",
        )

    def _replay_response(self) -> Response:
        return Response(
            content='{"detail":"Token replay detected"}',
            status_code=401,
            media_type="application/json",
        )

    async def _unverified_decode(self, request: Request, token: str) -> Response | None:
        """Hook: handle skip_verification=True path.

        Default: decode without signature verification, set tenant/user/role,
        and continue.  Returns ``None`` to indicate "continue to call_next" or
        a ``Response`` to short-circuit.  Subclasses (rag-chat) can enforce
        minimum-claim checks here.

        Note: the dispatcher calls ``await call_next(request)`` after this
        hook returns ``None``.
        """
        # Demoted from CRITICAL → DEBUG: skip_verification=True is the expected
        # dev/E2E path (documented in docker.env).  Logging at CRITICAL produced
        # ~1800 CRITICAL lines per 10 min, drowning real alert signals.
        # The startup log records internal_jwt_skip_verification_enabled at WARNING
        # once at boot, which is sufficient for ops awareness.
        logger.debug(
            "internal_jwt_unverified_decode",
            detail="Decoding JWT WITHOUT signature verification (skip_verification=True).",
        )
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
            # PLAN-0094 follow-up: parity with the verified-decode path.
            request.state.service_name = payload.get("service_name", "")
        except jwt.DecodeError:
            request.state.tenant_id = ""
            request.state.user_id = ""
            request.state.role = ""
            request.state.service_name = ""
        return None

    async def _jti_replay_check(
        self,
        request: Request,
        jti: str,
        exp: int,
    ) -> Response | None:
        """Hook: F-012 JTI replay protection via Valkey SET NX.

        Returns ``None`` if the JTI is fresh (or Valkey is unavailable — fail-open),
        or a ``Response`` to reject as a replay.  Subclasses can override the
        whole check (e.g. rag-chat increments ``rag_jti_check_bypass_total`` on
        fail-open).
        """
        valkey = getattr(request.app.state, self._valkey_attr, None)
        if valkey is None:
            return None
        # TTL = remaining token lifetime + 60 s buffer (handles clock skew).
        # max(1, ...) prevents a zero-or-negative TTL on an about-to-expire token.
        ttl = max(1, int(exp - time.time()) + 60)
        # JTI key shape: services that originally hardcoded ``jti:{jti}`` keep
        # that; newer services include the service_name to isolate replay
        # checks per service.  Controlled by jti_key_includes_service_name.
        jti_key = f"jti:{self._service_name}:{jti}" if self._jti_key_includes_service_name else f"jti:{jti}"
        try:
            was_new = await valkey.set_nx(jti_key, "1", ex=ttl)
            if not was_new:
                logger.warning("jti_replay_detected", jti=jti)
                return self._replay_response()
        except Exception:
            # Fail-open: Valkey unavailability must not block requests.  JWT
            # signature + expiry remain validated.  Counter enables alerting.
            self._on_jti_check_bypass(jti)
        return None

    def _on_jti_check_bypass(self, jti: str) -> None:
        """Hook: called when the JTI replay check fails open (Valkey unavailable).

        Default: WARNING log only.  rag-chat increments a Prometheus counter
        (``rag_jti_check_bypass_total``) on top of the log line (F-S004).
        """
        logger.warning("jti_check_valkey_unavailable", jti=jti)

    async def _post_validate(self, request: Request, token: str, payload: dict[str, Any]) -> None:
        """Hook: runs after successful decode + JTI check.

        Default: no-op.  rag-chat sets a ContextVar (``set_current_jwt``) so
        upstream service clients can forward ``X-Internal-JWT`` without
        threading the token through every method signature.  nlp-pipeline
        stores the raw token on ``request.state.internal_jwt``.
        """
        # — interface contract; subclasses use the params

    def _on_invalid_token(self, exc: Exception) -> None:
        """Hook: log an invalid (non-expired) token.

        Default: DEBUG with error string.  portfolio logs at WARNING (D-F2-001)
        with the exception class name so production logs surface the real
        decode-failure reason without reconfiguring log levels.
        """
        logger.debug("internal_jwt_invalid", error=str(exc))

    def _on_expired_token(self) -> None:
        """Hook: log an expired token.

        Default: no log line (the 401 response is enough).  rag-chat logs
        ``internal_jwt_expired`` at INFO so structlog preserves observability
        without leaking detail to the external body.
        """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip health / metrics / service-specific prefixes.
        if path in self._skip_paths or any(path.startswith(pfx) for pfx in self._skip_prefixes):
            return cast("Response", await call_next(request))

        token = self._load_token(request)
        if not token:
            return self._missing_token_response()

        # BP-159: Read from app.state (shared across instances), fallback to self
        # (so tests that monkey-patch ``self._public_key`` still work).
        public_key = getattr(request.app.state, "_internal_jwt_public_key", None) or self._public_key

        # market-data parity (PLAN-0052 platform-QA fix, 2026-05-01): when
        # ``skip_verification_takes_precedence=True`` AND ``skip_verification=True``,
        # ALWAYS take the unverified-decode path — not just when the public_key
        # is missing.  The previous gating only honoured skip_verification when
        # the JWKS load FAILED, which meant any service starting up successfully
        # (loading a real RS256 public key from S9) would then reject HS256 dev
        # tokens with 401.  Other services historically gate skip_verification
        # only when public_key is None; that's the default.
        if self._skip_verification_takes_precedence and self._skip_verification:
            short = await self._unverified_decode(request, token)
            if short is not None:
                return short
            return cast("Response", await call_next(request))

        # rag-chat parity (F-001 with eager unverified path): the same pattern
        # without the ``takes_precedence`` flag — rag-chat decides via subclass
        # override of dispatch.  To keep dispatch single-source-of-truth, we
        # expose the same behaviour via the takes-precedence flag.

        if public_key is None:
            if not self._skip_verification:
                # F-001: fail-closed — without the public key we cannot verify
                # signatures, so accepting tokens would let any forged JWT pass.
                logger.error(
                    "internal_jwt_no_public_key",
                    detail="JWKS public key not loaded — rejecting request (fail-closed).",
                )
                return self._no_public_key_response()
            # skip_verification + no key: fall through to the unverified-decode
            # path so the dev/E2E stack works even when S9 isn't reachable.
            short = await self._unverified_decode(request, token)
            if short is not None:
                return short
            return cast("Response", await call_next(request))

        # W1-05 (BUG-005): resolve the public key by ``kid`` from the JWT
        # header so S9 can rotate signing keys without restarting backends.
        # If the kid is not in our cache, attempt one rate-limited refresh and
        # retry the lookup.  If still missing, reject with 401 (the kid was
        # never valid OR the rotation grace window expired).  Fallback chain:
        # kid lookup → legacy single-key path (back-compat with tests that
        # monkey-patch ``self._public_key`` without populating ``_keys_by_kid``).
        verification_key = public_key
        try:
            token_kid = jwt.get_unverified_header(token).get("kid") or _DEFAULT_KID
        except jwt.DecodeError:
            # Malformed token — defer to the main decode block to emit 401
            # with the consistent rejection shape.
            token_kid = _DEFAULT_KID
        if self._keys_by_kid:
            mapped = self._keys_by_kid.get(token_kid)
            if mapped is None:
                refreshed = await self._refresh_jwks_if_allowed()
                if refreshed:
                    mapped = self._keys_by_kid.get(token_kid)
                if mapped is None:
                    logger.warning(
                        "internal_jwt_unknown_kid",
                        token_kid=token_kid,
                        known_kids=list(self._keys_by_kid.keys()),
                        refreshed=refreshed,
                    )
                    return self._invalid_token_response()
            verification_key = mapped

        try:
            # F-015: pass issuer= so PyJWT validates ``iss`` internally and raises
            # InvalidIssuerError before we touch the payload.  DEF-002: validate
            # ``aud`` so a token issued for service A cannot be replayed at
            # service B (lateral movement prevention).
            payload = jwt.decode(
                token,
                verification_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["sub", "tenant_id", "role", "exp", "iss", "aud"]},
            )

            # F-012: JTI replay detection — only when enabled.  IMPORTANT: set
            # ``jti_replay_check_enabled=False`` for internal-only services
            # (S6, S7) because S8 forwards the same JWT to these services
            # multiple times within a single user request (e.g. embed + chunk
            # search).  The user-facing boundary check at S8 is sufficient;
            # re-checking here causes false 401 replays.
            jti = payload.get("jti")
            exp = payload.get("exp", 0)
            if jti and self._jti_replay_check_enabled:
                replay_short = await self._jti_replay_check(request, jti, exp)
                if replay_short is not None:
                    return replay_short

            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
            # PLAN-0094 follow-up: expose ``service_name`` so downstream handlers
            # can recognise system-identity callers (e.g. rag-chat brief
            # pre-generation worker) issued via S9 POST /internal/v1/service-token.
            # Empty string for user tokens — safe for all existing handlers.
            request.state.service_name = payload.get("service_name", "")

            # Hook: per-service post-validate actions (e.g. ContextVar, raw token).
            await self._post_validate(request, token, payload)
        except jwt.ExpiredSignatureError:
            self._on_expired_token()
            return self._expired_token_response()
        except Exception as exc:
            # Catch jwt.InvalidTokenError AND any other validation error
            # consistently — the original copies were inconsistent here (some
            # caught only InvalidTokenError, others caught Exception).  Catching
            # Exception keeps the most permissive of the historical behaviours
            # while still returning the unified 401 response.
            self._on_invalid_token(exc)
            return self._invalid_token_response()

        return cast("Response", await call_next(request))


__all__ = [
    "DEFAULT_SKIP_PATHS",
    "DEFAULT_SKIP_PREFIXES",
    "InternalJWTMiddleware",
]
