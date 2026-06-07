"""Provider-agnostic read-through market-data cache (PLAN-0107 A-2).

Behavioural contract (see PLAN-0107 sections A.1 / A.2 for the full design):

* Key format: ``market_data:{dataset_type}:{symbol_lower}:{period_key}``.
  The provider/endpoint is **deliberately not** part of the key so a routing
  swap (e.g. EODHD -> Polygon for OHLCV) reuses the same cached payload.
* Backend: :class:`messaging.valkey.ValkeyClient` (``get`` / ``set(ex=)`` /
  ``set_nx(ex=)``).
* Serialization: ``json.dumps(payload, sort_keys=True, separators=(",", ":"))``.
* **Fail-open semantics**: a cache miss, Valkey timeout, deserialization
  error, or any backend exception must fall through to ``fetcher()``. The
  request never fails because of the cache.
* Stampede mitigation: a short-lived ``:inflight`` sentinel set via
  ``set_nx`` (TTL 10 s). On collision we sleep a small jitter (5-25 ms) and
  retry the GET exactly once; if it is still a miss we fall through to the
  fetcher (no in-process single-flight in v1).
* ``provider_label`` is accepted but not consumed in this wave -- metric
  wiring lands in PLAN-0107 Wave A-4.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeAlias

import structlog

from market_ingestion.infrastructure.cache.cache_policy import (
    CACHE_TTL_SECONDS,
    DatasetType,
)

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# The cache is payload-shape agnostic -- use cases pass whatever JSON-serialisable
# envelope their adapter returns. Aliased for readability at call sites.
ResultEnvelope: TypeAlias = Any

#: Sentinel suffix appended to the data key to mark a fetch as in-flight.
_INFLIGHT_SUFFIX = ":inflight"
#: TTL (seconds) for the in-flight sentinel -- must be longer than any plausible
#: provider call yet short enough that a crashed fetcher does not block traffic.
_INFLIGHT_TTL_SECONDS = 10
#: Jittered retry window when a sibling fetcher is already in-flight.
_INFLIGHT_RETRY_MIN_MS = 5
_INFLIGHT_RETRY_MAX_MS = 25


def _build_key(dataset_type: DatasetType, symbol: str, period_key: str) -> str:
    """Return the canonical cache key for the given coordinates.

    Lower-cases the symbol -- adapters already normalise to upper case
    upstream, so this is a belt-and-braces guarantee that ``AAPL`` and ``aapl``
    collide on the same cache entry.
    """
    return f"market_data:{dataset_type.value}:{symbol.lower()}:{period_key}"


class MarketDataCache:
    """Read-through cache for market-data provider responses.

    Construction is intentionally cheap -- the class holds no state besides the
    injected :class:`ValkeyClient`. Use cases get one instance via the DI
    container and share it across requests.
    """

    def __init__(self, valkey: ValkeyClient) -> None:
        self._valkey = valkey

    async def get_or_fetch(
        self,
        dataset_type: DatasetType,
        symbol: str,
        period_key: str,
        fetcher: Callable[[], Awaitable[ResultEnvelope]],
        *,
        provider_label: str,
    ) -> ResultEnvelope:
        """Return cached payload for ``(dataset_type, symbol, period_key)`` or
        call ``fetcher`` on miss/error.

        Raises:
            ValueError: ``dataset_type`` is not a :class:`DatasetType` member
                (i.e. an explicitly forbidden dataset like ``quote_realtime``
                slipped through).
        """
        # Defensive isinstance -- StrEnum already enforces membership at the
        # type level, but call sites may pass a raw str through dynamic
        # dispatch.
        if not isinstance(dataset_type, DatasetType):
            raise ValueError(f"dataset_type must be a DatasetType member; got {type(dataset_type).__name__}")

        key = _build_key(dataset_type, symbol, period_key)
        # ``provider_label`` is accepted for forward-compat with Wave A-4
        # metrics; silence the "unused argument" lint without altering the
        # signature.
        _ = provider_label

        # -- 1. Try cache. --------------------------------------------------
        cached = await self._safe_get(key)
        if cached is not None:
            return cached

        # -- 2. Stampede mitigation. ----------------------------------------
        # Try to claim the inflight sentinel. If another worker holds it we
        # wait a jittered slice and retry the GET exactly once before falling
        # through to the fetcher ourselves.
        inflight_key = key + _INFLIGHT_SUFFIX
        try:
            claimed = await self._valkey.set_nx(inflight_key, "1", ex=_INFLIGHT_TTL_SECONDS)
        except Exception as exc:  # -- fail-open
            logger.warning(
                "market_data_cache_inflight_set_failed",
                key=key,
                error=str(exc),
            )
            claimed = True  # Pretend we own it -- proceed straight to fetcher.

        if not claimed:
            # Sibling is already fetching -- back off and re-check the cache.
            delay_seconds = (
                random.uniform(_INFLIGHT_RETRY_MIN_MS, _INFLIGHT_RETRY_MAX_MS)  # noqa: S311 -- non-crypto jitter
                / 1000.0
            )
            await asyncio.sleep(delay_seconds)
            retried = await self._safe_get(key)
            if retried is not None:
                return retried
            # Still a miss -> fall through and fetch ourselves. Worst case both
            # workers hit the provider; full single-flight is deferred to v2
            # per PLAN-0107 section A.5.

        # -- 3. Provider fetch. ---------------------------------------------
        payload = await fetcher()

        # -- 4. Best-effort fill. -------------------------------------------
        ttl = CACHE_TTL_SECONDS[dataset_type]
        await self._safe_set(key, payload, ttl)

        return payload

    # -- Internal helpers ----------------------------------------------------

    async def _safe_get(self, key: str) -> ResultEnvelope | None:
        """Return deserialised cached value, or ``None`` on any error.

        Errors are logged at WARNING and swallowed -- see fail-open contract.
        """
        try:
            raw = await self._valkey.get(key)
        except Exception as exc:  # -- fail-open
            logger.warning("market_data_cache_get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as exc:
            # Corrupt payload -- log and treat as miss. Wave A-4 will
            # increment ``s2_mi_provider_cache_errors_total{kind="deserialize_error"}``.
            logger.warning(
                "market_data_cache_deserialize_failed",
                key=key,
                error=str(exc),
            )
            return None

    async def _safe_set(self, key: str, payload: ResultEnvelope, ttl: int) -> None:
        """Serialise and store ``payload`` at ``key`` with ``ttl`` seconds.

        Errors are logged at WARNING and swallowed -- see fail-open contract.
        """
        try:
            serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            logger.warning(
                "market_data_cache_serialize_failed",
                key=key,
                error=str(exc),
            )
            return
        try:
            await self._valkey.set(key, serialised, ex=ttl)
        except Exception as exc:  # -- fail-open
            logger.warning("market_data_cache_set_failed", key=key, error=str(exc))
