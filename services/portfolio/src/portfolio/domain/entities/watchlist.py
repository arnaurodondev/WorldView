"""Watchlist domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from portfolio.domain.enums import WatchlistStatus


@dataclass(frozen=True)
class Watchlist:
    """A named list of entities a user wants to track within a tenant.

    Unique constraint: (user_id, name) for active watchlists.
    """

    id: UUID
    tenant_id: UUID
    user_id: UUID
    name: str
    status: WatchlistStatus
    created_at: datetime

    def is_active(self) -> bool:
        return self.status == WatchlistStatus.ACTIVE
