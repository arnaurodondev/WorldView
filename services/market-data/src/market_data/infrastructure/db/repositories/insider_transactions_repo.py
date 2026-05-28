"""Repository for the ``insider_transactions`` table (PLAN-0089 Wave L-4b).

WHY A DEDICATED REPO (not extending FundamentalsRepository):
  The fundamentals repo only handles section-keyed embedded blobs. The
  per-transaction insider feed is a different cardinality (N rows per
  envelope, indexed independently) and needs different write semantics
  (ON CONFLICT DO NOTHING on a 5-column natural key, not upsert-by-PK).

Two methods:
  * ``insert_batch`` — used by ``InsiderTransactionsConsumer``; idempotent
    via the natural-key unique constraint.
  * ``sum_window_usd`` — used by the daily ``rollup_insider_90d`` worker;
    returns the SUM(net_value_usd) for ``transaction_date >= window_start``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

import common.ids  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PgInsiderTransactionsRepository:
    """Async repository for the ``insider_transactions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        # Bound at construction (same pattern as PgFundamentalsRepository) so
        # callers do not pass the session per-method.
        self._session = session

    async def insert_batch(self, rows: list[dict[str, Any]]) -> int:
        """Insert a batch of insider transactions; ON CONFLICT DO NOTHING.

        Each row dict must carry the natural-key columns plus ``shares``,
        ``price_per_share``, ``net_value_usd`` and ``transaction_type``. The
        ``id`` and ``source`` columns are filled here (UUIDv7 default).
        Returns the number of rows offered (not the number actually inserted
        — Postgres does not report that without RETURNING and we don't need
        it for the rollup worker).
        """
        if not rows:
            return 0
        sql = text(
            """
            INSERT INTO insider_transactions (
                id, instrument_id, filer_name, filer_title,
                transaction_date, transaction_type, shares,
                price_per_share, net_value_usd, source
            )
            VALUES (
                :id, :instrument_id, :filer_name, :filer_title,
                :transaction_date, :transaction_type, :shares,
                :price_per_share, :net_value_usd, :source
            )
            ON CONFLICT ON CONSTRAINT uq_insider_transactions_natural_key
            DO NOTHING
            """
        )
        for row in rows:
            params = dict(row)
            params.setdefault("id", common.ids.new_uuid7())
            params.setdefault("source", "EODHD")
            await self._session.execute(sql, params)
        return len(rows)

    async def sum_window_usd(
        self,
        *,
        instrument_id: str,
        window_start: date,
    ) -> Decimal:
        """Return SUM(net_value_usd) for ``transaction_date >= window_start``.

        Returns Decimal("0") when no transactions exist (not None) so the
        caller can distinguish "rolled up, no activity" (0) from "not yet
        rolled up" (NULL) — the snapshot column stays NULL until the worker
        explicitly writes a number.
        """
        sql = text(
            """
            SELECT COALESCE(SUM(net_value_usd), 0) AS total
            FROM insider_transactions
            WHERE instrument_id = :instrument_id
              AND transaction_date >= :window_start
              AND net_value_usd IS NOT NULL
            """
        )
        result = await self._session.execute(sql, {"instrument_id": instrument_id, "window_start": window_start})
        row = result.first()
        return Decimal(str(row[0])) if row is not None and row[0] is not None else Decimal("0")
