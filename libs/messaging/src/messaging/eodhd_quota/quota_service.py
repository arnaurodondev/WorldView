"""EodhdQuotaService — shared EODHD credit quota enforcement via Valkey.

Design
------
All EODHD consumers (S2 market-ingestion, S4 content-ingestion) share Valkey
credit counters.  This prevents the per-process token bucket failure pattern
(BP-185) where each replica maintains independent state and collectively
exceeds the account quota.

Which limit actually blocks (INCIDENT 2026-07-03)
------------------------------------------------
EODHD's REAL rate limit is **per calendar day (UTC), not per month**.  Verified
against the authoritative ``GET /api/user`` endpoint, which returns
``dailyRateLimit=100000`` and ``apiRequests`` (used TODAY, resets daily).  The
reference docs corroborate this ("1,000 req/min or 100,000 calls/24h").

The original guard hard-blocked on the MONTHLY counter with a 100k cap.  Because
normal usage (ticker-news alone ≈75k credits/day) blows past 100k in ~1-1.5
days, the monthly counter would trip the hard block a few days into every month
and STAY blocked (the monthly key only resets on TTL expiry) — artificially
starving ingestion even though the account had full daily headroom.  This was a
misconfiguration, not a real limit.

The guard now enforces the **DAILY** hard cap (``daily_hard_limit`` / the
per-UTC-day counter) as the blocker.  The monthly counters are retained for
cross-service reporting/attribution ONLY and no longer block traffic.

Valkey key schema
-----------------
    eodhd:v1:quota:{YYYY-MM}:credits_used           — total monthly counter (reporting)
    eodhd:v1:quota:{YYYY-MM}:{service}:credits_used — per-service attribution
    eodhd:v1:quota:{YYYY-MM}:symbol:{sym}:credits_used — per-symbol attribution
    eodhd:v1:quota:day:{YYYY-MM-DD}:credits_used    — cumulative per-UTC-day counter (ENFORCED)

The monthly keys carry a 32-day TTL; the daily key carries a 2-day TTL
(auto-expiry cleans up previous days).  The daily counter is both the hard-cap
enforcement source AND what ``DailyBudgetTracker`` reads for true
cumulative-spend headroom (it must NOT be derived from instantaneous
token-bucket depletion, which is permanently near-empty by design — see BP
daily-budget mis-model).

TOCTOU note
-----------
The GET → INCRBY sequence has a small race window in which two replicas could
simultaneously read a value below the hard limit and both proceed to increment.
This race can cause a brief over-consumption of a few credits (≤ one request's
cost per replica pair).  For a 100,000-credit daily budget this is acceptable;
the alternative (Lua script or atomic compare-and-swap) adds significant
complexity with marginal benefit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient

logger = get_logger(__name__)

# 32 days in seconds — covers end-of-month + a small buffer before auto-expiry.
_MONTHLY_TTL_SECONDS: int = 32 * 86_400
# 2 days in seconds — covers the current UTC day + a small buffer before auto-expiry.
_DAILY_TTL_SECONDS: int = 2 * 86_400


def _current_month() -> str:
    """Return the current UTC month as 'YYYY-MM'."""
    from datetime import UTC

    return datetime.now(tz=UTC).strftime("%Y-%m")


def _current_day() -> str:
    """Return the current UTC day as 'YYYY-MM-DD'."""
    from datetime import UTC

    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


class QuotaCheckResult(StrEnum):
    """Result of an EodhdQuotaService.try_consume() call."""

    OK = "ok"
    # 80 % threshold: log + alert, but do NOT block the call.
    SOFT_LIMIT_EXCEEDED = "soft_limit_exceeded"
    # 100 % threshold: BLOCK the EODHD call — quota exhausted for this month.
    HARD_LIMIT_EXCEEDED = "hard_limit_exceeded"


@dataclass(frozen=True)
class QuotaStatus:
    """Point-in-time snapshot of monthly quota usage."""

    month: str
    credits_used: int
    soft_limit: int
    hard_limit: int
    percent_used: float


class EodhdQuotaService:
    """Shared EODHD credit quota counter backed by Valkey.

    The **daily** counter is the real enforcement source (EODHD's limit is
    per-UTC-day — see module docstring).  The monthly counters are retained for
    cross-service reporting/attribution only and never block traffic.

    Args:
        valkey: An initialised :class:`~messaging.valkey.client.ValkeyClient`.
        hard_limit: Monthly credit counter cap — REPORTING ONLY, no longer
            blocks (default 100,000). Kept for the ``get_status`` snapshot and
            backward-compatible construction.
        soft_limit_ratio: Fraction of a limit that triggers a soft-limit warning
            (default 0.80 → 80% of the daily cap).
        daily_hard_limit: EODHD's REAL per-UTC-day credit ceiling — the value
            that actually blocks (default 100,000 = the account's
            ``dailyRateLimit``).
    """

    HARD_LIMIT: int = 100_000
    DAILY_HARD_LIMIT: int = 100_000
    SOFT_LIMIT_RATIO: float = 0.80

    def __init__(
        self,
        valkey: ValkeyClient,
        hard_limit: int = 100_000,
        soft_limit_ratio: float = 0.80,
        daily_hard_limit: int = 100_000,
    ) -> None:
        self._valkey = valkey
        # Monthly ceiling — retained for reporting/attribution only (no block).
        self._hard_limit = hard_limit
        self._soft_limit = int(hard_limit * soft_limit_ratio)
        self._soft_limit_ratio = soft_limit_ratio
        # Daily ceiling — the REAL EODHD limit that blocks (per UTC day).
        self._daily_hard_limit = daily_hard_limit
        self._daily_soft_limit = int(daily_hard_limit * soft_limit_ratio)

    # ── Public API ────────────────────────────────────────────────────────────

    async def try_consume(
        self,
        cost: int,
        service: str,
        symbol: str | None = None,
        month: str | None = None,
        day: str | None = None,
    ) -> QuotaCheckResult:
        """Attempt to consume *cost* credits against the DAILY EODHD quota.

        Enforcement is on the per-UTC-day counter (EODHD's real limit is
        per-day, not per-month — see module docstring).  The monthly counters
        are still incremented for cross-service reporting/attribution but do NOT
        block.

        Args:
            cost:    Number of EODHD credits this request will consume.
            service: Caller identity for attribution (e.g. ``"market-ingestion"``).
            symbol:  Optional ticker symbol for per-symbol attribution.
            month:   Month key as ``"YYYY-MM"`` (defaults to current UTC month).
            day:     Day key as ``"YYYY-MM-DD"`` (defaults to current UTC day).

        Returns:
            :class:`QuotaCheckResult` — OK, SOFT_LIMIT_EXCEEDED, or
            HARD_LIMIT_EXCEEDED.  Only HARD_LIMIT_EXCEEDED means the call should
            be blocked; soft-limit callers may still proceed with a warning.
        """
        if month is None:
            month = _current_month()
        if day is None:
            day = _current_day()

        total_key = f"eodhd:v1:quota:{month}:credits_used"
        service_key = f"eodhd:v1:quota:{month}:{service}:credits_used"
        day_key = f"eodhd:v1:quota:day:{day}:credits_used"

        # Pre-check the DAILY counter (the REAL EODHD cap). If we are already at
        # or above the daily hard limit, block immediately without consuming any
        # additional credits — this is what protects us from EODHD overage.
        day_raw = await self._valkey.get(day_key)
        day_current = int(day_raw) if day_raw else 0
        if day_current >= self._daily_hard_limit:
            return QuotaCheckResult.HARD_LIMIT_EXCEEDED

        # Cumulative per-UTC-day counter — the enforced hard-cap source AND the
        # true daily-spend source consumed by DailyBudgetTracker for headroom.
        new_day_total = await self._valkey.incr(day_key, cost)
        await self._valkey.expire(day_key, _DAILY_TTL_SECONDS)

        # Monthly + per-service counters: REPORTING/ATTRIBUTION ONLY (no block).
        # On first write of the month, new_total == cost.
        await self._valkey.incr(total_key, cost)
        # Refresh TTL on every write (idempotent; 32-day rolling window).
        await self._valkey.expire(total_key, _MONTHLY_TTL_SECONDS)

        await self._valkey.incr(service_key, cost)
        await self._valkey.expire(service_key, _MONTHLY_TTL_SECONDS)

        # Optional per-symbol attribution.
        if symbol:
            sym_key = f"eodhd:v1:quota:{month}:symbol:{symbol}:credits_used"
            await self._valkey.incr(sym_key, cost)
            await self._valkey.expire(sym_key, _MONTHLY_TTL_SECONDS)

        # Post-increment status is driven by the DAILY counter (the real cap).
        if new_day_total > self._daily_hard_limit:
            return QuotaCheckResult.HARD_LIMIT_EXCEEDED
        if new_day_total >= self._daily_soft_limit:
            return QuotaCheckResult.SOFT_LIMIT_EXCEEDED
        return QuotaCheckResult.OK

    async def record_usage(
        self,
        cost: int,
        service: str,
        symbol: str | None = None,
        month: str | None = None,
    ) -> QuotaCheckResult | None:
        """Best-effort variant of :meth:`try_consume` for pure *attribution*.

        This is the entry point for consumers (e.g. S4 content-ingestion) that
        want their EODHD spend to roll up into the SAME shared monthly/daily
        counters as S2 market-ingestion, but that must NEVER let a Valkey blip
        break ingestion.  Unlike :meth:`try_consume`, any exception raised by
        the underlying Valkey calls is swallowed and logged — the caller gets
        ``None`` and proceeds with the real API request regardless.

        Why a shared method rather than duplicating the increment in each
        service: the Valkey key scheme + increment semantics live in exactly
        one place (:meth:`try_consume`).  Both services call into it so the
        cross-service monthly total (``eodhd:v1:quota:{month}:credits_used``)
        stays a single true rollup and cannot silently under-count.

        Args:
            cost:    EODHD credits this request consumed (news = 5/request).
            service: Caller identity for attribution (e.g. ``"content-ingestion"``).
            symbol:  Optional ticker symbol for per-symbol attribution.
            month:   Month key ``"YYYY-MM"`` (defaults to current UTC month).

        Returns:
            The :class:`QuotaCheckResult` from the increment (so the caller can
            raise a loud alert on SOFT/HARD limit crossings), or ``None`` when
            the counter could not be written (Valkey unavailable).
        """
        try:
            return await self.try_consume(cost=cost, service=service, symbol=symbol, month=month)
        except Exception as exc:
            # Best-effort: quota accounting must never break ingestion.  A
            # WARNING (not ERROR) because the request itself still succeeds —
            # only the attribution counter is temporarily missed.
            logger.warning(
                "eodhd_quota_record_failed",
                service=service,
                symbol=symbol,
                cost=cost,
                error=str(exc),
            )
            return None

    async def get_status(self, month: str | None = None) -> QuotaStatus:
        """Return a point-in-time snapshot of monthly quota usage.

        Args:
            month: Month key as ``"YYYY-MM"`` (defaults to current UTC month).

        Returns:
            :class:`QuotaStatus` with current usage, limits, and percent used.
        """
        if month is None:
            month = _current_month()

        total_key = f"eodhd:v1:quota:{month}:credits_used"
        raw = await self._valkey.get(total_key)
        used = int(raw) if raw else 0
        return QuotaStatus(
            month=month,
            credits_used=used,
            soft_limit=self._soft_limit,
            hard_limit=self._hard_limit,
            percent_used=round(used / self._hard_limit * 100, 2) if self._hard_limit else 0.0,
        )

    async def get_daily_credits_used(self, day: str | None = None) -> int:
        """Return the cumulative EODHD credits consumed on *day* (UTC).

        This is the real cumulative daily spend, sourced from the per-day Valkey
        counter that :meth:`try_consume` maintains.  ``DailyBudgetTracker`` uses
        it to compute honest headroom instead of conflating it with the
        instantaneous (near-empty by design) token bucket.

        Args:
            day: Day key as ``"YYYY-MM-DD"`` (defaults to current UTC day).

        Returns:
            Integer credit count (0 if nothing recorded yet today).
        """
        if day is None:
            day = _current_day()
        key = f"eodhd:v1:quota:day:{day}:credits_used"
        raw = await self._valkey.get(key)
        return int(raw) if raw else 0

    async def get_by_service(self, service: str, month: str | None = None) -> int:
        """Return the credits consumed by *service* this month.

        Args:
            service: Service identifier (e.g. ``"market-ingestion"``).
            month:   Month key as ``"YYYY-MM"`` (defaults to current UTC month).

        Returns:
            Integer credit count (0 if no usage recorded yet).
        """
        if month is None:
            month = _current_month()
        key = f"eodhd:v1:quota:{month}:{service}:credits_used"
        raw = await self._valkey.get(key)
        return int(raw) if raw else 0

    async def get_by_symbol(self, symbol: str, month: str | None = None) -> int:
        """Return the credits consumed for *symbol* this month.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).
            month:  Month key as ``"YYYY-MM"`` (defaults to current UTC month).

        Returns:
            Integer credit count (0 if no usage recorded yet).
        """
        if month is None:
            month = _current_month()
        key = f"eodhd:v1:quota:{month}:symbol:{symbol}:credits_used"
        raw = await self._valkey.get(key)
        return int(raw) if raw else 0
