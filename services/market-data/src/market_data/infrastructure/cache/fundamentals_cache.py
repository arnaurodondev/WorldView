"""Valkey read-cache for the fundamentals read use-cases.

chat-enhancement-roadmap Area 1 #3.

WHY: the chat hot-path hammers a small set of tickers (AAPL/AMZN/NVDA) with the
SAME fundamentals reads across many questions. Fundamentals only change
quarterly, so these reads are highly repetitive yet each one currently costs a
DB round-trip (four section SELECTs) and holds a read-replica connection. A
short-TTL Valkey cache in front of the read use-cases collapses the repeats to a
single serialised-JSON GET, cutting DB round-trips and connection-pool pressure
with safe bounded staleness (worst case one TTL window behind a new quarter).

DESIGN — thin decorator, unchanged miss path:
    ``CachedFundamentalsHistoryUseCase`` and ``CachedQueryFundamentalsUseCase``
    wrap the real use-cases and mirror their ``execute()`` signatures exactly.
    On a hit they deserialise and return the cached dict; on a miss they call
    the wrapped use-case (so the query path is byte-for-byte unchanged) and
    store the serialised result. The wrapped use-cases already return plain,
    JSON-serialisable dicts, so caching is a straight serialise/deserialise.

FAIL-OPEN: every Valkey operation is wrapped so that a cache outage NEVER fails
the request — on any error we log, count, and fall through to the DB. The cache
is a pure latency/load optimisation, never a correctness dependency.

INVALIDATION: none in phase 1 — bounded TTL staleness is acceptable because
fundamentals are quarterly. Follow-up (noted in the roadmap): publish an
invalidation on the fundamentals-ingest path so a freshly-ingested quarter is
visible immediately rather than after ≤ TTL.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.application.use_cases.get_fundamentals_history import (
        GetFundamentalsHistoryUseCase,
    )
    from market_data.application.use_cases.query_fundamentals_metrics import (
        QueryFundamentalsUseCase,
    )
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)

# Versioned key namespace. Bump ``v1`` if the serialised dict shape ever changes
# in a backward-incompatible way so stale entries can't be mis-deserialised.
_KEY_PREFIX = "md:v1:fund"
_DEFAULT_TTL = 21_600  # 6 hours — mirrors Settings.fundamentals_cache_ttl_seconds


def _metrics_hash(metrics: list[str]) -> str:
    """Return a short, order-independent hash of the requested metric set.

    Order-independent so ``["revenue","eps"]`` and ``["eps","revenue"]`` share a
    cache slot (they return the same data). Truncated to 12 hex chars — ample
    collision resistance for a per-instrument keyspace, keeps keys compact.
    """
    joined = ",".join(sorted(metrics))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - non-crypto cache key


def _emit(use_case: str, outcome: str) -> None:
    """Increment the cache hit/miss/error counter, tolerating a metrics-less env.

    Import is local + guarded so unit tests (and any context where the
    prometheus registry is unavailable) never fail on a metrics side-effect.
    """
    try:
        from market_data.infrastructure.metrics.prometheus import (
            s3_fundamentals_cache_events_total,
        )

        s3_fundamentals_cache_events_total.labels(use_case=use_case, outcome=outcome).inc()
    except Exception:  # noqa: S110 - metrics side-effect must never break the read path  # pragma: no cover
        pass


class FundamentalsCache:
    """Cache-aside helper over :class:`ValkeyClient` for fundamentals reads.

    Stores use-case result dicts as JSON. All operations fail-open: a Valkey
    outage degrades transparently to the DB path (get → miss, set → no-op).
    """

    _KEY_PREFIX = _KEY_PREFIX

    def __init__(self, client: ValkeyClient, *, ttl: int = _DEFAULT_TTL) -> None:
        self._client = client
        self._ttl = ttl

    # ── Key construction ─────────────────────────────────────────────────────
    def key(
        self,
        kind: str,
        instrument_id: str | UUID,
        *,
        periods: int,
        period_type: str,
        metrics: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        extra: str | None = None,
    ) -> str:
        """Build the canonical cache key.

        Keyed by ``(instrument_id, periods, period_type, sorted-metrics-hash,
        from_date, to_date)`` per the roadmap spec. ``metrics``/``from_date``/
        ``to_date`` are absent for the history path (fixed projection, no date
        window) and are rendered as ``-`` placeholders so the two paths share a
        stable, collision-free namespace.
        """
        m = _metrics_hash(metrics) if metrics else "-"
        fd = from_date or "-"
        td = to_date or "-"
        # period_type is normalised to lower-case so "quarterly" and "QUARTERLY"
        # (both legal API inputs producing identical data) share one slot.
        pt = (period_type or "quarterly").lower()
        base = f"{self._KEY_PREFIX}:{kind}:{instrument_id}:{periods}:{pt}:{m}:{fd}:{td}"
        return f"{base}:{extra}" if extra else base

    # ── Cache-aside primitives (fail-open) ───────────────────────────────────
    async def get(self, key: str, *, use_case: str) -> dict[str, Any] | None:
        """Return the cached dict, or ``None`` on miss / any Valkey error."""
        try:
            raw = await self._client.get(key)
        except Exception:  # fail-open: cache down → treat as miss, read from DB
            logger.warning("fundamentals_cache_unavailable_get", key=key)
            _emit(use_case, "error")
            return None
        if raw is None:
            _emit(use_case, "miss")
            return None
        try:
            data = json.loads(raw) if isinstance(raw, bytes | str) else raw
        except (ValueError, TypeError):
            # Corrupt/undeserialisable entry → treat as a miss and let the DB
            # path overwrite it. Never propagate to the caller.
            logger.warning("fundamentals_cache_corrupt_entry", key=key)
            _emit(use_case, "error")
            return None
        _emit(use_case, "hit")
        return data if isinstance(data, dict) else None

    async def set(self, key: str, value: dict[str, Any]) -> None:
        """Store the dict as JSON with the configured TTL; no-op on any error."""
        try:
            # default=str serialises stray date/Decimal values (e.g. the
            # ``as_of`` date in current_snapshot) to ISO strings; the API schema
            # layer re-parses them cleanly (pydantic coerces str → date).
            payload = json.dumps(value, default=str)
            await self._client.set(key, payload, ttl=self._ttl)
        except Exception:  # fail-open: a failed write must not fail the request
            logger.warning("fundamentals_cache_unavailable_set", key=key)


class CachedFundamentalsHistoryUseCase:
    """Cache-aside wrapper mirroring :class:`GetFundamentalsHistoryUseCase`.

    Drop-in for the real use-case: same ``execute()`` signature, same return
    shape. On a miss it delegates unchanged to the wrapped use-case.
    """

    _USE_CASE = "history"

    def __init__(self, inner: GetFundamentalsHistoryUseCase, cache: FundamentalsCache) -> None:
        self._inner = inner
        self._cache = cache

    async def execute(
        self,
        instrument_id: UUID,
        periods: int = 8,
        *,
        requested_quarter: str | None = None,
        period_type: str = "quarterly",
    ) -> dict:
        # NOTE: ``requested_quarter`` intentionally omitted from the key — it does
        # not change the returned data (it only drives an observability warning),
        # so keying on it would fragment the cache for identical results. The
        # only visible effect is that the ``fundamentals_quarterly_missing`` log
        # fires on the first (miss) call, not on subsequent cache hits.
        key = self._cache.key(
            self._USE_CASE,
            instrument_id,
            periods=periods,
            period_type=period_type,
        )
        cached = await self._cache.get(key, use_case=self._USE_CASE)
        if cached is not None:
            return cached
        data = await self._inner.execute(
            instrument_id,
            periods,
            requested_quarter=requested_quarter,
            period_type=period_type,
        )
        await self._cache.set(key, data)
        return data


class CachedQueryFundamentalsUseCase:
    """Cache-aside wrapper mirroring :class:`QueryFundamentalsUseCase`."""

    _USE_CASE = "query"

    def __init__(self, inner: QueryFundamentalsUseCase, cache: FundamentalsCache) -> None:
        self._inner = inner
        self._cache = cache

    async def execute(
        self,
        instrument_id: UUID,
        metrics: list[str],
        *,
        periods: int = 8,
        period_type: str = "quarterly",
        include_snapshot: bool = True,
    ) -> dict[str, Any]:
        key = self._cache.key(
            self._USE_CASE,
            instrument_id,
            periods=periods,
            period_type=period_type,
            metrics=metrics,
            # include_snapshot changes the response shape, so it must partition
            # the keyspace — folded in via the ``extra`` discriminator.
            extra=f"snap={int(include_snapshot)}",
        )
        cached = await self._cache.get(key, use_case=self._USE_CASE)
        if cached is not None:
            return cached
        data = await self._inner.execute(
            instrument_id,
            metrics,
            periods=periods,
            period_type=period_type,
            include_snapshot=include_snapshot,
        )
        await self._cache.set(key, data)
        return data
