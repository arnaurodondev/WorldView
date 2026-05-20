"""InternalJWTMiddleware — market-ingestion (S2) thin subclass.

REF-001 (W2-05): logic lives in ``observability.internal_jwt``.  S2 uses the
shared defaults: JTI key is ``jti:{jti}`` (no service_name prefix), Valkey on
``app.state.valkey`` (typically unset on S2 so the JTI check no-ops safely).

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
    """S2 market-ingestion InternalJWTMiddleware — uses shared defaults."""

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
