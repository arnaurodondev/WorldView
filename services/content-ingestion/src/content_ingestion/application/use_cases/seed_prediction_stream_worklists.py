"""Seed the deeper-stream (CLOB / trades / OI) work-lists from live markets.

PLAN-0056 live-QA (BUG 2) — work-list seeder
============================================

The three deeper Polymarket-stream adapters read their *work-list* from the
``sources`` config of their own row:

- ``polymarket_clob``       → ``config["markets"]`` = ``[{condition_id, token_ids}]``
- ``polymarket_data_trades``→ ``config["markets"]`` = ``[{condition_id, token_ids}]``
  (the trades adapter uses only the ``condition_id`` of each item)
- ``polymarket_data_oi``    → ``config["condition_ids"]`` = ``[condition_id, ...]``

Migration ``0011_seed_pm_wave2_sources`` seeds all three EMPTY (``{"markets": []}``
/ ``{"condition_ids": []}``) with a comment promising "a later wave populates
them". Nothing ever did, so the adapters logged ``polymarket_clob_no_token_ids`` /
``polymarket_trades_no_condition_ids`` / ``polymarket_oi_no_condition_ids`` and
returned ``[]`` — the deeper streams produced ZERO rows forever.

This use case closes that gap. It runs *inside content-ingestion* (no cross-service
DB read — R9) right after the base Gamma ``/markets`` poll, which already fetches
each market's ``conditionId`` + ``clobTokenIds`` as
:class:`PredictionMarketFetchResult`. From those results it derives the
``{condition_id, token_ids}`` work-list and upserts it into the three source
configs so the deeper-stream adapters have a real list to poll on their next
cadence.

Design choices:

- **Only OPEN markets** are seeded (``resolution_status == "open"``): resolved /
  cancelled markets no longer produce meaningful price/trade/OI movement, and
  including them would waste the deeper-stream fetch budget.
- **Bounded fan-out**: the list is capped at ``max_markets`` (default 500) so a
  spike in the live market universe cannot blow up the per-cadence fetch count
  of the CLOB/trades/OI adapters (each iterates the whole list per poll).
- **Idempotent**: the config is only written when the derived work-list DIFFERS
  from the stored one, so a re-run with the same universe is a no-op (no config
  churn, no ``config_hash`` thrash, no duplicate rows — the work-list is keyed on
  ``condition_id`` and deduplicated).
- **Best-effort / additive**: this never blocks the base snapshot ingestion; the
  worker calls it in its own short-lived session with an outer guard.

The base adapter already holds the exact ``condition_id → [token_ids]`` mapping,
so there is no need to re-fetch or reach into another service's tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from content_ingestion.application.ports.repositories import SourcePort
    from content_ingestion.domain.entities import PredictionMarketFetchResult

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Source types whose config the deeper-stream adapters read. Kept as string
# literals (not the SourceType enum) because this application-layer use case
# compares against the raw ``sources.source_type`` column value.
_CLOB_SOURCE_TYPE = "polymarket_clob"
_TRADES_SOURCE_TYPE = "polymarket_data_trades"
_OI_SOURCE_TYPE = "polymarket_data_oi"

# Only these markets are considered "live" for the deeper streams.
_OPEN_STATUS = "open"

# Default cap on the deeper-stream fetch fan-out. Each CLOB/trades/OI poll
# iterates the WHOLE work-list, so an unbounded list would multiply their
# per-cadence request count without bound. 500 open markets is already a very
# wide universe for the demo footprint.
DEFAULT_MAX_MARKETS = 500


@dataclass(frozen=True)
class WorklistSeedSummary:
    """Outcome of one seeding cycle (for logging / tests)."""

    markets: int = 0
    clob_updated: bool = False
    trades_updated: bool = False
    oi_updated: bool = False


def build_market_worklist(
    results: list[PredictionMarketFetchResult],
    max_markets: int = DEFAULT_MAX_MARKETS,
) -> list[dict[str, Any]]:
    """Derive the ``[{condition_id, token_ids}]`` work-list from fetched markets.

    Filters to OPEN markets, deduplicates on ``condition_id`` (a market can appear
    twice across the two synthetic docs / re-delivery), preserves fetch order, and
    caps the result at ``max_markets``.

    Args:
        results: The base Gamma ``/markets`` fetch results.
        max_markets: Maximum number of markets to include (fan-out bound).

    Returns:
        One ``{"condition_id": str, "token_ids": list[str]}`` dict per open market,
        capped and deduplicated.
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        if result.resolution_status != _OPEN_STATUS:
            continue
        condition_id = (result.market_id or "").strip()
        if not condition_id or condition_id in seen:
            continue
        token_ids = [o.token_id for o in result.outcomes if o.token_id]
        seen.add(condition_id)
        items.append({"condition_id": condition_id, "token_ids": token_ids})
        if len(items) >= max_markets:
            break
    return items


