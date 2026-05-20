"""InternalJWTMiddleware — content-ingestion (S4) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S4 uses the
shared defaults: JTI key is ``jti:{jti}`` (no service_name prefix), Valkey on
``app.state.valkey``.

PRD-0025 §6.5 (InternalJWTMiddleware spec).
"""

from __future__ import annotations

from typing import Any

from observability.internal_jwt import (
    _DEFAULT_KID,  # noqa: F401 — re-exported for test parity
    _REFRESH_COOLDOWN_SECONDS,  # noqa: F401
    _last_refresh_ts,  # noqa: F401
    _refresh_lock,  # noqa: F401
)
from observability.internal_jwt import (
    InternalJWTMiddleware as _Shared,
)


class InternalJWTMiddleware(_Shared):
    """S4 content-ingestion InternalJWTMiddleware — uses shared defaults."""

    def __init__(
        self,
        app: Any,
        jwks_url: str,
        *,
        skip_verification: bool = False,
    ) -> None:
        super().__init__(
            app,
            jwks_url,
            skip_verification=skip_verification,
        )


__all__ = ["InternalJWTMiddleware"]
