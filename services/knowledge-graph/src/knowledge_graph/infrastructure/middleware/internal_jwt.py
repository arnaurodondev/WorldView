"""InternalJWTMiddleware — knowledge-graph (S7) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S7 specifics:

* JTI key includes ``service_name``.
* Propagates the ``skip_verification`` flag to ``app.state``.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

from typing import Any

from observability.internal_jwt import (  # type: ignore[import-untyped]
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (  # type: ignore[import-untyped]
    InternalJWTMiddleware as _Shared,
)


class InternalJWTMiddleware(_Shared):
    """S7 knowledge-graph InternalJWTMiddleware."""

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


__all__ = ["InternalJWTMiddleware"]
