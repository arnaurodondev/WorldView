"""Time utilities — all datetimes are UTC."""

from __future__ import annotations

from datetime import UTC, datetime

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_BAR_DATE_FORMAT = "%Y-%m-%d"
_BAR_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure *dt* is timezone-aware and in UTC.

    Raises ``ValueError`` if *dt* is naive (no tzinfo).
    """
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed: {dt!r}")
    return dt.astimezone(UTC)


def to_iso8601(dt: datetime) -> str:
    """Format a datetime as ``YYYY-MM-DDTHH:MM:SS.ffffffZ``."""
    return ensure_utc(dt).strftime(_ISO_FORMAT)


def from_iso8601(s: str) -> datetime:
    """Parse an ISO-8601 string and return a UTC datetime."""
    # Handle both 'Z' suffix and '+00:00'
    s = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(s)
    return ensure_utc(dt)


def parse_bar_date(s: str) -> datetime:
    """Parse ``YYYY-MM-DD`` → UTC midnight datetime."""
    return datetime.strptime(s, _BAR_DATE_FORMAT).replace(tzinfo=UTC)


def parse_bar_datetime(s: str) -> datetime:
    """Parse ``YYYY-MM-DD HH:MM:SS`` → UTC datetime."""
    return datetime.strptime(s, _BAR_DATETIME_FORMAT).replace(tzinfo=UTC)
