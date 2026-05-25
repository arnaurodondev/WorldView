"""InternalJWTMiddleware — alert (S10) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S10 specifics:

* Extra skip prefix ``/admin`` — these endpoints are protected by
  ``X-Admin-Token`` (AdminAuthDep) and do not require ``X-Internal-JWT``.
* WebSocket upgrades: browsers cannot set custom headers via
  ``new WebSocket(url)``, so the token comes from a ``?token=`` query param
  on the upgrade request (issued by ``GET /v1/auth/ws-token``, 30s TTL,
  RS256 signed).
* Unverified-decode also accepts HS256 (dev tokens).
* ``BP-159b`` — the ``_internal_jwt_skip_verification`` flag is also stored
  on ``app.state`` so WebSocket handlers (which bypass BaseHTTPMiddleware
  dispatch) can read it.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import jwt

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    DEFAULT_SKIP_PREFIXES,
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (  # type: ignore[import-untyped]
    InternalJWTMiddleware as _Shared,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from fastapi import Request, Response

logger = get_logger(__name__)


class InternalJWTMiddleware(_Shared):
    """S10 alert InternalJWTMiddleware — WebSocket token + /admin skip."""

    def __init__(
        self,
        app: Any,
        jwks_url: str,
        *,
        skip_verification: bool = False,
        jti_replay_check_enabled: bool = True,
    ) -> None:
        super().__init__(
            app,
            jwks_url,
            skip_verification=skip_verification,
            jti_replay_check_enabled=jti_replay_check_enabled,
            # Extra ``/admin`` prefix: admin endpoints use X-Admin-Token, not JWT.
            skip_prefixes=(*DEFAULT_SKIP_PREFIXES, "/admin"),
        )
        # BP-159b: also expose the skip_verification flag on app.state so
        # WebSocket handlers (which bypass BaseHTTPMiddleware dispatch) can
        # consult it without re-instantiating the middleware.
        if skip_verification and hasattr(app, "state"):
            with contextlib.suppress(AttributeError):
                app.state._internal_jwt_skip_verification = True

    def _load_token(self, request: Request) -> str | None:
        """WebSocket upgrades read ``?token=`` query param (HS256/RS256 dev tokens).

        Browsers cannot set custom headers on ``new WebSocket(url)`` — the
        gateway issues a short-lived (30s TTL) RS256 token via
        ``GET /v1/auth/ws-token`` which the client appends to the WS URL.
        """
        is_ws_upgrade = request.headers.get("upgrade", "").lower() == "websocket"
        if is_ws_upgrade:
            return request.query_params.get("token")  # type: ignore[no-any-return]
        return request.headers.get("X-Internal-JWT")  # type: ignore[no-any-return]

    async def _unverified_decode(self, request: Request, token: str) -> Response | None:
        """Accept HS256 OR RS256 in dev mode (parity with the original S10 path)."""
        logger.debug(
            "internal_jwt_unverified_decode",
            detail="Decoding JWT WITHOUT signature verification (skip_verification=True).",
        )
        try:
            payload = jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["HS256", "RS256"],
            )
            request.state.tenant_id = payload.get("tenant_id", "")
            request.state.user_id = payload.get("sub", "")
            request.state.role = payload.get("role", "")
        except jwt.DecodeError:
            request.state.tenant_id = ""
            request.state.user_id = ""
            request.state.role = ""
        return None


__all__ = ["InternalJWTMiddleware"]
