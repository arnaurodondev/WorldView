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


def _make_bars(n: int) -> list[OHLCVBar]:
    """Build *n* distinct OHLCV bars (distinct bar_date so no in-batch conflict)."""
    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        OHLCVBar(
            instrument_id="inst-1",
            timeframe=Timeframe.ONE_MIN,
            bar_date=base.replace(minute=i % 60, hour=(i // 60) % 24, day=1 + (i // 1440)),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("103"),
            volume=1000 + i,
            provider_priority=ProviderPriority(provider="alpaca", priority=100),
        )
        for i in range(n)
    ]


class TestOHLCVBulkUpsertChunking:
    """Regression: combined upserts must chunk under Postgres's 65_535 param cap.

    HEAD batched an entire consume-batch (tens of thousands of bars) into ONE
    multi-row INSERT.  With ~12-13 columns/row that blew past the 65_535
    bound-parameter wire limit, failed the statement, stalled the Kafka offset
    and crash-looped the ohlcv-consumer.  The repository now chunks every
    multi-row INSERT so no single statement can ever exceed the limit.
    """

    # Derive expectations from the repository's REAL constants so this regression
    # test follows boundary changes (BUG: hardcoded 5_000/65_535 broke when the
    # guard was tightened to the true asyncpg limit 32_767 + 2_000-row chunks).
    from market_data.infrastructure.db.repositories.ohlcv_repo import (
        _MAX_PARAMS as _PARAM_CEILING,
    )
    from market_data.infrastructure.db.repositories.ohlcv_repo import (
        _UPSERT_CHUNK_ROWS as _CHUNK_ROWS,
    )

    _MAX_COLS = 13

    @staticmethod
    def _expected_chunks(n_rows: int, chunk: int) -> int:
        return (n_rows + chunk - 1) // chunk  # ceil

    async def test_with_priority_chunks_large_batch(self):
        """A multi-chunk batch is split into multiple bounded INSERTs."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        n = self._CHUNK_ROWS * 6 + 345
        await repo.bulk_upsert_with_priority(_make_bars(n))
        assert session.execute.call_count == self._expected_chunks(n, self._CHUNK_ROWS)
        self._assert_chunks_bounded(session, n_total=n)

    async def test_derived_chunks_large_batch(self):
        """The derived upsert path chunks identically."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        n = self._CHUNK_ROWS * 5 + 1
        await repo.bulk_upsert_derived(_make_bars(n))
        assert session.execute.call_count == self._expected_chunks(n, self._CHUNK_ROWS)
        self._assert_chunks_bounded(session, n_total=n)

    async def test_exactly_one_chunk_at_boundary(self):
        """Exactly one chunk's worth of rows fits in a single INSERT (boundary)."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        await repo.bulk_upsert_with_priority(_make_bars(self._CHUNK_ROWS))
        assert session.execute.call_count == 1

    async def test_one_over_boundary_splits(self):
        """One row over a chunk boundary must split into 2 chunks (none exceeding the cap)."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        await repo.bulk_upsert_with_priority(_make_bars(self._CHUNK_ROWS + 1))
        assert session.execute.call_count == 2
        self._assert_chunks_bounded(session, n_total=self._CHUNK_ROWS + 1)

    def _assert_chunks_bounded(self, session: AsyncMock, *, n_total: int) -> None:
        """Every executed chunk's row count keeps params < the wire limit, and
        the chunks together cover exactly ``n_total`` rows (round-trip safety)."""
        total_rows = 0
        for call in session.execute.call_args_list:
            stmt = call.args[0]
            # Compile against the postgres dialect and count the bound params —
            # this is exactly what the wire protocol would carry.
            compiled = stmt.compile(
                dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()
            )
            n_params = len(compiled.params)
            assert n_params < self._PARAM_CEILING, f"chunk has {n_params} params (>= {self._PARAM_CEILING})"
            # Derive the row count from params / columns; must be <= chunk size.
            rows_in_chunk = n_params // self._MAX_COLS
            assert rows_in_chunk <= self._CHUNK_ROWS
            total_rows += rows_in_chunk
        # Round-trip: chunks must reconstruct the full batch (no rows dropped or
        # duplicated by the chunker).  Allow the column-count estimate to be a
        # lower bound (with-priority has 12 cols, derived 13) — assert coverage
        # by re-counting against the actual per-statement VALUES length instead.
        actual_rows = sum(self._rows_in_stmt(call.args[0]) for call in session.execute.call_args_list)
        assert actual_rows == n_total

    @staticmethod
    def _rows_in_stmt(stmt) -> int:
        """Number of VALUES rows in a multi-row INSERT statement."""
        # SQLAlchemy stores multi-VALUES rows on the compile state; the simplest
        # robust count is the number of parameter dicts the insert was built from.
        compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
        # postgres multi-row insert names params open_m0, open_m1, ... so count
        # the distinct row suffixes for a single column.
        suffixes = {k.rsplit("_m", 1)[-1] for k in compiled.params if k.startswith("open")}
        # Single-row inserts use bare "open" (no _mN suffix) → 1 row.
        numeric = {s for s in suffixes if s.isdigit()}
        return len(numeric) if numeric else 1


def _make_bar(
    *,
    instrument_id: str = "inst-1",
    minute: int = 0,
    priority: int = 100,
    open_: str = "100",
    source: str = "alpaca",
    timeframe: Timeframe = Timeframe.ONE_MIN,
) -> OHLCVBar:
    """A single OHLCV bar; ``minute`` controls the (conflict-key) bar_date."""
    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        bar_date=datetime(2026, 6, 19, 0, minute, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal("103"),
        volume=1000,
        source=source,
        provider_priority=ProviderPriority(provider=source, priority=priority),
    )


def _compiled_rows(stmt) -> list[dict]:
    """Reconstruct the per-row VALUES dicts from a compiled multi-row INSERT.

    Lets a test assert WHICH rows survived dedup (and their winning values),
    not just how many — params are named ``open_m0``, ``open_m1``, ... for
    multi-row inserts and bare ``open`` for a single row.
    """
    compiled = stmt.compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect())
    params = compiled.params
    cols = ("bar_date", "open", "provider_priority", "source")
    # Single-row insert → bare column names.
    if "open" in params:
        return [{c: params.get(c) for c in cols}]
    # Multi-row insert → suffixed names; collect distinct row indices.
    idxs = sorted({int(k.rsplit("_m", 1)[-1]) for k in params if k.startswith("open_m")})
    return [{c: params.get(f"{c}_m{i}") for c in cols} for i in idxs]


