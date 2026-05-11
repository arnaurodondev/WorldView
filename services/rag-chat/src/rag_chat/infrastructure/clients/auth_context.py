"""Per-request internal JWT propagation via asyncio ContextVar.

WHY CONTEXTVAR: S6Client and S7Client are singleton objects created at startup.
They cannot carry per-request state directly. Python's ContextVar propagates
correctly across asyncio Task boundaries — each request gets its own context.

The InternalJWTMiddleware sets the ContextVar after validating the incoming JWT.
BaseUpstreamClient reads it and adds X-Internal-JWT to all outgoing calls.
This pattern avoids threading request state through every method signature.
"""

from __future__ import annotations

import contextvars

# Holds the X-Internal-JWT token for the current request.
# Default None means "no JWT set" (e.g., health checks, startup probes).
_current_internal_jwt: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_internal_jwt",
    default=None,
)


def set_current_jwt(token: str | None) -> None:
    """Set the internal JWT for the current async context (call from middleware)."""
    _current_internal_jwt.set(token)


def get_current_jwt() -> str | None:
    """Get the internal JWT for the current async context (call from clients)."""
    return _current_internal_jwt.get()
