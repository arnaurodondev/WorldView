"""Use case: query the instrument_fundamentals_snapshot table.

WHY THIS USE CASE: The FundamentalsTab and InstrumentKeyMetrics panel need a
single flat snapshot of an instrument's key derived metrics (eps_ttm, beta,
avg_volume_30d, FCF, etc.).  Assembling this from 18 JSONB section tables at
query time would require many database round-trips.  The snapshot table
pre-computes these values at ingest/backfill time and serves them in one query.

R27: read-only use cases use the read (replica) session when available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _query_snapshot(
    session: AsyncSession,
    instrument_id: str,
) -> dict[str, Any] | None:
    """Return the snapshot row for *instrument_id*, or None if not found.

    PLAN-0053 platform-stability iter-1 F-PLATFORM-02: Application layer must
    not import from infrastructure (LAYER-APP-ISOLATION rule). Previously this
    function imported the SQLAlchemy ORM model — even though the import was
    function-local, the architecture test flags any infrastructure import in
    application/. Switched to a parameterized raw SQL query via ``text()`` so
    the use case stays fully decoupled from the ORM. The keys/types of the
    returned dict are unchanged so callers are unaffected.
    """
    from sqlalchemy import text

    stmt = text(
        """
        SELECT
            instrument_id, eps_ttm, beta, avg_volume_30d,
            operating_cash_flow, capex, free_cash_flow, fcf_margin,
            interest_coverage, net_debt_to_ebitda, credit_rating,
            updated_at
        FROM instrument_fundamentals_snapshot
        WHERE instrument_id = :instrument_id
        """
    )
    result = await session.execute(stmt, {"instrument_id": instrument_id})
    row = result.mappings().first()
    if row is None:
        return None

    return {
        "instrument_id": row["instrument_id"],
        "eps_ttm": float(row["eps_ttm"]) if row["eps_ttm"] is not None else None,
        "beta": float(row["beta"]) if row["beta"] is not None else None,
        "avg_volume_30d": int(row["avg_volume_30d"]) if row["avg_volume_30d"] is not None else None,
        "operating_cash_flow": float(row["operating_cash_flow"]) if row["operating_cash_flow"] is not None else None,
        "capex": float(row["capex"]) if row["capex"] is not None else None,
        "free_cash_flow": float(row["free_cash_flow"]) if row["free_cash_flow"] is not None else None,
        "fcf_margin": float(row["fcf_margin"]) if row["fcf_margin"] is not None else None,
        "interest_coverage": float(row["interest_coverage"]) if row["interest_coverage"] is not None else None,
        "net_debt_to_ebitda": float(row["net_debt_to_ebitda"]) if row["net_debt_to_ebitda"] is not None else None,
        "credit_rating": row["credit_rating"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


class GetFundamentalsSnapshotUseCase:
    """Return the fundamentals snapshot for a single instrument.

    WHY ACCEPTS AsyncSession DIRECTLY: This use case only reads one table.
    Passing the full ReadOnlyUnitOfWork would be over-engineering for a single
    SELECT — the session is the right abstraction level here.  The dependency
    function in dependencies.py extracts the read session from the UoW so the
    API layer still satisfies R27 (uses the read replica when configured).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, instrument_id: str) -> dict[str, Any] | None:
        """Return snapshot dict or None if this instrument has no snapshot row."""
        return await _query_snapshot(self._session, instrument_id)
