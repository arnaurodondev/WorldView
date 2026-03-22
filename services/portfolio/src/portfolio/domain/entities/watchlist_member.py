"""WatchlistMember domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True)
class WatchlistMember:
    """A single entity tracked within a watchlist.

    ``entity_id`` is the KG canonical entity UUID — intentionally not a
    cross-service FK (R7). ``entity_type`` is a free-form label such as
    ``"company"`` or ``"etf"``.
    """

    id: UUID
    watchlist_id: UUID
    entity_id: UUID
    entity_type: str
    added_at: datetime
