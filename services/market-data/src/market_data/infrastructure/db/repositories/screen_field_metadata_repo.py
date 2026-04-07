"""Repository for the screen_field_metadata table (write path).

Used exclusively by the background ``_screen_fields_refresh_loop`` in
``app.py`` to seed and refresh the 12 static field definitions.

The read path goes through ``PgFundamentalMetricsQueryRepository`` which
implements ``get_screen_field_metadata()`` on the read (replica) session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert

from market_data.infrastructure.db.models.screen_field_metadata import ScreenFieldMetadataModel

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from market_data.domain.entities import ScreenFieldMetadata


class PgScreenFieldMetadataRepository:
    """Write-side repository for ``screen_field_metadata`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(self, fields: list[ScreenFieldMetadata], computed_at: datetime) -> None:
        """Upsert all field metadata rows in a single statement.

        Uses ``INSERT … ON CONFLICT (field_name) DO UPDATE`` so this is safe
        to call repeatedly and is idempotent.
        """
        if not fields:
            return

        rows: list[dict[str, Any]] = [
            {
                "field_name": f.name,
                "label": f.label,
                "field_type": f.field_type,
                "unit": f.unit,
                "description": f.description,
                "observed_min": f.observed_min,
                "observed_max": f.observed_max,
                "null_fraction": f.null_fraction,
                "last_computed_at": computed_at,
            }
            for f in fields
        ]

        stmt = insert(ScreenFieldMetadataModel).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["field_name"],
            set_={
                "label": stmt.excluded.label,
                "field_type": stmt.excluded.field_type,
                "unit": stmt.excluded.unit,
                "description": stmt.excluded.description,
                "observed_min": stmt.excluded.observed_min,
                "observed_max": stmt.excluded.observed_max,
                "null_fraction": stmt.excluded.null_fraction,
                "last_computed_at": stmt.excluded.last_computed_at,
            },
        )
        await self._session.execute(stmt)
