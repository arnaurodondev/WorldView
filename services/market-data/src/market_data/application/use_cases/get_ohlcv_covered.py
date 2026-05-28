"""Use case: list instruments with OHLCV coverage (PLAN-0089 Wave L-4b).

WHY THIS USE CASE EXISTS:
  ``market-ingestion`` needs to expand the insider-transactions universe
  from the hardcoded 3-ticker seed (AAPL/TSLA/AMZN) to the live universe
  of OHLCV-covered instruments. Cross-service DB reads violate R9, so the
  worker calls this internal REST endpoint instead.

  Modelled on ``get_top_by_market_cap`` but simpler: no per-instrument
  market-cap join is required, and the result list is the *full* set
  (no pagination cap beyond an explicit ``limit`` clamp) because the
  caller persists the result into the ingestion-policy table once per
  refresh.

ACTIVE filter: ``has_ohlcv = TRUE`` only. Instruments with quotes or
fundamentals but no daily bars are excluded — without OHLCV the insider
rollup's price-impact context is meaningless.

R27: read-only — runs on the read replica.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_MAX_LIMIT = 5000  # Same hard cap as get_top_by_market_cap.


async def query_ohlcv_covered(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return ``(total, rows)`` for instruments with ``has_ohlcv = TRUE``.

    Rows are ordered by symbol ASC for deterministic pagination. Each row
    dict carries: id, symbol, exchange, country, currency_code.
    """
    from sqlalchemy import text

    limit = max(1, min(_MAX_LIMIT, int(limit)))
    offset = max(0, int(offset))

    count_stmt = text(
        """
        SELECT COUNT(*)::int AS total
        FROM instruments
        WHERE has_ohlcv = TRUE
        """
    )
    total_row = await session.execute(count_stmt)
    total = int(total_row.scalar_one_or_none() or 0)

    rows_stmt = text(
        """
        SELECT
            i.id::text   AS id,
            i.symbol     AS symbol,
            i.exchange   AS exchange,
            i.country    AS country,
            i.currency_code AS currency_code
        FROM instruments i
        WHERE i.has_ohlcv = TRUE
        ORDER BY i.symbol ASC
        LIMIT :limit OFFSET :offset
        """
    )
    result = await session.execute(rows_stmt, {"limit": limit, "offset": offset})
    rows = [dict(row) for row in result.mappings().all()]
    return total, rows
