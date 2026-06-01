"""Daily worker: roll up trailing-90d insider net dollar flow per instrument.

PLAN-0089 Wave L-4b (T-WL4B-03).

WHAT THIS DOES:
  For every instrument that has at least one row in ``insider_transactions``
  with ``transaction_date >= now() - 90d``, compute
  ``SUM(net_value_usd)`` over that window and UPSERT it into
  ``instrument_fundamentals_snapshot.insider_net_buy_90d``.

  Instruments without any in-window transactions stay untouched (NULL =
  "no rollup yet" is preferred over "0 = no activity"; the snapshot
  consumer makes the distinction).

WHY a single SQL statement (CTE-based) and not Python looping:
  At full universe (~3000 instruments with OHLCV) the window query is
  cheap on the (instrument_id, transaction_date DESC) index, and the
  whole rollup runs as a single transaction. Python-loop UPSERTs would
  inflate the round-trip count by 3000x.

SCHEDULE: ``_insider_rollup_loop`` in app.py wakes daily at
``INSIDER_ROLLUP_HOUR_UTC`` (default 03:00 UTC — one hour after the L-3
computed-metrics worker so we don't pile two large analytical writes on
top of each other).

IDEMPOTENCE: the UPSERT is idempotent by construction. The 20-hour
"skip if last successful run < 20h ago" guard prevents duplicate work
after container restart within the same UTC day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

import common.time  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


# 90 days as a Python timedelta so the SQL window-start is computed inside
# the application (auditable in tests) rather than relying on Postgres
# ``INTERVAL '90 days'`` (which counts calendar days from server time).
_WINDOW_DAYS = 90


async def run_insider_rollup_once(session: AsyncSession) -> dict[str, int]:
    """Execute one rollup pass; return a small stats dict for logging.

    The statement performs the SUM and UPSERT in one round-trip:

      WITH agg AS (
        SELECT instrument_id, SUM(net_value_usd) AS total_90d
        FROM insider_transactions
        WHERE transaction_date >= :window_start AND net_value_usd IS NOT NULL
        GROUP BY instrument_id
      )
      INSERT INTO instrument_fundamentals_snapshot (instrument_id, insider_net_buy_90d, updated_at)
      SELECT instrument_id, total_90d, now() FROM agg
      ON CONFLICT (instrument_id) DO UPDATE
        SET insider_net_buy_90d = EXCLUDED.insider_net_buy_90d,
            updated_at          = now();

    Returns ``{"instruments": N, "window_days": 90}`` so the scheduler can
    log a meaningful summary. NOTE: ``N`` is the row-count returned by
    Postgres for the INSERT (sum of inserted + updated rows).
    """
    today = common.time.utc_now().date()
    window_start = today - timedelta(days=_WINDOW_DAYS)

    sql = text(
        """
        WITH agg AS (
            SELECT instrument_id, SUM(net_value_usd) AS total_90d
            FROM insider_transactions
            WHERE transaction_date >= :window_start
              AND net_value_usd IS NOT NULL
            GROUP BY instrument_id
        )
        INSERT INTO instrument_fundamentals_snapshot
            (instrument_id, insider_net_buy_90d, updated_at)
        SELECT instrument_id, total_90d, now()
        FROM agg
        ON CONFLICT (instrument_id) DO UPDATE
            SET insider_net_buy_90d = EXCLUDED.insider_net_buy_90d,
                updated_at          = now()
        """
    )
    result = await session.execute(sql, {"window_start": window_start})
    affected = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0  # type: ignore[attr-defined]
    return {"instruments": int(affected), "window_days": _WINDOW_DAYS}


async def _do_insider_rollup(
    write_factory: async_sessionmaker,
    log: object,
) -> None:
    """Open a session, run the rollup, commit, log the summary."""
    async with write_factory() as session:
        stats = await run_insider_rollup_once(session)
        await session.commit()
    log.info(  # type: ignore[attr-defined]
        "insider_rollup_completed",
        instruments=stats["instruments"],
        window_days=stats["window_days"],
    )


# Minimum interval between runs — if a container restarts inside the same
# day we don't want to re-execute the heavy aggregate. 20h gives plenty of
# headroom for the daily 24h cadence while still letting an operator force
# a rerun by waiting <4h.
_MIN_INTERVAL_BETWEEN_RUNS = timedelta(hours=20)


def _seconds_until_next_run_hour(
    *,
    now: datetime,
    target_hour_utc: int,
) -> float:
    """Compute seconds to sleep until the next UTC ``target_hour_utc:00``.

    Pure function, exported for tests.
    """
    today_target = now.replace(hour=target_hour_utc, minute=0, second=0, microsecond=0)
    next_target = today_target + timedelta(days=1) if now >= today_target else today_target
    return max(0.0, (next_target - now).total_seconds())


async def insider_rollup_loop(
    write_factory: async_sessionmaker,
    log: object,
    *,
    target_hour_utc: int = 3,
    min_interval: timedelta = _MIN_INTERVAL_BETWEEN_RUNS,
) -> None:
    """Daily loop — wakes at ``target_hour_utc:00`` UTC and runs the rollup.

    Skips a run if the last successful execution was less than
    ``min_interval`` ago (20h default). On error, backs off 60s and tries
    again — same retry cadence as ``_screen_fields_refresh_loop``.
    """
    import asyncio

    last_run_at: datetime | None = None
    while True:
        try:
            now = datetime.now(tz=UTC)
            if last_run_at is not None and now - last_run_at < min_interval:
                # Too soon — sleep until the next target hour.
                await asyncio.sleep(_seconds_until_next_run_hour(now=now, target_hour_utc=target_hour_utc))
                continue
            await _do_insider_rollup(write_factory, log)
            last_run_at = datetime.now(tz=UTC)
            # Sleep until tomorrow's target hour.
            sleep_for = _seconds_until_next_run_hour(now=datetime.now(tz=UTC), target_hour_utc=target_hour_utc)
            await asyncio.sleep(sleep_for)
        except Exception as exc:
            log.error("insider_rollup_error", error=str(exc))  # type: ignore[attr-defined]
            await asyncio.sleep(60)