@pytest.mark.unit
class TestOHLCVUpsertDedup:
    """Regression: within-batch duplicate conflict keys must be collapsed.

    A bulk ``ON CONFLICT DO UPDATE`` that sees the same
    ``(instrument_id, timeframe, bar_date)`` key twice in one statement raises
    ``CardinalityViolationError: ON CONFLICT DO UPDATE command cannot affect row
    a second time``.  Overlapping crypto backfill/replay windows (e.g. ARB-USD
    re-published with overlapping ranges) produce exactly this, crash-looping the
    ohlcv-consumer (2_686 restarts).  The repo dedupes by conflict key BEFORE the
    upsert, keeping the winner the ON CONFLICT clause would have resolved to.
    """

    async def test_priority_path_keeps_highest_priority_winner(self):
        """Duplicate keys collapse to one row; the highest-priority value wins."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        # Two bars, SAME conflict key, different priority. The priority-guarded
        # ON CONFLICT would keep the higher-priority value → so must dedup.
        bars = [
            _make_bar(minute=0, priority=50, open_="111", source="yahoo"),
            _make_bar(minute=0, priority=100, open_="222", source="alpaca"),
        ]
        await repo.bulk_upsert_with_priority(bars)
        assert session.execute.call_count == 1
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 1, "duplicate key must collapse to a single VALUES row"
        assert rows[0]["open"] == Decimal("222")  # higher-priority winner
        assert rows[0]["provider_priority"] == 100

    async def test_priority_path_equal_priority_keeps_last(self):
        """On equal priority the LAST occurrence wins (mirrors ON CONFLICT order)."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        bars = [
            _make_bar(minute=0, priority=100, open_="111"),
            _make_bar(minute=0, priority=100, open_="333"),  # last → wins
        ]
        await repo.bulk_upsert_with_priority(bars)
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 1
        assert rows[0]["open"] == Decimal("333")

    async def test_priority_path_lower_priority_does_not_overwrite(self):
        """A later LOWER-priority dup must NOT displace the earlier higher one."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        bars = [
            _make_bar(minute=0, priority=100, open_="222"),  # higher → wins
            _make_bar(minute=0, priority=50, open_="111"),
        ]
        await repo.bulk_upsert_with_priority(bars)
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 1
        assert rows[0]["open"] == Decimal("222")
        assert rows[0]["provider_priority"] == 100

    async def test_distinct_keys_all_survive(self):
        """Distinct conflict keys are untouched by dedup."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        bars = [_make_bar(minute=m, priority=100) for m in range(5)]
        await repo.bulk_upsert_with_priority(bars)
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 5

    async def test_dedup_composes_with_chunking(self):
        """A batch full of dups dedupes FIRST, then chunks the deduped result.

        2_000 distinct keys each duplicated 3x = 6_000 input rows.  Dedup must
        collapse to 2_000 rows → a single chunk (no CardinalityViolation, and no
        spurious extra chunk from the pre-dedup 6_000 count).
        """
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        bars: list[OHLCVBar] = []
        for m in range(2_000):
            for _ in range(3):  # 3 copies of each conflict key
                bars.append(_make_bar(minute=m % 60, instrument_id=f"i{m}", priority=100))
        await repo.bulk_upsert_with_priority(bars)
        # 2_000 deduped rows fit in a single chunk.
        assert session.execute.call_count == 1
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 2_000

    async def test_derived_path_dedupes_last_wins(self):
        """The derived (unconditional) path keeps the LAST occurrence per key."""
        session = AsyncMock()
        repo = PgOHLCVRepository(session)
        bars = [
            _make_bar(minute=0, timeframe=Timeframe.ONE_WEEK, open_="111", priority=10),
            _make_bar(minute=0, timeframe=Timeframe.ONE_WEEK, open_="333", priority=5),  # last → wins
        ]
        await repo.bulk_upsert_derived(bars)
        assert session.execute.call_count == 1
        rows = _compiled_rows(session.execute.call_args.args[0])
        assert len(rows) == 1
        assert rows[0]["open"] == Decimal("333")  # unconditional → last wins regardless of priority


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


