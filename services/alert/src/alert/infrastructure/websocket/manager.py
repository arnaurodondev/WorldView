"""WebSocket connection manager for S10 alert delivery.

.. warning:: **Single-replica constraint**

    Connections are stored in process memory.  Running ≥2 replicas of S10
    requires an out-of-process fan-out layer (e.g. Redis Pub/Sub) so that a
    push to any replica reaches the correct user.  The current deployment is
    single-replica; this constraint is documented in
    ``docs/services/alert-service.md``.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = get_logger(__name__)  # type: ignore[no-any-return]


class ConnectionManager:
    """In-memory registry of active WebSocket connections, keyed by user_id.

    Thread-safety: designed for single-threaded asyncio; do NOT call from
    multiple threads without external locking.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, WebSocket] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for *user_id*.

        If *user_id* already has an active connection it is replaced
        (handles reconnects gracefully).
        """
        await websocket.accept()
        self._connections[user_id] = websocket
        logger.info("websocket_connected", user_id=str(user_id))  # type: ignore[no-any-return]

    def disconnect(self, user_id: UUID) -> None:
        """Deregister the connection for *user_id*.  No-op if not connected."""
        removed = self._connections.pop(user_id, None)
        if removed is not None:
            logger.info("websocket_disconnected", user_id=str(user_id))  # type: ignore[no-any-return]

    # ── Queries ───────────────────────────────────────────────────────────────

    def is_connected(self, user_id: UUID) -> bool:
        """Return ``True`` if *user_id* has an active connection."""
        return user_id in self._connections

    @property
    def active_count(self) -> int:
        """Number of currently connected users."""
        return len(self._connections)

    # ── Messaging ─────────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: UUID, data: dict[str, Any]) -> bool:
        """Send *data* as JSON to *user_id*.

        Returns ``True`` on success, ``False`` when the user is not connected
        or the send fails.  On failure the stale connection is cleaned up.
        """
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "websocket_send_failed",
                user_id=str(user_id),
            )
            self.disconnect(user_id)
            return False

    async def broadcast(self, data: dict[str, Any]) -> int:
        """Send *data* to all connected users.

        Returns the number of successful deliveries.
        Stale connections are cleaned up on failure (via ``send_to_user``).
        """
        sent = 0
        # Snapshot the key set to avoid mutation-during-iteration issues.
        for user_id in list(self._connections):
            with contextlib.suppress(Exception):
                if await self.send_to_user(user_id, data):
                    sent += 1
        return sent
