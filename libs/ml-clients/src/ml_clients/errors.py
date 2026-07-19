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

__all__ = [
    "FatalError",
    "ProviderBillingError",
    "RateLimitError",
    "RetryableError",
    "is_billing_status",
    "is_transient_status",
    "parse_retry_after",
]

# ── HTTP status classification (2026-07-18 spend-cap self-heal) ────────────────
#
# Root cause of the 402/spend-cap incident: adapters mapped EVERY non-429 4xx to
# ``FatalError`` (terminal). When the DeepInfra spend cap was hit, the provider
# returned HTTP 402 ``Payment Required`` — a purely BILLING refusal that clears
# the instant the operator raises the cap — yet it was treated as a permanent
# bad-request. Result: 693 article extractions silently empty-committed and 2,383
# embeddings were abandoned after their retry budget, both indefinitely lost.
#
# The fix splits 4xx into three buckets:
#   * BILLING/auth refusals (401/402/403) → :class:`ProviderBillingError`
#     (a ``RetryableError``). These clear only when the operator acts, so callers
#     that keep a bounded retry budget MUST NOT consume it here — otherwise a
#     multi-hour cap-down abandons all in-flight work. See EmbeddingRetryWorker.
#   * Other transient statuses (408/409/425/429) + all 5xx → bounded RetryableError.
#   * Everything else (genuine bad input: 400/404/413/422/…) → FatalError (drop).

#: Billing / auth refusals — retryable, but self-heal only when the operator acts.
_BILLING_HTTP_STATUSES = frozenset({401, 402, 403})

#: Other transient 4xx worth a bounded retry (timeout/conflict/too-early/rate-limit).
_TRANSIENT_4XX_HTTP_STATUSES = frozenset({408, 409, 425, 429})


def is_billing_status(status_code: int) -> bool:
    """True for a spend-cap / auth refusal (HTTP 401/402/403).

    These are retryable but distinct from generic transient errors: they clear
    only when the operator raises the spend cap or restores the key, so a bounded
    retry budget must not be spent on them (they would exhaust it and dead-end).
    """
    return status_code in _BILLING_HTTP_STATUSES


def is_transient_status(status_code: int) -> bool:
    """True for a generic transient status worth a bounded retry (5xx or 408/409/425/429).

    Excludes the billing statuses (see :func:`is_billing_status`) which callers
    should classify first so they can apply the no-budget-consumption policy.
    """
    return status_code >= 500 or status_code in _TRANSIENT_4XX_HTTP_STATUSES


class ProviderBillingError(RetryableError):
    """Spend-cap / billing / auth refusal from an upstream ML provider (HTTP 401/402/403).

    A :class:`RetryableError` subclass, so every existing ``except RetryableError``
    retry loop — Kafka consumer redelivery, the embedding retry worker — already
    treats it as transient (no new call sites required to stop the silent data
    loss). What sets it apart from a generic transient error is *when* it clears:
    only when the operator raises the DeepInfra spend cap or restores the API key.

    Consequently, callers that enforce a bounded retry budget (e.g.
    ``EmbeddingRetryWorker``'s max-5-attempts-then-abandon) MUST NOT count a
    ``ProviderBillingError`` against that budget — otherwise a cap-down lasting
    longer than the backoff schedule (~2 h) abandons all queued work permanently
    and it never self-heals when the cap is finally raised. Instead they should
    back off and re-attempt indefinitely until the cap clears.
    """


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