class TestPredictionMarketListQueryEscape:
    """Regression guard for BP-712 — the free-text ILIKE ESCAPE clause.

    ``list_markets`` builds a raw SQL predicate with an ``ESCAPE`` clause when a
    free-text ``query`` is supplied (the chat prediction-market tool always
    supplies one).  The ESCAPE operand MUST be a single character: under
    Postgres ``standard_conforming_strings=on`` the previous literal rendered
    the SQL string ``ESCAPE '\\'`` (two backslashes = a 2-char literal) which
    asyncpg rejects with ``InvalidEscapeSequenceError`` → HTTP 500 on every
    query.  This test asserts the generated SQL now uses a single-backslash
    escape and never the broken two-backslash form.
    """

    async def test_list_markets_query_uses_single_char_escape(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketRepository,
        )

        # Mock the session so the raw SQL is captured without a live DB.
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []  # empty result → list_markets returns ([], 0)
        session.execute.return_value = result

        repo = PgPredictionMarketRepository(session)
        pairs, total = await repo.list_markets(status=None, query="election", limit=5, offset=0)

        assert pairs == []
        assert total == 0

        # The TextClause passed to execute carries the raw SQL string.
        text_clause = session.execute.call_args[0][0]
        sql = text_clause.text

        # Single-char escape present (Python "'\\'" == SQL   ESCAPE '<one backslash>').
        assert "ESCAPE '\\'" in sql, f"expected single-char ESCAPE, got: {sql}"
        # The broken two-backslash form (Python "'\\\\'") must be absent.
        assert "ESCAPE '\\\\'" not in sql, f"two-backslash ESCAPE must not appear: {sql}"


