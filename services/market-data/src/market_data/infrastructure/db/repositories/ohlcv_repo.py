"""PostgreSQL adapter for OHLCVRepository.

Key implementation detail: ``bulk_upsert_with_priority`` uses
``INSERT ... ON CONFLICT DO UPDATE SET ... WHERE EXCLUDED.provider_priority
>= ohlcv_bars.provider_priority`` so that lower-priority data never
overwrites a higher-priority stored record.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import distinct, func, select, text
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import OHLCVRepository
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncSession


# PostgreSQL's wire protocol caps a single statement at 65_535 bound parameters
# (a uint16 in the Bind message).  ``INSERT ... VALUES`` binds one parameter per
# column per row, so a multi-row VALUES with N columns blows past the cap at
# ``65_535 / N`` rows.  A single OHLCV combined upsert can carry tens of
# thousands of rows (a full poll cycle of ~50 symbols x hundreds of 1m bars, or
# a deep backfill), which previously failed the statement, stalled the Kafka
# offset, and crash-looped the consumer (BP: combined-upsert wire-param overflow).
#
# We chunk every multi-row INSERT to a safe ROW count well under the limit.
# CRITICAL (2026-06-21): the real limit is 32_767, NOT 65_535. asyncpg 0.29
# enforces the SIGNED int16 ceiling client-side before the bind hits the wire —
# ``asyncpg/protocol/prepared_stmt.pyx``: ``if len(args) > 32767: raise
# InterfaceError("the number of query arguments cannot exceed 32767")``. The old
# 65_535 guard + 5_000-row chunk bound 5_000 x 13 = 65_000 params per derived/
# priority chunk -> every full chunk raised InterfaceError and crash-looped the
# consumer (the very failure the chunking was meant to prevent). At 13 columns the
# real ceiling is 32_767 / 13 ~= 2_520 rows; 2_000 leaves headroom for future cols.
_MAX_PARAMS = 32_767
_UPSERT_CHUNK_ROWS = 2_000


def _chunk_rows(values: list[dict[str, Any]], chunk_size: int = _UPSERT_CHUNK_ROWS) -> Iterator[list[dict[str, Any]]]:
    """Yield ``values`` in row-count chunks that stay under the param limit.

    Splitting by a fixed ROW count (rather than a param count) keeps each chunk's
    bound-parameter total at ``chunk_size * columns`` — guaranteed < 65_535 for
    any VALUES row with ≤ 13 columns.  An empty input yields nothing.
    """
    for start in range(0, len(values), chunk_size):
        yield values[start : start + chunk_size]


# The conflict key of the ``ohlcv_bars`` unique index that ``ON CONFLICT`` targets.
_CONFLICT_KEY = ("instrument_id", "timeframe", "bar_date")


def _dedupe_by_conflict_key(values: list[dict[str, Any]], *, priority_guarded: bool) -> list[dict[str, Any]]:
    """Collapse rows sharing the ON CONFLICT key to one winner per key.

    PostgreSQL rejects an ``INSERT ... ON CONFLICT DO UPDATE`` whose VALUES list
    contains the SAME conflict key ``(instrument_id, timeframe, bar_date)`` more
    than once — ``CardinalityViolationError: ON CONFLICT DO UPDATE command cannot
    affect row a second time``.  Backfill / replay batches routinely carry
    duplicate keys (overlapping crypto 1m windows, e.g. ARB-USD re-published with
    overlapping ranges), so without this dedup the chunk dies and crash-loops the
    consumer (it re-reads the same poison batch on restart; 2_686 restarts seen).

    The dedup must reproduce the *final state* the upsert would have reached if
    Postgres allowed dup keys, so dedup-then-upsert is observationally identical:

    * ``priority_guarded`` (``bulk_upsert_with_priority``): the upsert's WHERE
      clause only overwrites when ``EXCLUDED.provider_priority >=`` the stored
      priority.  Within a single statement Postgres processes the VALUES in order,
      so the surviving value for a key is the one with the highest priority, and
      on a tie the LAST occurrence (most recent in the batch) wins.  We keep that
      winner: ``new`` replaces the kept row when its priority is ``>=`` the kept
      row's priority.
    * non-guarded (``bulk_upsert_derived``): the upsert overwrites
      unconditionally, so the LAST occurrence of a key wins.

    Order is preserved by first-seen position so chunking downstream stays stable.
    """
    winners: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in values:
        key = tuple(row[k] for k in _CONFLICT_KEY)
        existing = winners.get(key)
        if existing is None:
            winners[key] = row
            continue
        if not priority_guarded:
            # Unconditional overwrite → last occurrence wins.
            winners[key] = row
        elif row["provider_priority"] >= existing["provider_priority"]:
            # Priority-guarded overwrite (>= mirrors the ON CONFLICT WHERE):
            # higher priority wins; equal priority → last occurrence wins.
            winners[key] = row
    return list(winners.values())


class PgOHLCVRepository(OHLCVRepository):
    """SQLAlchemy-backed implementation of OHLCVRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── mapping ────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_domain(row: OHLCVBarModel) -> OHLCVBar:
        return OHLCVBar(
            instrument_id=row.instrument_id,
            timeframe=Timeframe(row.timeframe),
            bar_date=row.bar_date,
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            volume=int(row.volume) if row.volume is not None else 0,
            adjusted_close=Decimal(str(row.adjusted_close)) if row.adjusted_close is not None else None,
            source=row.source or "",
            provider_priority=ProviderPriority(provider="unknown", priority=int(row.provider_priority)),
            is_derived=bool(row.is_derived),
            is_partial=bool(row.is_partial),
        )

    # ── commands ───────────────────────────────────────────────────────────────

    async def bulk_upsert_with_priority(self, bars: list[OHLCVBar]) -> None:
        """Bulk-upsert OHLCV bars with provider-priority conflict resolution.

        ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE SET ...
        WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority

        This guards against lower-priority sources overwriting higher-priority
        stored records (e.g., Yahoo overwriting Polygon data).
        """
        if not bars:
            return

        values = [
            {
                "instrument_id": bar.instrument_id,
                "timeframe": str(bar.timeframe),
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume if bar.volume is not None else 0,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "provider_priority": bar.provider_priority.priority,
                "is_partial": bar.is_partial,
            }
            for bar in bars
        ]

        # Collapse within-batch duplicate conflict keys BEFORE chunking.  A bulk
        # ON CONFLICT DO UPDATE that sees the same (instrument_id, timeframe,
        # bar_date) twice in one statement raises CardinalityViolationError, which
        # crash-looped the consumer on overlapping backfill/replay windows.  We
        # keep the highest-priority (tie → last) row per key, matching what the
        # priority-guarded ON CONFLICT WHERE would have resolved to.
        values = _dedupe_by_conflict_key(values, priority_guarded=True)

        # Chunk the VALUES list so no single INSERT exceeds Postgres's 65_535
        # bound-parameter wire limit (see ``_UPSERT_CHUNK_ROWS``).  Each chunk is
        # its own ON CONFLICT upsert and is therefore idempotent: a partial
        # failure mid-batch leaves earlier chunks applied (this method runs inside
        # the caller's transaction, so the OUTER commit makes all chunks atomic;
        # re-delivery re-runs the whole batch and the ON CONFLICT clause is a
        # no-op for already-stored rows).  We never half-commit silently — any
        # chunk error propagates and rolls the caller's transaction back.
        for chunk in _chunk_rows(values):
            stmt = (
                insert(OHLCVBarModel)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=["instrument_id", "timeframe", "bar_date"],
                    set_={
                        "open": insert(OHLCVBarModel).excluded.open,
                        "high": insert(OHLCVBarModel).excluded.high,
                        "low": insert(OHLCVBarModel).excluded.low,
                        "close": insert(OHLCVBarModel).excluded.close,
                        "volume": insert(OHLCVBarModel).excluded.volume,
                        "adjusted_close": insert(OHLCVBarModel).excluded.adjusted_close,
                        "source": insert(OHLCVBarModel).excluded.source,
                        "provider_priority": insert(OHLCVBarModel).excluded.provider_priority,
                        "is_partial": insert(OHLCVBarModel).excluded.is_partial,
                    },
                    where=(insert(OHLCVBarModel).excluded.provider_priority >= OHLCVBarModel.provider_priority),
                )
            )
            await self._session.execute(stmt)

    # ── queries ────────────────────────────────────────────────────────────────

    async def find_by_instrument_timeframe_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        *,
        limit: int | None = None,
    ) -> list[OHLCVBar]:
        """Return bars for the given instrument/timeframe within [start, end].

        WHY limit pushdown: callers that only need the last N bars (e.g. the
        OHLCV API endpoint with its default limit=200) previously fetched every
        matching row and sliced in Python.  For a 550-day window (~390 bars)
        this wastes ~190 rows of I/O and Decimal conversion.  By pushing the
        LIMIT to the DB with ORDER BY DESC we only materialise the rows we keep.

        The result is reversed back to ASC order before returning so existing
        callers see no behavioural change — they always receive bars in
        chronological order.
        """
        start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC)

        if limit is not None:
            # Use DESC + LIMIT to materialise only the most-recent N rows, then
            # reverse in Python.  This avoids fetching the full date-range and
            # is equivalent to bars[-limit:] on the full ASC result.
            result = await self._session.execute(
                select(OHLCVBarModel)
                .where(
                    OHLCVBarModel.instrument_id == instrument_id,
                    OHLCVBarModel.timeframe == str(timeframe),
                    OHLCVBarModel.bar_date >= start_dt,
                    OHLCVBarModel.bar_date <= end_dt,
                )
                .order_by(OHLCVBarModel.bar_date.desc())
                .limit(limit)
            )
            # Reverse so callers receive bars in chronological (ASC) order.
            return [self._to_domain(row) for row in reversed(result.scalars().all())]

        # No limit — return all bars ASC (original behaviour).
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.bar_date >= start_dt,
                OHLCVBarModel.bar_date <= end_dt,
            )
            .order_by(OHLCVBarModel.bar_date.asc())
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_available_timeframes(self, instrument_id: str) -> list[Timeframe]:
        tf_result: Any = await self._session.execute(
            select(distinct(OHLCVBarModel.timeframe)).where(OHLCVBarModel.instrument_id == instrument_id)
        )
        return [Timeframe(tf) for tf in tf_result.scalars().all()]

    async def get_date_range(self, instrument_id: str, timeframe: Timeframe) -> tuple[date, date] | None:
        range_result = await self._session.execute(
            select(
                func.min(OHLCVBarModel.bar_date),
                func.max(OHLCVBarModel.bar_date),
            ).where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
            )
        )
        min_date: datetime | None
        max_date: datetime | None
        min_date, max_date = range_result.one()
        if min_date is None or max_date is None:
            return None
        return (min_date.date(), max_date.date())

    async def bulk_upsert_derived(self, bars: list[OHLCVBar]) -> None:
        """Upsert locally-derived bars unconditionally (no priority guard).

        Derived bars are always the authoritative source for their timeframe —
        no external provider will ever supply competing 1w/1M data via the
        normal ingestion path after PLAN-0036.  The ON CONFLICT clause always
        overwrites so that a fresh derivation pass replaces stale aggregates.
        """
        if not bars:
            return

        values = [
            {
                "instrument_id": bar.instrument_id,
                "timeframe": str(bar.timeframe),
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume if bar.volume is not None else 0,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "provider_priority": bar.provider_priority.priority,
                "is_derived": True,
                "is_partial": bar.is_partial,
            }
            for bar in bars
        ]

        # Dedupe within-batch duplicate conflict keys BEFORE chunking (same
        # CardinalityViolationError risk as the priority path).  The derived
        # upsert overwrites unconditionally, so the LAST occurrence of a key is
        # the winner — mirror that here.
        values = _dedupe_by_conflict_key(values, priority_guarded=False)

        # Same param-limit chunking as ``bulk_upsert_with_priority`` — the derived
        # VALUES row is the widest here (13 columns), so ``_UPSERT_CHUNK_ROWS``
        # (5_000) is sized to keep ``5_000 * 13 = 65_000`` < 65_535.
        for chunk in _chunk_rows(values):
            stmt = (
                insert(OHLCVBarModel)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=["instrument_id", "timeframe", "bar_date"],
                    set_={
                        "open": insert(OHLCVBarModel).excluded.open,
                        "high": insert(OHLCVBarModel).excluded.high,
                        "low": insert(OHLCVBarModel).excluded.low,
                        "close": insert(OHLCVBarModel).excluded.close,
                        "volume": insert(OHLCVBarModel).excluded.volume,
                        "adjusted_close": insert(OHLCVBarModel).excluded.adjusted_close,
                        "source": insert(OHLCVBarModel).excluded.source,
                        "provider_priority": insert(OHLCVBarModel).excluded.provider_priority,
                        "is_derived": insert(OHLCVBarModel).excluded.is_derived,
                        "is_partial": insert(OHLCVBarModel).excluded.is_partial,
                    },
                )
            )
            await self._session.execute(stmt)

    async def find_by_instrument_timeframe_datetime_range(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[OHLCVBar]:
        """Return bars within ``[start_dt, end_dt]`` (inclusive), ordered ascending."""
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.bar_date >= start_dt,
                OHLCVBarModel.bar_date <= end_dt,
            )
            .order_by(OHLCVBarModel.bar_date.asc())
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def find_derived(
        self,
        instrument_id: str,
        timeframe: Timeframe,
        *,
        limit: int = 200,
    ) -> list[OHLCVBar]:
        """Return derived bars sorted by bar_date descending, capped at ``limit``."""
        result = await self._session.execute(
            select(OHLCVBarModel)
            .where(
                OHLCVBarModel.instrument_id == instrument_id,
                OHLCVBarModel.timeframe == str(timeframe),
                OHLCVBarModel.is_derived.is_(True),
            )
            .order_by(OHLCVBarModel.bar_date.desc())
            .limit(limit)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def get_sector_period_returns(self, lookback_days: int) -> list[dict]:
        """Compute average period return per GICS sector from daily OHLCV bars.

        WHY daily bars + calendar lookback: derived weekly/monthly bars require at
        least 2 such bars per instrument to exist, which is rarely the case in
        production (only the current period's bar is available). Using daily bars
        with a calendar-based lookback (7 or 30 days) works with any instrument
        that has ≥2 trading days of history, making 1W and 1M viable.

        Uses LATERAL JOINs: first subquery finds the latest daily bar, second finds
        the closest daily bar at-or-before the lookback horizon.

        2026-06-12 (chat-eval root cause C): the ``prev`` LATERAL is now a
        two-tier ``LEFT JOIN`` (mirrors ``get_period_movers``) so sectors whose
        instruments have a daily history SHORTER than the lookback window still
        contribute a return instead of being silently dropped — this previously
        made 1W/1M sector heatmaps collapse to a handful of long-history names.

        2026-06-10 (frontend audit gap #6): each sector row now also carries
        ``top_mover_ticker`` / ``top_mover_return_pct`` — the instrument with the
        largest ABSOLUTE period return within the sector. The frontend heatmap
        previously had to client-side-join /market/period-movers to label tiles.
        Computed via DISTINCT ON over the same per-instrument CTE the average
        uses, so the extra cost is one sort over already-materialised rows.
        """
        sql = text(
            """
            WITH per_instrument AS (
                SELECT
                    i.sector AS sector,
                    i.symbol AS ticker,
                    (latest.close - prev.close) / NULLIF(prev.close, 0) * 100 AS return_pct
                FROM instruments i
                JOIN LATERAL (
                    SELECT close, bar_date FROM ohlcv_bars
                    WHERE instrument_id = i.id AND timeframe = '1d'
                    ORDER BY bar_date DESC LIMIT 1
                ) latest ON true
                LEFT JOIN LATERAL (
                    -- Two-tier prev: at-or-before horizon, else oldest bar
                    -- before latest (see get_period_movers for rationale).
                    SELECT close FROM (
                        (
                            SELECT close, bar_date, 0 AS tier FROM ohlcv_bars
                            WHERE instrument_id = i.id AND timeframe = '1d'
                              AND bar_date <= latest.bar_date - (INTERVAL '1 day' * :lookback_days)
                            ORDER BY bar_date DESC LIMIT 1
                        )
                        UNION ALL
                        (
                            SELECT close, bar_date, 1 AS tier FROM ohlcv_bars
                            WHERE instrument_id = i.id AND timeframe = '1d'
                              AND bar_date < latest.bar_date
                            ORDER BY bar_date ASC LIMIT 1
                        )
                    ) candidates
                    ORDER BY tier ASC LIMIT 1
                ) prev ON true
                WHERE i.sector IS NOT NULL
            ),
            sector_agg AS (
                SELECT
                    sector,
                    AVG(return_pct) AS change_pct,
                    COUNT(*)::int AS instrument_count
                FROM per_instrument
                GROUP BY sector
            ),
            top_movers AS (
                -- One row per sector: the largest absolute move (gainer OR loser).
                SELECT DISTINCT ON (sector)
                    sector,
                    ticker AS top_mover_ticker,
                    return_pct AS top_mover_return_pct
                FROM per_instrument
                WHERE return_pct IS NOT NULL
                ORDER BY sector, ABS(return_pct) DESC
            )
            SELECT
                a.sector AS name,
                a.change_pct,
                a.instrument_count,
                t.top_mover_ticker,
                t.top_mover_return_pct
            FROM sector_agg a
            LEFT JOIN top_movers t ON t.sector = a.sector
            ORDER BY a.change_pct DESC NULLS LAST
            """
        )
        result = await self._session.execute(sql, {"lookback_days": lookback_days})
        rows = result.mappings().all()
        return [
            {
                "name": row["name"],
                "change_pct": round(float(row["change_pct"]), 2) if row["change_pct"] is not None else None,
                "instrument_count": int(row["instrument_count"]),
                # Forward-compatible additions (2026-06-10): null when the sector
                # has no instrument with a computable return.
                "top_mover_ticker": row["top_mover_ticker"],
                "top_mover_return_pct": (
                    round(float(row["top_mover_return_pct"]), 2) if row["top_mover_return_pct"] is not None else None
                ),
            }
            for row in rows
        ]

    async def get_period_movers(
        self,
        lookback_days: int,
        mover_type: str,
        limit: int,
        offset: int = 0,
    ) -> list[dict]:
        """Return top gainers or losers by period return from daily OHLCV bars.

        WHY daily bars + calendar lookback: see get_sector_period_returns docstring.
        offset: SQL OFFSET for paginating through the sorted leaderboard.

        2026-06-12 (chat-eval root cause C — non-1D periods returned empty):
        the ``prev`` LATERAL was an INNER JOIN requiring a daily bar AT OR BEFORE
        ``latest.bar_date - N days``. For ``1D`` (N=1) virtually every instrument
        has such a bar, so movers populated. For ``1W`` (N=7) / ``1M`` (N=30) any
        instrument whose daily history is SHORTER than the lookback window had no
        qualifying ``prev`` bar and was silently dropped by the INNER JOIN — so
        the live ``period="1W"`` request collapsed to a 1-item placeholder
        (``tc_movers_week_losers``). The fix makes ``prev`` a two-tier
        ``LEFT JOIN LATERAL``: prefer the bar at-or-before the horizon, but fall
        back to the OLDEST available bar strictly before ``latest`` when the
        instrument's history is shorter than the window. ``period_return_pct`` is
        then computed against the best-available baseline instead of dropping the
        instrument. Instruments with only ONE daily bar (no prior bar at all)
        still yield ``prev IS NULL`` → NULL return → sorted last via NULLS LAST.
        """
        order = "DESC" if mover_type == "gainers" else "ASC"
        # 2026-06-10 (frontend audit gap #4): also project the latest daily close
        # as ``last_price`` — the LATERAL subquery already materialises it, so
        # this is free. Consumers previously paid a second /internal/v1/price
        # batch call just to label movers with a price.
        sql = text(
            f"""
            SELECT
                i.id AS instrument_id,
                i.symbol AS ticker,
                i.name AS name,
                latest.close AS last_price,
                (latest.close - prev.close) / NULLIF(prev.close, 0) * 100 AS period_return_pct
            FROM instruments i
            JOIN LATERAL (
                SELECT close, bar_date FROM ohlcv_bars
                WHERE instrument_id = i.id AND timeframe = '1d'
                ORDER BY bar_date DESC LIMIT 1
            ) latest ON true
            LEFT JOIN LATERAL (
                -- Tier 1: most recent bar at-or-before the lookback horizon.
                -- Tier 2 (fallback): oldest bar strictly before ``latest`` when
                -- the instrument's history is shorter than the window. Picking
                -- the OLDEST (not newest) fallback maximises the lookback we can
                -- honour with the data available, so a 1W return on an
                -- instrument with 4 days of history compares latest vs its
                -- earliest bar rather than dropping it.
                SELECT close FROM (
                    (
                        SELECT close, bar_date, 0 AS tier FROM ohlcv_bars
                        WHERE instrument_id = i.id AND timeframe = '1d'
                          AND bar_date <= latest.bar_date - (INTERVAL '1 day' * :lookback_days)
                        ORDER BY bar_date DESC LIMIT 1
                    )
                    UNION ALL
                    (
                        SELECT close, bar_date, 1 AS tier FROM ohlcv_bars
                        WHERE instrument_id = i.id AND timeframe = '1d'
                          AND bar_date < latest.bar_date
                        ORDER BY bar_date ASC LIMIT 1
                    )
                ) candidates
                ORDER BY tier ASC LIMIT 1
            ) prev ON true
            WHERE i.sector IS NOT NULL
            ORDER BY period_return_pct {order} NULLS LAST
            LIMIT :lim OFFSET :off
            """
        )
        result = await self._session.execute(
            sql,
            {"lookback_days": lookback_days, "lim": limit, "off": offset},
        )
        rows = result.mappings().all()
        return [
            {
                "instrument_id": row["instrument_id"],
                "ticker": row["ticker"],
                "name": row["name"],
                # Forward-compatible addition (2026-06-10): latest daily close.
                "last_price": float(row["last_price"]) if row["last_price"] is not None else None,
                "period_return_pct": (
                    round(float(row["period_return_pct"]), 2) if row["period_return_pct"] is not None else None
                ),
            }
            for row in rows
        ]
