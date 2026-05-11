"""Market calendar — NYSE/NASDAQ trading day and hours awareness.

This module is infrastructure-free (no I/O). All calendar logic uses
the embedded holiday list and UTC time comparisons.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

# US equity market hours in UTC
_MARKET_OPEN_UTC = (13, 30)  # 09:30 ET = 13:30 UTC (EDT)
_MARKET_CLOSE_UTC = (20, 0)  # 16:00 ET = 20:00 UTC (EDT)
_POST_CLOSE_START_UTC = (20, 0)
_POST_CLOSE_END_UTC = (21, 0)  # 1-hour post-close window

# NYSE holidays 2026-2028 (date objects).
# Black Friday (day after Thanksgiving) has an early close — treated as a trading day.
_NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2026
        date(2026, 1, 1),  # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 7, 3),  # Independence Day (observed)
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
        # 2027
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 4, 26),  # Good Friday
        date(2027, 5, 31),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
        # 2028
        date(2028, 1, 17),
        date(2028, 2, 21),
        date(2028, 4, 14),
        date(2028, 5, 29),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
    },
)


class MarketCalendar:
    """NYSE/NASDAQ market calendar for scheduling decisions.

    All methods accept and return UTC-aware datetimes or plain dates.
    No I/O — safe to call from domain layer.
    """

    def is_trading_day(self, d: date) -> bool:
        """Return True if d is a NYSE/NASDAQ trading day (not weekend or holiday)."""
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return d not in _NYSE_HOLIDAYS

    def is_market_open(self, dt: datetime) -> bool:
        """Return True if dt (UTC-aware) falls within NYSE/NASDAQ market hours (13:30-20:00 UTC)."""
        utc = dt.astimezone(UTC)
        if not self.is_trading_day(utc.date()):
            return False
        minutes = utc.hour * 60 + utc.minute
        open_min = _MARKET_OPEN_UTC[0] * 60 + _MARKET_OPEN_UTC[1]
        close_min = _MARKET_CLOSE_UTC[0] * 60 + _MARKET_CLOSE_UTC[1]
        return open_min <= minutes < close_min

    def is_post_close(self, dt: datetime) -> bool:
        """Return True if dt falls in the post-close window (20:00-21:00 UTC) on a trading day."""
        utc = dt.astimezone(UTC)
        if not self.is_trading_day(utc.date()):
            return False
        minutes = utc.hour * 60 + utc.minute
        open_min = _POST_CLOSE_START_UTC[0] * 60 + _POST_CLOSE_START_UTC[1]
        close_min = _POST_CLOSE_END_UTC[0] * 60 + _POST_CLOSE_END_UTC[1]
        return open_min <= minutes < close_min

    def next_trading_day(self, d: date) -> date:
        """Return the next calendar trading day after d."""
        candidate = d + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate
