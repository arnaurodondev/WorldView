"""InternalJWTMiddleware — nlp-pipeline (S6) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S6 specifics:

* JTI key includes ``service_name`` (``jti:{service_name}:{jti}``).
* The raw JWT is stashed on ``request.state.internal_jwt`` so downstream use
  cases can forward it to other backend services (e.g. S6 → S5 batch calls).
* The ``_internal_jwt_skip_verification`` flag is propagated to ``app.state``
  for non-HTTP code paths.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (  # type: ignore[import-untyped]
    InternalJWTMiddleware as _Shared,
)

if TYPE_CHECKING:
    from fastapi import Request


class InternalJWTMiddleware(_Shared):
    """S6 nlp-pipeline InternalJWTMiddleware — stores token on request.state."""

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
            jti_key_includes_service_name=True,
            set_skip_verification_on_state=True,
        )

    async def _post_validate(self, request: Request, token: str, payload: dict[str, Any]) -> None:
        """Store raw token so downstream use cases can forward X-Internal-JWT.

        Reading from ``request.state`` is more reliable than re-reading
        ``request.headers`` through stacked BaseHTTPMiddleware wrappers.
        """
        request.state.internal_jwt = token


__all__ = ["InternalJWTMiddleware"]
