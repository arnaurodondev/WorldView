"""INotificationPublisher — application port for real-time notification delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from uuid import UUID


@runtime_checkable
class INotificationPublisher(Protocol):
    """Port for delivering real-time notifications to connected users.

    Best-effort: no retry, no durability guarantee.
    Durability is provided by the Kafka outbox (``alert.delivered.v1``).

    Both :class:`~alert.infrastructure.websocket.manager.ConnectionManager` (API process)
    and :class:`~alert.infrastructure.notification.valkey_publisher.ValkeyNotificationPublisher`
    (standalone consumer process) satisfy this protocol.
    """

    async def send_to_user(self, user_id: UUID, payload: dict[str, Any]) -> None:
        """Publish a real-time notification to a connected user.

        Args:
            user_id: Target user's UUID.
            payload: Notification payload (serialised by the implementation).

        Note:
            Implementations must silently no-op if the user is not reachable.
        """
        ...