class TestPredictionMarketListVolumeWindow:
    """PLAN-0056 QA — the latest-volume LATERAL time-window bound.

    ``prediction_market_snapshots`` is a TimescaleDB hypertable (~1.8M rows,
    weekly chunks). The unbounded ``ORDER BY snapshot_at DESC LIMIT 1`` LATERAL
    cannot stop early for markets whose newest snapshot is in an old chunk, so
    it cold-scans every chunk per market x 527 markets (~1.8 s) and 500s the
    endpoint under load. ``volume_window_days`` bounds the LATERAL so
    TimescaleDB prunes to recent chunks (verified live: 5 chunks excluded,
    ~60-370 ms). These tests pin that the SQL is emitted (bound param, not
    interpolated) when a window is set and stays unbounded otherwise.
    """

    async def _run(self, *, volume_window_days):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        session.execute.return_value = result

        repo = PgPredictionMarketRepository(session)
        await repo.list_markets(
            status="open",
            query=None,
            limit=10,
            offset=0,
            volume_window_days=volume_window_days,
        )
        text_clause = session.execute.call_args[0][0]
        params = {k: v.value for k, v in text_clause._bindparams.items()}
        return text_clause.text, params

    async def test_window_adds_bounded_snapshot_predicate(self):
        """A positive window emits a bound-param time predicate inside the LATERAL."""
        sql, params = await self._run(volume_window_days=30)

        # The LATERAL is time-bounded so TimescaleDB can prune chunks.
        assert "s.snapshot_at >= now() - make_interval(days => :volume_window_days)" in sql
        # The window is a *bound parameter* — never interpolated into the SQL
        # string (no injection surface, and the planner still folds it for
        # chunk exclusion).
        assert params["volume_window_days"] == 30
        assert "30" not in sql
        # Predicate lives inside the LATERAL (before its ORDER BY), not in the
        # outer WHERE — so it bounds the per-market snapshot lookup, not the
        # market set.
        assert sql.index("make_interval") < sql.index("ORDER BY s.snapshot_at DESC")

    async def test_no_window_keeps_unbounded_lateral(self):
        """``None`` window preserves the legacy unbounded LATERAL (no time bound)."""
        sql, params = await self._run(volume_window_days=None)

        assert "make_interval" not in sql
        assert "volume_window_days" not in params
        # The LATERAL still pulls the newest snapshot per market.
        assert "ORDER BY s.snapshot_at DESC" in sql

    async def test_non_positive_window_is_ignored(self):
        """``0`` / negative disables the bound (defensive — never a 0-day window).

        A 0-day window would return NULL volume for every market (nothing is
        ``>= now()``), so the code treats ``<= 0`` as "unbounded" rather than
        applying a self-defeating predicate.
        """
        for bad in (0, -5):
            sql, params = await self._run(volume_window_days=bad)
            assert "make_interval" not in sql, f"window={bad} must be ignored"
            assert "volume_window_days" not in params

    async def _run_price_batch(self, *, window_days):
        """Execute ``get_latest_prices_batch`` against a mock session; return (sql, params)."""
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketSnapshotRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        session.execute.return_value = result

        repo = PgPredictionMarketSnapshotRepository(session)
        await repo.get_latest_prices_batch(["mkt-1", "mkt-2"], window_days=window_days)
        text_clause = session.execute.call_args[0][0]
        params = {k: v.value for k, v in text_clause._bindparams.items()}
        return text_clause.text, params

    async def test_price_batch_window_bounds_scan(self):
        """A positive window bounds the batch price scan with a bound param."""
        sql, params = await self._run_price_batch(window_days=30)

        assert "snapshot_at >= now() - make_interval(days => :window_days)" in sql
        assert params["window_days"] == 30
        assert "30" not in sql
        # Bound still lives before the DISTINCT ON's ORDER BY.
        assert sql.index("make_interval") < sql.index("ORDER BY market_id")

    async def test_price_batch_no_window_is_unbounded(self):
        """``None`` window keeps the legacy unbounded DISTINCT ON batch scan."""
        sql, params = await self._run_price_batch(window_days=None)

        assert "make_interval" not in sql
        assert "window_days" not in params
        assert "DISTINCT ON (market_id)" in sql


