"""WatchlistMember domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class WatchlistMember:
    """A single entity tracked within a watchlist.

    ``entity_id`` is the KG canonical entity UUID — intentionally not a
    cross-service FK (R7). ``entity_type`` is a free-form label such as
    ``"company"`` or ``"etf"``.

    ``ticker``, ``name`` and ``instrument_id`` are denormalised snapshots
    resolved at add-time (PLAN-0046 T-46-2-01). They may be ``None`` for
    historical rows that pre-date Alembic 0010 or when the lookup against the
    local ``instruments`` table failed (caller still wins — the write
    succeeds and the row appears with a "—" placeholder until re-added).
    """

    id: UUID
    watchlist_id: UUID
    entity_id: UUID
    entity_type: str
    added_at: datetime
    ticker: str | None = None
    name: str | None = None
    instrument_id: UUID | None = None
    # REQ-002b: caller-supplied ``Idempotency-Key`` (UUID). NULL for legacy
    # rows + callers that don't send the header. Partial unique index on
    # (watchlist_id, idempotency_key) enforces uniqueness only when set.
    idempotency_key: UUID | None = None
