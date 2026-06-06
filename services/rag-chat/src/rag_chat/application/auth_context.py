"""Per-request internal JWT propagation via asyncio ContextVar.

WHY this lives in the application layer (F-ARCH-001 / LAYER-APP-ISOLATION):
the morning-brief pre-generation worker (application layer) needs to set the
JWT ContextVar for each user it processes so downstream upstream clients pick
it up.  Importing from ``rag_chat.infrastructure`` would invert the layer
dependency (application must not depend on infrastructure).

The module exposes a pure ContextVar with no infra dependencies; the original
location ``rag_chat.infrastructure.clients.auth_context`` re-exports these
names for backward compatibility (api routes, infra clients, middleware).
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


__all__ = ["get_current_jwt", "set_current_jwt"]
