"""Backward-compatible re-export of the JWT ContextVar.

The canonical module is now ``rag_chat.application.auth_context`` (moved
in F-ARCH-001 to satisfy LAYER-APP-ISOLATION — the application-layer worker
needs to import the setter, and the application layer must not depend on
infrastructure). This shim keeps the original import path working for the
many api routes, infrastructure clients, and tests that still import from
the old location.
"""

from __future__ import annotations

from rag_chat.application.auth_context import get_current_jwt, set_current_jwt

__all__ = ["get_current_jwt", "set_current_jwt"]
