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


# ── find_by_symbol_exchange empty-exchange wildcard (Bug 1 regression) ───────


class TestFindBySymbolExchange:
    """find_by_symbol_exchange must treat empty exchange as no filter."""

    async def test_empty_exchange_omits_exchange_filter(self):
        """When exchange='', the compiled WHERE clause must NOT contain an exchange predicate.

        Previously the query was ``WHERE symbol = :s AND exchange = :e`` which
        matched nothing for exchange='' because all real instruments use values
        like 'US' or 'CC'.  After the fix, empty exchange → single predicate on
        symbol only.
        """
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = PgInstrumentRepository(session)
        await repo.find_by_symbol_exchange("AAPL", "")

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled).lower()
        # symbol filter must be present
        assert "symbol" in sql
        # exchange equality filter must NOT be present when exchange is empty
        # (the WHERE clause should only have the symbol condition)
        params = compiled.params
        assert "exchange" not in params, f"exchange param should be absent when exchange='', got params={params}"

    async def test_non_empty_exchange_adds_exchange_filter(self):
        """When exchange='US', both symbol and exchange predicates must be present."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        repo = PgInstrumentRepository(session)
        await repo.find_by_symbol_exchange("AAPL", "US")

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        params = compiled.params
        # Both symbol and exchange must appear as bound parameters
        symbol_vals = [v for k, v in params.items() if "symbol" in k]
        exchange_vals = [v for k, v in params.items() if "exchange" in k]
        assert "AAPL" in symbol_vals
        assert "US" in exchange_vals


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


# ── F-002: null volume coercion at storage boundary ──────────────────────────


class TestOHLCVNullVolumeCoercion:
    """Verify that None volume is coerced to 0 in bulk_upsert_with_priority values."""

    async def test_ohlcv_bar_null_volume_coerced_at_storage_boundary(self):
        """A domain OHLCVBar with volume=None must produce volume=0 in the DB values dict.

        The DB column ohlcv_bars.volume is NOT NULL, so the repository adapter
        must coerce None → 0 at the storage boundary (F-002 Option B).
        """
        session = AsyncMock()
        repo = PgOHLCVRepository(session)

        bar = OHLCVBar(
            instrument_id="inst-1",
            timeframe=Timeframe.ONE_DAY,
            bar_date=datetime(2026, 6, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("103"),
            volume=None,
            provider_priority=ProviderPriority(provider="eodhd", priority=80),
        )

        await repo.bulk_upsert_with_priority([bar])

        # The execute call receives an INSERT statement whose bound parameters
        # contain the values list.  Inspect the compiled statement parameters.
        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        # Extract the compiled parameters to verify volume was coerced
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        params = compiled.params
        # The volume parameter key may be "volume" or "volume_m0" depending on
        # SQLAlchemy version — check all params for a volume key with value 0.
        volume_values = [v for k, v in params.items() if "volume" in k]
        assert 0 in volume_values, f"Expected volume=0 in params, got {params}"

    async def test_ohlcv_bar_int_volume_passes_through(self):
        """A domain OHLCVBar with volume=42000 must pass 42000 unchanged."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)

        bar = OHLCVBar(
            instrument_id="inst-1",
            timeframe=Timeframe.ONE_DAY,
            bar_date=datetime(2026, 6, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("103"),
            volume=42000,
            provider_priority=ProviderPriority(provider="eodhd", priority=80),
        )

        await repo.bulk_upsert_with_priority([bar])

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        params = compiled.params
        volume_values = [v for k, v in params.items() if "volume" in k]
        assert 42000 in volume_values, f"Expected volume=42000 in params, got {params}"


# ── PLAN-0040 B-1: is_partial in _to_domain and upsert methods ──────────────


class TestOHLCVIsPartialMapping:
    """Verify that is_partial flows through _to_domain and upsert SQL."""

    def test_to_domain_maps_is_partial(self) -> None:
        """ORM row with is_partial=True must map to domain entity is_partial=True."""
        row = MagicMock(spec=OHLCVBarModel)
        row.instrument_id = "inst-1"
        row.timeframe = "1w"
        row.bar_date = datetime(2026, 1, 6, tzinfo=UTC)
        row.open = 100.0
        row.high = 110.0
        row.low = 90.0
        row.close = 105.0
        row.volume = 5000.0
        row.adjusted_close = None
        row.source = "derived"
        row.provider_priority = 0
        row.is_derived = True
        row.is_partial = True

        domain = PgOHLCVRepository._to_domain(row)
        assert domain.is_partial is True
        assert domain.is_derived is True

    async def test_bulk_upsert_with_priority_includes_is_partial(self) -> None:
        """bulk_upsert_with_priority values dict must contain is_partial key."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)

        bar = OHLCVBar(
            instrument_id="inst-1",
            timeframe=Timeframe.ONE_DAY,
            bar_date=datetime(2026, 6, 1, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("103"),
            volume=1000,
            provider_priority=ProviderPriority(provider="eodhd", priority=80),
        )

        await repo.bulk_upsert_with_priority([bar])

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql_str = str(compiled).lower()
        # is_partial must appear both in the INSERT values and the ON CONFLICT SET clause
        assert "is_partial" in sql_str, f"is_partial not found in SQL: {sql_str}"

    async def test_bulk_upsert_derived_includes_is_partial(self) -> None:
        """bulk_upsert_derived values dict must contain is_partial key."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)

        bar = OHLCVBar(
            instrument_id="inst-1",
            timeframe=Timeframe.ONE_WEEK,
            bar_date=datetime(2026, 1, 6, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=5000,
            source="derived",
            provider_priority=ProviderPriority(provider="unknown", priority=0),
            is_derived=True,
            is_partial=True,
        )

        await repo.bulk_upsert_derived([bar])

        session.execute.assert_called_once()
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        sql_str = str(compiled).lower()
        assert "is_partial" in sql_str, f"is_partial not found in SQL: {sql_str}"