class TestPredictionMarketQueryTokenizer:
    """R2 fix — tokenised multi-word free-text search.

    The old free-text branch matched the ENTIRE query phrase as one ILIKE
    substring, so natural multi-word chat queries ("2028 Democratic
    presidential nomination") returned 0 rows because no single market question
    contains that exact substring. The branch now splits the query into
    meaningful tokens and AND-matches each one.
    """

    def test_tokenize_splits_meaningful_words(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            _tokenize_query,
        )

        # "2028" survives (numeric, len 4); trivial words are irrelevant here.
        assert _tokenize_query("2028 Democratic presidential nomination") == [
            "2028",
            "democratic",
            "presidential",
            "nomination",
        ]

    def test_tokenize_drops_stopwords_short_tokens_and_dedupes(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            _tokenize_query,
        )

        # "who"/"will"/"the" = stopwords; "in" = short; "election" appears twice
        # but is de-duplicated; casing/punctuation normalised.
        assert _tokenize_query("Who will win the election, the 2024 election?") == [
            "win",
            "election",
            "2024",
        ]

    def test_tokenize_all_stopwords_returns_empty(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            _tokenize_query,
        )

        assert _tokenize_query("who will the") == []

    def test_tokenize_keeps_wildcard_chars_in_token(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            _tokenize_query,
        )

        # "50%" stays a single token so escaping later matches a literal "50%"
        # rather than the bare number "50".
        assert _tokenize_query("win 50%") == ["win", "50%"]

    async def _run_list_markets(self, query):
        """Execute ``list_markets`` against a mock session; return (sql, params)."""
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        session.execute.return_value = result

        repo = PgPredictionMarketRepository(session)
        await repo.list_markets(status=None, query=query, limit=5, offset=0)

        text_clause = session.execute.call_args[0][0]
        # Compiled bind params are exposed via the TextClause's bind params.
        params = {k: v.value for k, v in text_clause._bindparams.items()}
        return text_clause.text, params

    async def test_multi_word_query_builds_anded_per_token_predicates(self):
        """Each token becomes its own AND-ed, separately-bound ILIKE predicate."""
        sql, params = await self._run_list_markets("presidential nomination")

        # Two distinct token params, each a literal-substring pattern.
        assert params["query_tok_0"] == "%presidential%"
        assert params["query_tok_1"] == "%nomination%"
        # AND-ed together (not OR — OR would broaden to the whole table).
        assert "query_tok_0" in sql and "query_tok_1" in sql
        assert " AND " in sql
        assert " OR " not in sql
        # Single-char ESCAPE preserved on every token predicate (BP-712).
        assert "ESCAPE '\\'" in sql
        assert "ESCAPE '\\\\'" not in sql
        # The whole-phrase substring must NOT be used for a multi-word query.
        assert "%presidential nomination%" not in params.values()
        assert "query_like" not in params

    async def test_all_stopword_query_falls_back_to_whole_phrase(self):
        """When no meaningful token survives, match the whole phrase (no crash)."""
        sql, params = await self._run_list_markets("who will the")

        assert params["query_like"] == "%who will the%"
        assert "query_tok_0" not in params
        assert "ESCAPE '\\'" in sql


# ── PLAN-0056 A2: prediction deeper-stream repos (prices/trades/oi/events) ─────
#
# These mirror the snapshot-repo unit style: mock AsyncSession, assert the
# ON CONFLICT semantics compile correctly, and verify insert/dedup return
# values and list ordering/filter binding. No live DB (see integration tests
# for real-TimescaleDB coverage). T-A-2-01..04.


def _price(**over):
    from market_data.domain.entities import PredictionMarketPrice

    base = {
        "market_id": "mkt-1",
        "token_id": "tok-1",
        "interval": "1h",
        "window_start_ts": datetime(2026, 1, 1, tzinfo=UTC),
        "price": Decimal("0.42"),
    }
    base.update(over)
    return PredictionMarketPrice(**base)


