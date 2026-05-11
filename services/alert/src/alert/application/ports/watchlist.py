"""IWatchlistCache — application port for watchlist lookups."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IWatchlistCache(Protocol):
    """Port for resolving watchers for a given entity.

    Returns the list of user watchlist entries watching a given entity_id.
    Implementations may use Valkey cache-aside backed by S1 REST.
    """

    async def get_watchers(self, entity_id: str) -> list[Any]:
        """Return watcher entries for the given entity_id.

        Args:
        ----
            entity_id: String UUID of the entity.

        Returns:
        -------
            List of watcher objects with at least a ``user_id`` attribute.
            Returns empty list if no watchers or entity not found.

        """
        ...
