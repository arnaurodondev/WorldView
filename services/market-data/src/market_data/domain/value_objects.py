"""Value objects for the market-data domain.

Value objects are immutable by design (frozen dataclasses).  Equality is
structural — two instances with the same field values are considered identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.domain.enums import Provider


@dataclass(frozen=True)
class ProviderPriority:
    """Immutable coupling of a provider identifier with its numeric priority.

    Higher ``priority`` values are preferred when resolving conflicts between
    data from multiple providers (e.g. OHLCV upsert strategy).
    """

    provider: str
    priority: int

    @classmethod
    def for_provider(cls, provider: Provider) -> ProviderPriority:
        """Build a ``ProviderPriority`` from a ``Provider`` enum member."""
        return cls(provider=provider.value, priority=provider.priority)


@dataclass(frozen=True)
class InstrumentFlags:
    """Capability flags indicating which dataset types exist for an instrument.

    Set to ``True`` once at least one record of that type has been ingested.
    Used to drive fast-path checks (e.g. cache warm-up, API availability).
    """

    has_ohlcv: bool = False
    has_quotes: bool = False
    has_fundamentals: bool = False
