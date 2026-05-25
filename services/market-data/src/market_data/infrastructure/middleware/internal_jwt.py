"""InternalJWTMiddleware — market-data (S3) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S3 specifics:

* Valkey client lives on ``app.state.valkey_client`` (not the default ``valkey``).
* JTI key includes ``service_name``.
* ``skip_verification=True`` ALWAYS takes the unverified-decode path
  (PLAN-0052 platform-QA fix, 2026-05-01) so a service that loaded a real
  RS256 key still accepts HS256 dev tokens.
* Unverified-decode log demoted CRITICAL → DEBUG (PLAN-0088 SA-5, 2026-05-10)
  to avoid drowning alert signals when skip_verification=True is the
  documented dev/E2E path.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
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
    """S3 market-data InternalJWTMiddleware."""

    def __init__(
        self,
        app: Any,
        jwks_url: str,
        *,
        skip_verification: bool = False,
        service_name: str = "unknown",
        jti_replay_check_enabled: bool = True,
    ) -> None:
        super().__init__(
            app,
            jwks_url,
            service_name=service_name,
            skip_verification=skip_verification,
            jti_replay_check_enabled=jti_replay_check_enabled,
            valkey_attr="valkey_client",
            jti_key_includes_service_name=True,
            skip_verification_takes_precedence=True,
        )

    async def _unverified_decode(self, request: Request, token: str) -> Response | None:
        """Demoted from CRITICAL → DEBUG (PLAN-0088 SA-5, 2026-05-10).

        skip_verification=True is the expected, intentional dev/E2E path.
        Logging this at CRITICAL produced ~1800 CRITICAL lines per 10 min,
        drowning real alert signals.  The startup log records
        ``internal_jwt_skip_verification_enabled`` at CRITICAL once at boot,
        which is sufficient for ops awareness.
        """
        logger.debug(
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
        return None


__all__ = ["InternalJWTMiddleware"]
