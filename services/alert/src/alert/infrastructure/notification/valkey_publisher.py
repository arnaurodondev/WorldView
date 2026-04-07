"""ValkeyNotificationPublisher — Valkey pub/sub notification adapter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from uuid import UUID

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


class ValkeyNotificationPublisher:
    """Publishes real-time alert notifications via Valkey pub/sub.

    Each user has a dedicated channel: ``alert:{user_id}``.
    Fire-and-forget — no retry, no durability guarantee.
    Durability is handled by the Kafka outbox (``alert.delivered.v1``).
    """

    def __init__(self, valkey_client: ValkeyClient) -> None:
        self._valkey = valkey_client

    async def send_to_user(self, user_id: UUID, payload: dict[str, Any]) -> None:
        """Publish *payload* to the user's Valkey channel.

        Args:
        ----
            user_id: Target user's UUID.
            payload: Notification payload serialised as JSON.

        Note:
        ----
            Best-effort: if the user has no active WebSocket subscription the
            message is silently dropped.  Exceptions are logged and suppressed.

        """
        channel = f"alert:{user_id}"
        try:
            await self._valkey.publish(channel, json.dumps(payload, default=str))
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "notification_publish_failed",
                user_id=str(user_id),
                exc_info=True,
            )
