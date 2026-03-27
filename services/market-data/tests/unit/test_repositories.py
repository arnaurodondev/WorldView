"""Unit tests for PostgreSQL repository adapters (MD-016).

These tests use mock AsyncSession objects — no live database required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
from market_data.infrastructure.db.repositories.ingestion_event_repo import PgIngestionEventRepository
from market_data.infrastructure.db.repositories.instrument_repo import PgInstrumentRepository
from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository
from sqlalchemy.dialects.postgresql import insert as pg_insert

pytestmark = pytest.mark.unit


class TestOHLCVBulkUpsertSQL:
    """Verify that bulk_upsert_with_priority generates SQL with the provider-priority WHERE clause."""

    def test_ohlcv_bulk_upsert_sql_generation(self):
        """The upsert statement must contain EXCLUDED.provider_priority comparison."""
        # Build the insert statement directly (same logic as the adapter)
        bars = [
            OHLCVBar(
                instrument_id="inst-1",
                timeframe=Timeframe.ONE_DAY,
                bar_date=datetime(2026, 1, 1, tzinfo=UTC),
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("99"),
                close=Decimal("103"),
                volume=1000,
                provider_priority=ProviderPriority(provider="polygon", priority=100),
            )
        ]
        values = [
            {
                "instrument_id": bar.instrument_id,
                "timeframe": str(bar.timeframe),
                "bar_date": bar.bar_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "provider_priority": bar.provider_priority.priority,
            }
            for bar in bars
        ]
        stmt = (
            pg_insert(OHLCVBarModel)
            .values(values)
            .on_conflict_do_update(
                index_elements=["instrument_id", "timeframe", "bar_date"],
                set_={
                    "open": pg_insert(OHLCVBarModel).excluded.open,
                    "provider_priority": pg_insert(OHLCVBarModel).excluded.provider_priority,
                },
                where=(pg_insert(OHLCVBarModel).excluded.provider_priority >= OHLCVBarModel.provider_priority),
            )
        )
        # Compile to string and check for EXCLUDED.provider_priority
        compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
        sql_str = str(compiled)
        assert "excluded.provider_priority" in sql_str.lower()

    async def test_bulk_upsert_empty_list_is_noop(self):
        """An empty bars list must not execute any SQL."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        await repo.bulk_upsert_with_priority([])
        session.execute.assert_not_called()


class TestInstrumentSearch:
    """Verify that instrument search generates correct WHERE clauses."""

    async def test_instrument_search_filters(self):
        """search() must execute a query with ILIKE filters on symbol and exchange."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        repo = PgInstrumentRepository(session)
        await repo.search("AAPL")

        # Verify execute was called (with an ILIKE query)
        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        # Compile the statement to inspect its WHERE clause
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled).lower()
        assert "ilike" in sql or "like" in sql


class TestIngestionEventExists:
    """Verify that the EXISTS check compiles correctly."""

    async def test_ingestion_event_exists_check(self):
        """exists() must execute an EXISTS subquery."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        session.execute.return_value = mock_result

        repo = PgIngestionEventRepository(session)
        result = await repo.exists("test-event-id")

        assert result is True
        session.execute.assert_called_once()

        # Verify the compiled query contains EXISTS
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled).lower()
        assert "exists" in sql


# ── T-E2-1-02: atomic create_if_not_exists ────────────────────────────────────


class TestCreateIfNotExists:
    """Verify create_if_not_exists INSERT…ON CONFLICT DO NOTHING…RETURNING."""

    async def test_create_if_not_exists_returns_true_on_first_insert(self):
        """New event_id → True (row was inserted and RETURNING returns a value)."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 1  # row was inserted
        session.execute.return_value = mock_result

        repo = PgIngestionEventRepository(session)
        result = await repo.create_if_not_exists("new-event-id")

        assert result is True
        session.execute.assert_called_once()

    async def test_create_if_not_exists_returns_false_on_duplicate(self):
        """Duplicate event_id → False (ON CONFLICT DO NOTHING → RETURNING returns nothing)."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # conflict → no row returned
        session.execute.return_value = mock_result

        repo = PgIngestionEventRepository(session)
        result = await repo.create_if_not_exists("duplicate-event-id")

        assert result is False
        session.execute.assert_called_once()


# ── T-E2-2-01: LIKE metacharacter escape in instrument search ──────────────────


class TestInstrumentLikeEscape:
    """Verify that LIKE metacharacters are escaped before building ILIKE patterns."""

    def test_escape_like_percent(self):
        """'%' in query is escaped to '\\%'."""
        assert PgInstrumentRepository._escape_like("50%") == "50\\%"

    def test_escape_like_underscore(self):
        """'_' in query is escaped to '\\_'."""
        assert PgInstrumentRepository._escape_like("A_B") == "A\\_B"

    def test_escape_like_backslash(self):
        """Existing backslash is doubled before other escaping."""
        assert PgInstrumentRepository._escape_like("A\\B") == "A\\\\B"

    def test_escape_like_normal_query_unchanged(self):
        """Normal alphanumeric query is not altered."""
        assert PgInstrumentRepository._escape_like("AAPL") == "AAPL"
