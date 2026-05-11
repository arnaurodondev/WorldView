"""SymbolTier entity — maps a symbol+exchange to a cadence tier for quota-aware scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from common.ids import new_ulid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime


class TierLevel(IntEnum):
    """Polling cadence tiers, ordered from most-frequent (0) to least-frequent (4).

    Higher tiers receive less frequent EODHD API calls, preserving quota for
    actively-used symbols.
    """

    T0 = 0  # Portfolio holdings — actively held positions, highest cadence
    T1 = 1  # Watchlist — user-tracked but not held
    T2 = 2  # Tracked instruments — screener universe, active (default)
    T3 = 3  # Screener-only — comparison universe, infrequent
    T4 = 4  # Inactive — not recently accessed, minimal polling


@dataclass
class SymbolTier:
    """Maps a symbol+exchange pair to a tier level for cadence-aware scheduling.

    The tier determines the base_interval multiplier applied by the scheduler.
    T0 symbols poll at full cadence; T4 symbols may be deferred entirely.
    """

    id: str = field(default_factory=new_ulid)
    symbol: str = ""
    exchange: str = ""
    tier: TierLevel = TierLevel.T2  # default = quota-safe T2
    tier_source: str = "default"  # "default" | "portfolio" | "watchlist" | "screener" | "user"
    assigned_at: datetime = field(default_factory=utc_now)
    last_user_refresh_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
