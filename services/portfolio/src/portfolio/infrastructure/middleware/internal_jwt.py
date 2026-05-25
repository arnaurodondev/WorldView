"""InternalJWTMiddleware — portfolio (S1) thin subclass.

REF-001 (W2-05): the bulk of the logic now lives in
``observability.internal_jwt``.  This module exists as a thin subclass that
applies portfolio's two historical differences:

* No JTI replay check (``jti_replay_check_enabled=False``).
* The ``internal_jwt_invalid`` log line is emitted at WARNING (D-F2-001,
  PLAN-0087, 2026-05-09) with the exception class name so production logs
  surface decode-failure reasons without reconfiguring log levels.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

from typing import Any

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test monkey-patch parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (  # type: ignore[import-untyped]
    InternalJWTMiddleware as _Shared,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class InternalJWTMiddleware(_Shared):
    """S1 portfolio InternalJWTMiddleware — no JTI replay; WARNING on invalid."""

    def __init__(
        self,
        app: Any,
        jwks_url: str,
        issuer: str = "worldview-gateway",
        *,
        skip_verification: bool = False,
    ) -> None:
        # Portfolio's only constructor differences vs. the shared default are
        # the positional ``issuer`` parameter (kept for backwards-compatible
        # callsites that pass it positionally) and disabling the JTI check.
        super().__init__(
            app,
            jwks_url,
            issuer=issuer,
            skip_verification=skip_verification,
            jti_replay_check_enabled=False,
        )

    def _on_invalid_token(self, exc: Exception) -> None:
        """D-F2-001 (PLAN-0087, 2026-05-09): WARNING with error class name.

        Elevated from DEBUG → WARNING so production logs surface the actual
        decode failure (signature / issuer / audience / expiry) at a glance
        without reconfiguring log levels.
        """
        logger.warning(
            "internal_jwt_invalid",
            error_class=type(exc).__name__,
            error=str(exc),
        )


__all__ = ["InternalJWTMiddleware"]