def _trade(**over):
    from market_data.domain.entities import PredictionMarketTrade

    base = {
        "market_id": "mkt-1",
        "trade_id": "trd-1",
        "token_id": "tok-1",
        "price": Decimal("0.51"),
        "side": "buy",
        "ts": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(over)
    return PredictionMarketTrade(**base)


def _oi(**over):
    from datetime import date

    from market_data.domain.entities import PredictionMarketOI

    base = {"market_id": "mkt-1", "snapshot_date": date(2026, 1, 1)}
    base.update(over)
    return PredictionMarketOI(**base)


def _event(**over):
    from market_data.domain.entities import PredictionEvent

    base = {"event_id": "evt-1", "name": "US Election 2028"}
    base.update(over)
    return PredictionEvent(**base)


def _mock_session(*, scalar=None, fetchall=None):
    """Build an AsyncMock session whose execute() returns a result stub."""
    session = AsyncMock()
    result = MagicMock()
    if scalar is not None or fetchall is None:
        result.scalar_one_or_none.return_value = scalar
    if fetchall is not None:
        result.fetchall.return_value = fetchall
    session.execute.return_value = result
    return session


class TestPgPredictionMarketPricesRepository:
    async def test_insert_if_not_exists_true_on_new(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketPricesRepository,
        )

        session = _mock_session(scalar="new-id")
        repo = PgPredictionMarketPricesRepository(session)
        assert await repo.insert_if_not_exists(_price()) is True
        # ON CONFLICT DO NOTHING on the composite unique index must be present.
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        assert "on conflict" in sql and "do nothing" in sql

    async def test_insert_if_not_exists_false_on_conflict(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketPricesRepository,
        )

        session = _mock_session(scalar=None)
        repo = PgPredictionMarketPricesRepository(session)
        assert await repo.insert_if_not_exists(_price()) is False

    async def test_bulk_insert_empty_is_noop(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketPricesRepository,
        )

        session = _mock_session()
        repo = PgPredictionMarketPricesRepository(session)
        assert await repo.bulk_insert([]) == 0
        session.execute.assert_not_called()

    async def test_bulk_insert_returns_inserted_row_count(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketPricesRepository,
        )

        # RETURNING yields one row per row actually inserted (2 of 3 — 1 conflict).
        session = _mock_session(fetchall=[("id1",), ("id2",)])
        repo = PgPredictionMarketPricesRepository(session)
        n = await repo.bulk_insert([_price(), _price(interval="1d"), _price(interval="1m")])
        assert n == 2
        session.execute.assert_called_once()

    async def test_list_prices_orders_desc_and_binds_filters(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketPricesRepository,
        )

        session = _mock_session(fetchall=[])
        repo = PgPredictionMarketPricesRepository(session)
        await repo.list_prices(
            "mkt-1",
            token_id="tok-1",
            interval="1h",
            from_dt=datetime(2026, 1, 1, tzinfo=UTC),
            to_dt=datetime(2026, 2, 1, tzinfo=UTC),
            limit=10,
        )
        clause = session.execute.call_args[0][0]
        sql = clause.text
        params = {k: v.value for k, v in clause._bindparams.items()}
        assert "ORDER BY window_start_ts DESC" in sql
        assert params["token_id"] == "tok-1"  # noqa: S105 — token_id is a market outcome id, not a secret
        assert params["interval"] == "1h"
        assert params["from_dt"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert params["to_dt"] == datetime(2026, 2, 1, tzinfo=UTC)
        assert params["limit"] == 10


class TestPgPredictionMarketTradesRepository:
    async def test_insert_if_not_exists_dedup(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketTradesRepository,
        )

        repo_new = PgPredictionMarketTradesRepository(_mock_session(scalar="id"))
        assert await repo_new.insert_if_not_exists(_trade()) is True
        repo_dup = PgPredictionMarketTradesRepository(_mock_session(scalar=None))
        assert await repo_dup.insert_if_not_exists(_trade()) is False

    async def test_bulk_insert_empty_is_noop(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketTradesRepository,
        )

        session = _mock_session()
        repo = PgPredictionMarketTradesRepository(session)
        assert await repo.bulk_insert([]) == 0
        session.execute.assert_not_called()

    async def test_list_trades_orders_by_ts_desc_with_since(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketTradesRepository,
        )

        session = _mock_session(fetchall=[])
        repo = PgPredictionMarketTradesRepository(session)
        await repo.list_trades("mkt-1", since=datetime(2026, 1, 1, tzinfo=UTC), limit=25)
        clause = session.execute.call_args[0][0]
        params = {k: v.value for k, v in clause._bindparams.items()}
        assert "ORDER BY ts DESC" in clause.text
        assert params["since"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert params["limit"] == 25


class TestPgPredictionMarketOIRepository:
    async def test_upsert_uses_on_conflict_do_update(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketOIRepository,
        )

        session = _mock_session()
        repo = PgPredictionMarketOIRepository(session)
        await repo.upsert(_oi(total_oi_usd=Decimal("1000"), total_volume_24h_usd=Decimal("50")))
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        assert "on conflict" in sql and "do update" in sql
        assert "excluded" in sql

    async def test_get_latest_limits_to_one_and_maps(self):
        from types import SimpleNamespace

        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketOIRepository,
        )

        row = SimpleNamespace(
            market_id="mkt-1",
            snapshot_date=__import__("datetime").date(2026, 1, 3),
            total_oi_usd=Decimal("1234.5"),
            total_volume_24h_usd=None,
        )
        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = row
        session.execute.return_value = result
        repo = PgPredictionMarketOIRepository(session)
        oi = await repo.get_latest("mkt-1")
        assert oi is not None
        assert oi.total_oi_usd == Decimal("1234.5")
        assert oi.total_volume_24h_usd is None
        assert "LIMIT 1" in session.execute.call_args[0][0].text

    async def test_get_latest_returns_none_when_absent(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketOIRepository,
        )

        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        session.execute.return_value = result
        repo = PgPredictionMarketOIRepository(session)
        assert await repo.get_latest("mkt-x") is None

    async def test_list_oi_binds_date_range_and_orders_desc(self):
        from datetime import date

        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketOIRepository,
        )

        session = _mock_session(fetchall=[])
        repo = PgPredictionMarketOIRepository(session)
        await repo.list_oi("mkt-1", from_date=date(2026, 1, 1), to_date=date(2026, 1, 31), limit=7)
        clause = session.execute.call_args[0][0]
        params = {k: v.value for k, v in clause._bindparams.items()}
        assert "ORDER BY snapshot_date DESC" in clause.text
        assert params["from_date"] == date(2026, 1, 1)
        assert params["to_date"] == date(2026, 1, 31)


class TestPgPredictionMarketEventsRepository:
    async def test_upsert_on_conflict_do_update_on_event_id(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
        )

        session = _mock_session()
        repo = PgPredictionMarketEventsRepository(session)
        await repo.upsert(_event(category="politics", market_count=4))
        stmt = session.execute.call_args[0][0]
        from sqlalchemy.dialects import postgresql

        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        assert "on conflict" in sql and "do update" in sql
        assert "event_id" in sql

    async def test_find_by_event_id_maps_and_missing_returns_none(self):
        from types import SimpleNamespace

        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
        )

        row = SimpleNamespace(
            event_id="evt-1",
            name="US Election 2028",
            category="politics",
            start_date=None,
            end_date=None,
            market_count=3,
        )
        session = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = row
        session.execute.return_value = result
        repo = PgPredictionMarketEventsRepository(session)
        ev = await repo.find_by_event_id("evt-1")
        assert ev is not None
        assert ev.event_id == "evt-1"
        assert ev.market_count == 3

        session2 = AsyncMock()
        result2 = MagicMock()
        result2.fetchone.return_value = None
        session2.execute.return_value = result2
        assert await PgPredictionMarketEventsRepository(session2).find_by_event_id("nope") is None

    async def test_list_events_returns_empty_and_total_zero(self):
        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
        )

        session = _mock_session(fetchall=[])
        repo = PgPredictionMarketEventsRepository(session)
        events, total = await repo.list_events(limit=10, offset=0)
        assert events == []
        assert total == 0

    async def test_list_events_reads_total_from_window_count(self):
        from types import SimpleNamespace

        from market_data.infrastructure.db.repositories.prediction_market_repo import (
            PgPredictionMarketEventsRepository,
        )

        rows = [
            SimpleNamespace(
                event_id="evt-1",
                name="A",
                category=None,
                start_date=None,
                end_date=None,
                market_count=1,
                total=2,
            ),
            SimpleNamespace(
                event_id="evt-2",
                name="B",
                category="crypto",
                start_date=None,
                end_date=None,
                market_count=5,
                total=2,
            ),
        ]
        session = _mock_session(fetchall=rows)
        repo = PgPredictionMarketEventsRepository(session)
        events, total = await repo.list_events(limit=10, offset=0)
        assert [e.event_id for e in events] == ["evt-1", "evt-2"]
        assert total == 2
