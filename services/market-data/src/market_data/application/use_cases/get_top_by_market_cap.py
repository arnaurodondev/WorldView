"""Use case: return the top-N active instruments by latest market capitalisation.

WHY THIS USE CASE: PLAN-0100 T-W5-01. ``FundamentalsRefreshWorker`` in
``market-ingestion`` needs to know which symbols are currently in the top-N
by market cap so it can re-enqueue fundamentals fetches for the most
valuable / most-queried tickers first. Cross-service DB reads would violate
R9, so the worker calls this REST endpoint instead.

The query picks the most-recent ``market_capitalization`` row per instrument
from ``fundamental_metrics`` (one row per (instrument_id, as_of_date, metric,
period_type) — we want the latest ``as_of_date`` regardless of period_type).
Instruments without a market-cap row come last (NULLS LAST) so the worker
gets a deterministic ordering even for newly-listed names.

R27: read-only — runs on the read replica via the read session factory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# Hard guardrails on the public API. ``n`` is clamped here defensively even
# though the router also clamps — defence in depth so worker-driven calls
# that bypass FastAPI validation (e.g. internal mocks) cannot escalate into
# a 10k-row response.
_MIN_LIMIT = 1
_MAX_LIMIT = 5000


async def query_top_by_market_cap(
    session: AsyncSession,
    *,
    n: int,
    offset: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return ``(total, rows)`` for the top-N instruments by market cap.

    ``total`` is the count of active instruments — the same denominator used
    for pagination. Each row dict carries: id, symbol, exchange,
    market_cap_usd (Decimal | None), currency_code.

    Active = the instrument has at least one capability flag set
    (``has_ohlcv`` OR ``has_quotes`` OR ``has_fundamentals``). The
    ``instruments`` table has no ``is_active`` column today (see
    ``models/instruments.py``); a flag-based filter is the closest
    semantic equivalent and keeps the endpoint cheap.
    """
    from sqlalchemy import text

    # Clamp belt-and-braces — see module docstring.
    n = max(_MIN_LIMIT, min(_MAX_LIMIT, int(n)))
    offset = max(0, int(offset))

    # Count active instruments — same WHERE as the paginated query so the
    # caller's pagination math is consistent.
    count_stmt = text(
        """
        SELECT COUNT(*)::int AS total
        FROM instruments
        WHERE (has_ohlcv = TRUE OR has_quotes = TRUE OR has_fundamentals = TRUE)
        """
    )
    total_row = await session.execute(count_stmt)
    total = int(total_row.scalar_one_or_none() or 0)

    # DISTINCT ON picks the latest ``as_of_date`` row per instrument for the
    # ``market_capitalization`` metric. LEFT JOIN keeps instruments that have
    # never received a fundamentals fetch — those sort last (NULLS LAST).
    rows_stmt = text(
        """
        WITH latest_mktcap AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id,
                value_numeric AS market_cap_usd
            FROM fundamental_metrics
            WHERE metric = 'market_capitalization'
              AND value_numeric IS NOT NULL
            ORDER BY instrument_id, as_of_date DESC
        )
        SELECT
            i.id::text AS id,
            i.symbol,
            i.exchange,
            lm.market_cap_usd,
            i.currency_code
        FROM instruments i
        LEFT JOIN latest_mktcap lm ON i.id = lm.instrument_id
        WHERE (i.has_ohlcv = TRUE OR i.has_quotes = TRUE OR i.has_fundamentals = TRUE)
        ORDER BY lm.market_cap_usd DESC NULLS LAST, i.symbol ASC
        LIMIT :limit OFFSET :offset
        """
    )
    result = await session.execute(rows_stmt, {"limit": n, "offset": offset})
    rows = [dict(row) for row in result.mappings().all()]
    return total, rows
