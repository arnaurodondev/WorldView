"""PostgreSQL adapter for SecurityRepository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from market_data.application.ports.repositories import SecurityRepository
from market_data.domain.entities import Security
from market_data.infrastructure.db.models.securities import SecurityModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# F-S09: explicit allowlist for ``update_from_enrichment`` columns.  The SET
# clause is built by string interpolation on ``fields`` keys, so any caller
# that managed to pass a hostile column name (e.g. via a misconfigured
# upstream port) could write to an arbitrary column.  This guard rejects the
# call before any SQL is constructed.
_ALLOWED_ENRICHMENT_COLUMNS: frozenset[str] = frozenset(
    {"description", "sector", "industry", "country", "currency", "figi", "isin", "name"}
)


class PgSecurityRepository(SecurityRepository):
    """SQLAlchemy-backed implementation of SecurityRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── mapping ────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_domain(row: SecurityModel) -> Security:
        return Security(
            id=row.id,
            figi=row.figi,
            isin=row.isin,
            name=row.name,
            sector=row.sector,
            industry=row.industry,
            country=row.country,
            currency=row.currency,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ── queries ────────────────────────────────────────────────────────────────

    async def find_by_id(self, id: str) -> Security | None:  # noqa: A002
        result = await self._session.execute(select(SecurityModel).where(SecurityModel.id == id))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def find_by_figi(self, figi: str) -> Security | None:
        result = await self._session.execute(select(SecurityModel).where(SecurityModel.figi == figi))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def find_by_isin(self, isin: str) -> Security | None:
        result = await self._session.execute(select(SecurityModel).where(SecurityModel.isin == isin))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list(self, limit: int = 100, offset: int = 0) -> tuple[list[Security], int]:
        from sqlalchemy import func

        count_result = await self._session.execute(select(func.count()).select_from(SecurityModel))
        total = count_result.scalar_one()

        rows_result = await self._session.execute(select(SecurityModel).offset(offset).limit(limit))
        securities = [self._to_domain(row) for row in rows_result.scalars().all()]
        return securities, total

    async def upsert(self, security: Security) -> Security:
        values = {
            "id": security.id,
            "figi": security.figi,
            "isin": security.isin,
            "name": security.name,
            "sector": security.sector,
            "industry": security.industry,
            "country": security.country,
            "currency": security.currency,
            "description": security.description,
        }
        update_values = {
            "figi": security.figi,
            "isin": security.isin,
            "name": security.name,
            "sector": security.sector,
            "industry": security.industry,
            "country": security.country,
            "currency": security.currency,
            "description": security.description,
        }

        # Prefer FIGI as the natural identity when present so repeated seeds with
        # different generated IDs do not violate the unique FIGI constraint.
        conflict_columns = ["figi"] if security.figi else ["id"]

        stmt = (
            insert(SecurityModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=conflict_columns,
                set_=update_values,
            )
            .returning(SecurityModel)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one()
        return self._to_domain(row)

    async def update_from_enrichment(self, security_id: str, fields: dict[str, str | None]) -> None:
        """COALESCE-update: only write a column when the current DB value IS NULL."""
        if not fields:
            return

        # F-S09: reject any column outside the allowlist before string-formatting
        # it into SQL.  Belt-and-suspenders against a bad caller passing a
        # column name like ``"id"`` or anything injection-shaped — the SET
        # clause is built by f-string interpolation on these keys.
        disallowed = set(fields) - _ALLOWED_ENRICHMENT_COLUMNS
        if disallowed:
            raise ValueError(f"Disallowed column in enrichment update: {disallowed}")

        # Build SET clauses using COALESCE so existing values are never overwritten.
        set_clauses = ", ".join(f"{col} = COALESCE(securities.{col}, :{col})" for col in fields)
        params: dict[str, object] = {"security_id": security_id, **fields}
        await self._session.execute(
            text(f"UPDATE securities SET {set_clauses}, updated_at = NOW() WHERE id = :security_id"),
            params,
        )
