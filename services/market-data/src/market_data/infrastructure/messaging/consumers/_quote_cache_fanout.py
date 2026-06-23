"""Shared post-commit cache fan-out for fresh quotes.

Extracted from ``QuotesConsumer.process_message`` (Option B write-through) so
both the quotes consumer and the OHLCV 1m write-through schedule the exact
same cache side effects after a quote upsert:

1. ``QuoteCache.invalidate(instrument_id)`` — drop the stale per-quote cache
   entry so the next API read re-resolves from the DB.
2. ``PriceSnapshotCache.set(instrument_id, snapshot)`` — warm the snapshot
   cache with a PriceSnapshot resolved from the fresh quote, so the first API
   read is served O(1) from Valkey instead of a full DB resolution.

Both effects are scheduled via ``uow.schedule_post_commit`` (M-005): running
them before the transaction commits risks a concurrent read re-caching stale
data between the invalidation and the commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data.application.ports.cache import PriceSnapshotCachePort, QuoteCachePort
    from market_data.application.ports.uow import UnitOfWork
    from market_data.domain.entities import Quote


def schedule_quote_cache_fanout(
    uow: UnitOfWork,
    *,
    instrument_id: str,
    symbol: str,
    exchange: str,
    quote: Quote,
    quote_cache: QuoteCachePort | None,
    price_snapshot_cache: PriceSnapshotCachePort | None,
) -> None:
    """Schedule QuoteCache invalidation + PriceSnapshotCache warm post-commit.

    Either cache may be ``None`` (e.g. Valkey not configured); each effect is
    skipped independently.  The caller is responsible for gating on backfill
    (historical replays must never touch the live caches — BUG-009 / BP-492).
    """
    # Invalidate the per-quote cache so reads see the fresh DB row.
    if quote_cache is not None:
        uow.schedule_post_commit(quote_cache.invalidate(instrument_id))

    # Warm the PriceSnapshot cache from the fresh quote.  We pass
    # ohlcv_bars=[] because at the consumer stage the quote is the only
    # source in hand — the full fallback chain (including OHLCV) is
    # exercised in the API router on cache miss.
    if price_snapshot_cache is not None:
        from market_data.domain.price_snapshot import PriceSnapshotResolver

        resolved_at = datetime.now(tz=UTC)
        resolver = PriceSnapshotResolver()
        snapshot = resolver.resolve(
            instrument_id=instrument_id,
            symbol=symbol,
            exchange=exchange,
            quote=quote,
            ohlcv_bars=[],  # OHLCV bars not available at consumer stage (see above)
            resolved_at=resolved_at,
        )
        uow.schedule_post_commit(price_snapshot_cache.set(instrument_id, snapshot))
