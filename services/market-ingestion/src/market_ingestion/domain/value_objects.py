"""Domain value objects for the Market Ingestion service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_VALID_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo", "1y"})


class Timeframe:
    """Validated timeframe string value object.

    Valid values: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo, 1y.
    Raises ValueError on construction if the value is not in the valid set.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if value not in _VALID_TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {value!r}. Valid: {sorted(_VALID_TIMEFRAMES)}")
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Timeframe({self._value!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Timeframe):
            return self._value == other._value
        if isinstance(other, str):
            return self._value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class ObjectRef:
    """Immutable reference to an object in object storage (claim-check pointer)."""

    bucket: str
    key: str
    sha256: str
    byte_length: int
    mime_type: str


@dataclass(frozen=True)
class InstrumentKey:
    """Identifies a financial instrument by symbol and optional exchange."""

    symbol: str
    exchange: str | None = None


@dataclass(frozen=True)
class DateRange:
    """An inclusive date range with UTC-aware boundary datetimes.

    Both datetimes must be timezone-aware (UTC). start must be strictly before end.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("DateRange datetimes must be timezone-aware (UTC)")
        if self.start >= self.end:
            raise ValueError(f"DateRange.start must be strictly before end: {self.start!r} >= {self.end!r}")