class SeedPredictionStreamWorklistsUseCase:
    """Populate the CLOB/trades/OI source configs from the live market universe.

    Args:
        source_repo: Repository over the ``sources`` table (``get_all`` + ``update``).
        commit_fn: Async callable committing the shared DB session.
        max_markets: Fan-out cap for the derived work-list.
    """

    def __init__(
        self,
        source_repo: SourcePort,
        commit_fn: Callable[[], Coroutine[Any, Any, None]],
        *,
        max_markets: int = DEFAULT_MAX_MARKETS,
    ) -> None:
        self._source_repo = source_repo
        self._commit_fn = commit_fn
        self._max_markets = max_markets

    async def execute(self, results: list[PredictionMarketFetchResult]) -> WorklistSeedSummary:
        """Build the work-list from ``results`` and upsert it into the 3 configs.

        Returns a summary describing which source configs were actually rewritten.
        A source config is rewritten ONLY when the derived value differs from what
        is stored (idempotent — a stable universe produces no writes).
        """
        worklist = build_market_worklist(results, self._max_markets)
        if not worklist:
            # Nothing open to seed (e.g. an all-resolved batch); leave configs as-is.
            return WorklistSeedSummary()

        condition_ids = [m["condition_id"] for m in worklist]

        # Match the seeded rows by source_type. get_all() is cheap (a handful of
        # rows) and avoids adding a bespoke port method for three fixed types.
        sources = await self._source_repo.get_all()
        by_type: dict[str, Any] = {}
        for src in sources:
            # First row per type wins (there is exactly one seeded row per type).
            by_type.setdefault(src.source_type, src)

        clob_updated = await self._update_markets_config(by_type.get(_CLOB_SOURCE_TYPE), worklist)
        trades_updated = await self._update_markets_config(by_type.get(_TRADES_SOURCE_TYPE), worklist)
        oi_updated = await self._update_condition_ids_config(by_type.get(_OI_SOURCE_TYPE), condition_ids)

        if clob_updated or trades_updated or oi_updated:
            await self._commit_fn()

        summary = WorklistSeedSummary(
            markets=len(worklist),
            clob_updated=clob_updated,
            trades_updated=trades_updated,
            oi_updated=oi_updated,
        )
        logger.info(
            "prediction_stream_worklist_seeded",
            markets=summary.markets,
            clob_updated=summary.clob_updated,
            trades_updated=summary.trades_updated,
            oi_updated=summary.oi_updated,
            cap=self._max_markets,
        )
        return summary

    async def _update_markets_config(
        self,
        source: Any | None,
        worklist: list[dict[str, Any]],
    ) -> bool:
        """Upsert ``config["markets"] = worklist`` for a CLOB/trades source.

        Preserves any other config keys. Writes only when the value changed
        (idempotent). Returns True when a write happened.
        """
        if source is None:
            return False
        existing = dict(source.config or {})
        if existing.get("markets") == worklist:
            return False
        existing["markets"] = worklist
        await self._source_repo.update(source.id, config=existing)
        return True

    async def _update_condition_ids_config(
        self,
        source: Any | None,
        condition_ids: list[str],
    ) -> bool:
        """Upsert ``config["condition_ids"] = condition_ids`` for the OI source.

        Preserves any other config keys. Writes only when the value changed
        (idempotent). Returns True when a write happened.
        """
        if source is None:
            return False
        existing = dict(source.config or {})
        if existing.get("condition_ids") == condition_ids:
            return False
        existing["condition_ids"] = condition_ids
        await self._source_repo.update(source.id, config=existing)
        return True
