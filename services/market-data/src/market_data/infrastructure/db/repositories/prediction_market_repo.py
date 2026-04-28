"""PostgreSQL adapters for PredictionMarketRepository and PredictionMarketSnapshotRepository."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_data.application.ports.repositories import (
    PredictionMarketRepository,
    PredictionMarketSnapshotRepository,
)
from market_data.domain.entities import PredictionMarket, PredictionMarketSnapshot
from market_data.infrastructure.db.models.prediction_markets import (
    PredictionMarketModel,
    PredictionMarketSnapshotModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _row_to_market(row: Any) -> PredictionMarket:
    """Map a raw DB row to a ``PredictionMarket`` domain entity."""
    return PredictionMarket(
        id=str(row.id),
        market_id=row.market_id,
        source=row.source,
        question=row.question,
        description=row.description,
        outcomes=row.outcomes if row.outcomes is not None else [],
        close_time=row.close_time,
        resolution_status=row.resolution_status,
        resolved_answer=row.resolved_answer,
        market_slug=row.market_slug,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_snapshot(row: Any) -> PredictionMarketSnapshot:
    """Map a raw DB row to a ``PredictionMarketSnapshot`` domain entity."""
    prices: dict[str, float] = row.outcomes_prices if row.outcomes_prices is not None else {}
    return PredictionMarketSnapshot(
        id=str(row.id),
        market_id=row.market_id,
        snapshot_at=row.snapshot_at,
        outcomes_prices=prices,
        volume_24h=Decimal(str(row.volume_24h)) if row.volume_24h is not None else None,
        liquidity=Decimal(str(row.liquidity)) if row.liquidity is not None else None,
        source_event_id=row.source_event_id,
    )


class PgPredictionMarketRepository(PredictionMarketRepository):
    """SQLAlchemy-backed implementation of PredictionMarketRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, market: PredictionMarket) -> PredictionMarket:
        """Insert or update a prediction market; return the persisted entity."""
        stmt = (
            pg_insert(PredictionMarketModel)
            .values(
                id=market.id,
                market_id=market.market_id,
                source=market.source,
                question=market.question,
                description=market.description,
                outcomes=market.outcomes,
                close_time=market.close_time,
                resolution_status=market.resolution_status,
                resolved_answer=market.resolved_answer,
                market_slug=market.market_slug,
            )
            .on_conflict_do_update(
                index_elements=["market_id"],
                set_={
                    "question": pg_insert(PredictionMarketModel).excluded.question,
                    "description": pg_insert(PredictionMarketModel).excluded.description,
                    "outcomes": pg_insert(PredictionMarketModel).excluded.outcomes,
                    "close_time": pg_insert(PredictionMarketModel).excluded.close_time,
                    "resolution_status": pg_insert(PredictionMarketModel).excluded.resolution_status,
                    "resolved_answer": pg_insert(PredictionMarketModel).excluded.resolved_answer,
                    # WHY update market_slug on conflict: slug may arrive on a later poll
                    # if the Gamma API added it after initial ingestion. Always take the
                    # newest non-null value. COALESCE keeps existing slug if new one is null.
                    "market_slug": text("COALESCE(EXCLUDED.market_slug, prediction_markets.market_slug)"),
                    "updated_at": text("now()"),
                },
            )
            .returning(
                PredictionMarketModel.id,
                PredictionMarketModel.market_id,
                PredictionMarketModel.source,
                PredictionMarketModel.question,
                PredictionMarketModel.description,
                PredictionMarketModel.outcomes,
                PredictionMarketModel.close_time,
                PredictionMarketModel.resolution_status,
                PredictionMarketModel.resolved_answer,
                PredictionMarketModel.market_slug,
                PredictionMarketModel.created_at,
                PredictionMarketModel.updated_at,
            )
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            # Should never happen — upsert always returns a row
            return market
        return _row_to_market(row)

    async def find_by_market_id(self, market_id: str) -> PredictionMarket | None:
        result = await self._session.execute(
            text(
                "SELECT id, market_id, source, question, description, outcomes, "
                "close_time, resolution_status, resolved_answer, market_slug, "
                "created_at, updated_at "
                "FROM prediction_markets WHERE market_id = :market_id LIMIT 1"
            ).bindparams(market_id=market_id)
        )
        row = result.fetchone()
        return _row_to_market(row) if row is not None else None

    async def list_markets(
        self,
        *,
        status: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[PredictionMarket, Decimal | None]], int]:
        """Return paginated ``(market, latest_volume_24h)`` pairs and total count.

        Adds a ``LEFT JOIN LATERAL`` to ``prediction_market_snapshots`` that
        pulls the single newest snapshot per market (ORDER BY snapshot_at
        DESC LIMIT 1).  PLAN-0048 D-1: the list endpoint must surface real
        24-hour volume — previously the field was hardcoded to ``None``
        because it lives on the hypertable, not the master ``prediction_markets``
        row.  LATERAL keeps the join evaluated per-row (uses the partial
        per-market index on snapshot_at) instead of a window function over
        the whole snapshot table.
        """
        # F-101: build WHERE clause from static string segments only; all user
        # values are bound via named parameters — no f-string interpolation of
        # user data.
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        # Base query — always-true predicate allows clean appending below.
        # WHY LEFT JOIN LATERAL (not DISTINCT ON over snapshots): we want at
        # most ONE additional column per market row, no behaviour change to
        # the existing pagination/ORDER/COUNT(*) OVER() shape.  LEFT (not
        # INNER) ensures markets without snapshots still appear with NULL
        # volume — matches the previous behaviour where volume was always
        # NULL.
        base = (
            "SELECT m.id, m.market_id, m.source, m.question, m.description, m.outcomes, "
            "m.close_time, m.resolution_status, m.resolved_answer, m.market_slug, "
            "m.created_at, m.updated_at, latest.volume_24h AS latest_volume_24h, "
            "COUNT(*) OVER() AS total "
            "FROM prediction_markets m "
            "LEFT JOIN LATERAL ("
            "  SELECT volume_24h "
            "  FROM prediction_market_snapshots s "
            "  WHERE s.market_id = m.market_id "
            "  ORDER BY s.snapshot_at DESC "
            "  LIMIT 1"
            ") latest ON TRUE"
        )
        predicates: list[str] = []

        if status is not None:
            predicates.append("m.resolution_status = :status")
            params["status"] = status

        if query is not None:
            # Escape ILIKE metacharacters before building the pattern (M-002).
            safe_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            predicates.append("m.question ILIKE :query_like ESCAPE '\\\\'")
            params["query_like"] = f"%{safe_query}%"

        where_sql = (" WHERE " + " AND ".join(predicates)) if predicates else ""
        full_sql = base + where_sql + " ORDER BY m.updated_at DESC LIMIT :limit OFFSET :offset"

        result = await self._session.execute(text(full_sql).bindparams(**params))
        rows = result.fetchall()
        if not rows:
            return [], 0
        total = int(rows[0].total)
        # Project each row into (market, latest_volume_24h).  Decimal cast
        # mirrors the snapshot row mapper for type consistency on the wire.
        pairs: list[tuple[PredictionMarket, Decimal | None]] = [
            (
                _row_to_market(row),
                Decimal(str(row.latest_volume_24h)) if row.latest_volume_24h is not None else None,
            )
            for row in rows
        ]
        return pairs, total


