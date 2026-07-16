"""Repository for the ``earnings_calendar`` table (fix/data-coverage-warns).

WHY A DEDICATED REPO (mirrors PgInsiderTransactionsRepository):
  Earnings-calendar rows are a distinct cardinality from the fundamentals
  section blobs — one global EODHD ``/calendar/earnings`` fetch yields MANY
  companies, each contributing a ``(instrument_id, report_date)`` row. The
  table is populated by ``EarningsCalendarConsumer`` and read back by the
  snapshot writer's ``fetch_next_earnings_date`` (screener
  ``next_earnings_date`` column).

Single write method:
  * ``insert_batch`` — idempotent via the ``uq_earnings_calendar`` unique
    constraint on ``(instrument_id, report_date)``. ON CONFLICT DO UPDATE
    with COALESCE so a later partial re-fetch (e.g. estimate known now,
    actual arrives after the report) never clobbers a previously-stored
    non-null value with NULL — the same COALESCE convention used by
    ``fundamentals_snapshot_writer`` (F-Q2-03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

import common.ids  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgEarningsCalendarRepository:
    """Async repository for the ``earnings_calendar`` table."""

    def __init__(self, session: AsyncSession) -> None:
        # Bound at construction (same pattern as PgInsiderTransactionsRepository)
        # so callers do not pass the session per-method.
        self._session = session

    async def insert_batch(self, rows: list[dict[str, Any]]) -> int:
        """Upsert a batch of earnings rows; ON CONFLICT (instrument_id, report_date).

        Each row dict must carry ``instrument_id`` and ``report_date`` (the
        natural key) plus the optional ``fiscal_date``, ``eps_estimate``,
        ``eps_actual``, ``before_after`` and ``currency`` columns. The ``id``
        is filled here (UUIDv7 default) and ``ingested_at`` is refreshed to
        ``now()`` on every upsert.

        Returns the number of rows offered (not the number actually written —
        Postgres does not report per-row insert/update splits without
        RETURNING, and callers only need the offered count for logging).
        """
        if not rows:
            return 0
        # COALESCE(EXCLUDED.col, earnings_calendar.col): a re-fetch that lacks a
        # value (e.g. the estimate-only pre-report row) must not overwrite a
        # value we already stored from an earlier fetch. Mirrors the
        # fundamentals-snapshot COALESCE policy exactly.
        sql = text(
            """
            INSERT INTO earnings_calendar (
                id, instrument_id, report_date, fiscal_date,
                eps_estimate, eps_actual, before_after, currency
            )
            VALUES (
                :id, :instrument_id, :report_date, :fiscal_date,
                :eps_estimate, :eps_actual, :before_after, :currency
            )
            ON CONFLICT ON CONSTRAINT uq_earnings_calendar
            DO UPDATE SET
                fiscal_date  = COALESCE(EXCLUDED.fiscal_date, earnings_calendar.fiscal_date),
                eps_estimate = COALESCE(EXCLUDED.eps_estimate, earnings_calendar.eps_estimate),
                eps_actual   = COALESCE(EXCLUDED.eps_actual, earnings_calendar.eps_actual),
                before_after = COALESCE(EXCLUDED.before_after, earnings_calendar.before_after),
                currency     = COALESCE(EXCLUDED.currency, earnings_calendar.currency),
                ingested_at  = now()
            """
        )
        for row in rows:
            params = dict(row)
            params.setdefault("id", common.ids.new_uuid7())
            # Defensive defaults so a caller may omit any optional column.
            params.setdefault("fiscal_date", None)
            params.setdefault("eps_estimate", None)
            params.setdefault("eps_actual", None)
            params.setdefault("before_after", None)
            params.setdefault("currency", None)
            await self._session.execute(sql, params)
        return len(rows)
