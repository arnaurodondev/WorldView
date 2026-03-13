"""market_data domain package — pure Python, no framework dependencies.

Public symbols are re-exported here for a clean import surface:

    from market_data.domain import Security, Instrument, OHLCVBar
    from market_data.domain import InstrumentCreated, MarketDataError
"""

from market_data.domain.entities import (
    FundamentalsRecord,
    Instrument,
    OHLCVBar,
    Quote,
    Security,
)
from market_data.domain.enums import (
    DatasetType,
    FundamentalsSection,
    PeriodType,
    Provider,
    Timeframe,
)
from market_data.domain.errors import (
    DuplicateEventError,
    IngestionError,
    InstrumentNotFoundError,
    MarketDataError,
    ParseError,
    SecurityNotFoundError,
    StaleDataError,
)
from market_data.domain.events import (
    DomainEvent,
    InstrumentCreated,
    InstrumentUpdated,
)
from market_data.domain.value_objects import (
    InstrumentFlags,
    ProviderPriority,
)

__all__ = [
    "DatasetType",
    "DomainEvent",
    "DuplicateEventError",
    "FundamentalsRecord",
    "FundamentalsSection",
    "IngestionError",
    "Instrument",
    "InstrumentCreated",
    "InstrumentFlags",
    "InstrumentNotFoundError",
    "InstrumentUpdated",
    "MarketDataError",
    "OHLCVBar",
    "ParseError",
    "PeriodType",
    "Provider",
    "ProviderPriority",
    "Quote",
    "Security",
    "SecurityNotFoundError",
    "StaleDataError",
    "Timeframe",
]
