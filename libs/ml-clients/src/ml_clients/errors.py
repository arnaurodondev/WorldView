"""Error types for ml-clients — re-exported from messaging.

In addition to the base ``FatalError`` / ``RetryableError`` re-exports, this
module defines :class:`RateLimitError` (LIB-005 / TASK-W4-03).

Hierarchy
---------
``RateLimitError`` extends ``messaging.kafka.consumer.errors.RateLimitedError``
which itself extends ``RetryableError``. Consequence:

  - ``except RetryableError:`` now catches HTTP 429s — consumers can transparently
    back-off and retry instead of crashing.
  - ``except RateLimitError:`` is also valid for callers that want to react to
    rate-limiting specifically (e.g. honour the ``Retry-After`` header).

The class carries the parsed ``Retry-After`` value (in seconds) when the
upstream provider supplies it. ``None`` means "no hint, use default back-off".
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from messaging.kafka.consumer.errors import FatalError, RateLimitedError, RetryableError

__all__ = ["FatalError", "RateLimitError", "RetryableError", "parse_retry_after"]


def parse_retry_after(headers: Mapping[str, str] | None) -> int | None:
    """Parse the HTTP ``Retry-After`` header into seconds.

    Per RFC 9110 §10.2.3, ``Retry-After`` may be either:
      - a non-negative integer number of seconds (e.g. ``Retry-After: 5``), or
      - an HTTP-date (e.g. ``Retry-After: Fri, 31 Dec 1999 23:59:59 GMT``).

    Returns
    -------
    int | None
        Seconds to wait. ``None`` when the header is absent, empty, or malformed
        so callers can transparently fall back to their default back-off.
    """
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    # Integer-seconds form
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return None
    # HTTP-date form — compute delta from "now" in UTC.
    try:
        target = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    # parsedate_to_datetime may return naive datetimes; treat those as UTC.
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    delta = (target - datetime.now(tz=UTC)).total_seconds()
    if delta <= 0:
        return 0
    return int(delta)


class RateLimitError(RateLimitedError):
    """HTTP 429 (or equivalent) from an upstream ML provider.

    Inherits from ``messaging.kafka.consumer.errors.RateLimitedError`` so the
    full chain is ``Exception → ConsumerError → RetryableError → RateLimitedError
    → RateLimitError``. This means existing ``except RetryableError`` retry loops
    in Kafka consumers automatically pick up 429s (LIB-005 fix).

    Attributes
    ----------
    retry_after:
        Seconds the upstream provider asked us to wait before retrying, parsed
        from the ``Retry-After`` response header when present. ``None`` if the
        header was absent or could not be parsed (callers should fall back to
        their default back-off schedule).
    """

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
