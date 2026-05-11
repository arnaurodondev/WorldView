"""InstrumentRef entity — local reference copy synced from Market Data service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]


@dataclass
class InstrumentRef:
    """Read-only reference to a financial instrument, sourced from market.instrument events.

    ``source_event_id`` is retained to enable idempotent consumer re-processing.
    ``entity_id`` links to the KG canonical entity when available; not a cross-service FK (R7).
    """

    symbol: str
    exchange: str
    source_event_id: UUID
    name: str | None = None
    currency: str | None = None
    # PLAN-0053 T-D-4-02: now non-null at the DB layer (server_default='unknown'
    # via migration 0016). The domain remains ``str | None`` so adapters that
    # don't know the class can pass ``None`` — the repository normalises that
    # to ``'unknown'`` on save (see InstrumentRepository.save).
    asset_class: str | None = None
    entity_id: UUID | None = None
    id: UUID = field(default_factory=new_uuid)
    synced_at: datetime = field(default_factory=utc_now)