class PgPredictionMarketSnapshotRepository(PredictionMarketSnapshotRepository):
    """SQLAlchemy-backed implementation of PredictionMarketSnapshotRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_not_exists(self, snapshot: PredictionMarketSnapshot) -> bool:
        """Atomically insert a snapshot; return ``True`` if new, ``False`` on conflict."""
        stmt = (
            pg_insert(PredictionMarketSnapshotModel)
            .values(
                id=snapshot.id,
                market_id=snapshot.market_id,
                snapshot_at=snapshot.snapshot_at,
                outcomes_prices=snapshot.outcomes_prices,
                volume_24h=snapshot.volume_24h,
                liquidity=snapshot.liquidity,
                source_event_id=snapshot.source_event_id,
            )
            # WHY index_elements not constraint: migration 005 created uq_pms_market_snapshot
            # as a UNIQUE INDEX (not a UNIQUE CONSTRAINT), so ON CONFLICT ON CONSTRAINT raises
            # UndefinedObjectError. index_elements works with unique indexes.
            .on_conflict_do_nothing(index_elements=["market_id", "snapshot_at"])
            .returning(PredictionMarketSnapshotModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_snapshots(
        self,
        market_id: str,
        *,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
    ) -> list[PredictionMarketSnapshot]:
        # F-101: static SQL base; all user values bound via named parameters.
        params: dict[str, Any] = {"market_id": market_id, "limit": limit}
        predicates = ["market_id = :market_id"]

        if from_dt is not None:
            predicates.append("snapshot_at >= :from_dt")
            params["from_dt"] = from_dt

        if to_dt is not None:
            predicates.append("snapshot_at <= :to_dt")
            params["to_dt"] = to_dt

        where_sql = " AND ".join(predicates)
        full_sql = (
            "SELECT id, market_id, snapshot_at, outcomes_prices, "
            "volume_24h, liquidity, source_event_id "
            "FROM prediction_market_snapshots "
            "WHERE " + where_sql + " "
            "ORDER BY snapshot_at DESC "
            "LIMIT :limit"
        )

        result = await self._session.execute(text(full_sql).bindparams(**params))
        return [_row_to_snapshot(row) for row in result.fetchall()]

    async def get_latest_prices_batch(
        self,
        market_ids: list[str],
    ) -> dict[str, dict[str, float]]:
        """Return latest ``outcomes_prices`` per market using a single DISTINCT ON query."""
        if not market_ids:
            return {}
        sql = text(
            "SELECT DISTINCT ON (market_id) market_id, outcomes_prices "
            "FROM prediction_market_snapshots "
            "WHERE market_id = ANY(CAST(:market_ids AS TEXT[])) "
            "ORDER BY market_id, snapshot_at DESC"
        ).bindparams(market_ids=market_ids)
        result = await self._session.execute(sql)
        return {
            row.market_id: (row.outcomes_prices if row.outcomes_prices is not None else {}) for row in result.fetchall()
        }
