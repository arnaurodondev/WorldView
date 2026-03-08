"""InstrumentRef entity — local reference copy synced from Market Data service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class InstrumentRef:
    """Read-only reference to a financial instrument, sourced from market.instrument events.

    ``source_event_id`` is retained to enable idempotent consumer re-processing.
    """

    symbol: str
    exchange: str
    source_event_id: UUID
    name: str | None = None
    currency: str | None = None
    asset_class: str | None = None
    id: UUID = field(default_factory=new_uuid)
    synced_at: datetime = field(default_factory=utc_now)
