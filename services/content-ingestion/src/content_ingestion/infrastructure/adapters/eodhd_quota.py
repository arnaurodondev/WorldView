"""Shared EODHD quota recording for content-ingestion adapters.

Why this module exists (blind-spot fix, 2026-07-01)
---------------------------------------------------
content-ingestion (S4) is the LARGEST EODHD consumer — the per-ticker news
sweep alone issues hundreds of requests/hour — yet it historically wrote NO
Valkey quota counters.  market-ingestion (S2) *does* increment the shared
``eodhd:v1:quota:*`` counters, and both services share the same EODHD account
key, so the account-wide monthly total reflected ONLY S2.  Dashboards and the
soft-limit alert therefore materially UNDERCOUNTED true usage, which is why the
June monthly exhaustion fired with no freshness alert (ingestion just silently
stopped once EODHD returned 402/403).

The fix routes every S4 EODHD request through :func:`record_eodhd_request` so it
rolls up into the SAME shared counters S2 uses (via the single shared
``EodhdQuotaService.record_usage`` implementation — no divergent key scheme).
It is deliberately best-effort: a Valkey failure logs a WARNING and returns,
never breaking ingestion.  When the shared counter crosses the 80% soft limit or
100% hard limit — a cross-service signal that now includes S4's own spend — it
emits a loud WARNING/ERROR plus a Prometheus safeguard metric so the next
exhaustion is caught before ingestion silently halts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from content_ingestion.infrastructure.metrics.prometheus import (
    record_eodhd_credits,
    record_eodhd_quota_alert,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.eodhd_quota.quota_service import EodhdQuotaService

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Service identity used for per-service attribution in the shared counter
# (``eodhd:v1:quota:{month}:content-ingestion:credits_used``).  Must stay stable
# so historical attribution is not fragmented across renames.
SERVICE_NAME = "content-ingestion"


async def record_eodhd_request(
    quota_service: EodhdQuotaService | None,
    *,
    endpoint: str,
    credit_cost: int,
    symbol: str | None = None,
) -> None:
    """Record a single S4 EODHD request into the shared quota counters.

    Best-effort by construction: any Valkey failure is swallowed inside
    :meth:`EodhdQuotaService.record_usage`, and this function additionally
    guards its own metric/logging so nothing here can raise into the fetch path.

    Args:
        quota_service: The shared :class:`EodhdQuotaService`, or ``None`` when
            Valkey is not configured (accounting silently degrades to a no-op).
        endpoint: EODHD endpoint identifier for the Prometheus label — e.g.
            ``"news"`` (general feed) or ``"ticker_news"`` (per-symbol feed).
        credit_cost: Credit cost of the request (news = 5 credits/request).
        symbol: Optional ticker for per-symbol attribution.
    """
    if quota_service is None:
        # No Valkey configured — accounting is unavailable.  Do not treat this
        # as an error; the request itself proceeds normally.
        return

    from messaging.eodhd_quota.quota_service import QuotaCheckResult

    # Local Prometheus counter always reflects intended spend, even if the
    # Valkey write below fails — so S4's own dashboard never under-reports.
    record_eodhd_credits(endpoint, credit_cost)

    result = await quota_service.record_usage(
        cost=credit_cost,
        service=SERVICE_NAME,
        symbol=symbol,
    )

    # ``None`` → the shared counter could not be written (Valkey blip); already
    # logged as a WARNING inside record_usage.  Nothing more to do.
    if result is None:
        return

    # Loud, actionable signals on threshold crossings.  These now include S4's
    # own spend in the shared total, so they fire on the *true* account usage.
    if result == QuotaCheckResult.HARD_LIMIT_EXCEEDED:
        record_eodhd_quota_alert("hard_limit")
        logger.error(
            "eodhd_quota_hard_limit_exceeded",
            endpoint=endpoint,
            symbol=symbol,
            service=SERVICE_NAME,
            message=(
                "Shared EODHD DAILY hard limit reached — ingestion will start "
                "failing (429/402) until the next UTC day. Raise eodhd_daily_quota "
                "only if the account's real dailyRateLimit is higher."
            ),
        )
    elif result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED:
        record_eodhd_quota_alert("soft_limit")
        logger.warning(
            "eodhd_quota_soft_limit_exceeded",
            endpoint=endpoint,
            symbol=symbol,
            service=SERVICE_NAME,
            message="Shared EODHD DAILY usage crossed 80% — approaching today's limit.",
        )


def record_eodhd_auth_or_quota_rejection(endpoint: str, status_code: int, *, symbol: str | None = None) -> None:
    """Emit a loud safeguard signal when EODHD rejects a request.

    EODHD returns 401 (bad/revoked key), 402/403 (quota exhausted), or 429
    (rate limit) once the account is out of credits.  Historically these
    surfaced only as generic adapter errors and ingestion halted silently.
    This records a dedicated safeguard metric + ERROR log so the condition is
    unmissable.

    Args:
        endpoint: EODHD endpoint identifier — ``"news"`` or ``"ticker_news"``.
        status_code: The rejecting HTTP status code.
        symbol: Optional ticker for context.
    """
    record_eodhd_quota_alert("auth_or_quota_rejected")
    logger.error(
        "eodhd_auth_or_quota_rejected",
        endpoint=endpoint,
        status_code=status_code,
        symbol=symbol,
        message="EODHD rejected a request (auth/quota) — key may be dead or the monthly quota exhausted.",
    )
