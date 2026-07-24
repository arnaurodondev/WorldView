"""End-to-end DB test for migrations 046 (data repair) + 047 (prevention guard).

WHY THIS TEST EXISTS (NFLX-duplicate-instrument incident, 2026-07):

Migration 046 merges duplicate ``instruments`` rows sharing the same symbol
into one canonical row, reassigning FK-referencing child rows first so no
real data is lost. Migration 047 then adds a partial unique index that
rejects a second placeholder-exchange row per symbol going forward.

This test runs BOTH migrations against a REAL disposable Postgres
(testcontainers — the same mechanism this service's other integration tests
use in lieu of a manually-managed docker-compose Postgres) with a seeded
fixture that mimics the real NFLX incident:
  * an ``exchange=''`` placeholder row with STALE data in several child
    tables (fundamentals section, snapshot, quote, fundamental_metric)
  * a real ``exchange='US'`` row with FRESH/overlapping data in the same
    tables

and asserts:
  1. exactly one ``instruments`` row survives for the symbol, and it is the
     real-exchange row;
  2. the placeholder's UNIQUE child row (a fundamentals period NOT present
     on the canonical row) was reassigned to the canonical row, not lost;
  3. the placeholder's CONFLICTING child rows (same natural key already
     present on the canonical row) were dropped rather than colliding or
     duplicating;
  4. migration 047's partial unique index then rejects a second
     placeholder-exchange insert for the same symbol.

Unlike the shared ``tests/integration/conftest.py`` fixtures (which run
Alembic to ``head`` ONCE per session, i.e. before any test-seeded duplicate
data exists — the merge DO block would find nothing to do), this test needs
to insert duplicate rows BEFORE the merge migration runs. It therefore spins
up its own disposable container, drives Alembic to revision "045", seeds the
fixture, then upgrades through "047" — all in SYNC fixture setup (Alembic's
``env.py`` runs migrations via ``asyncio.run()``, which cannot be called from
inside a running event loop, so none of this may happen inside an ``async
def test`` body under pytest-asyncio; only the final read-only assertions
run there). This genuinely exercises migration 046's merge logic against
seeded duplicate data — the "test the migration locally on a seeded
orphan+canonical fixture" step required before this migration is ever run
against production.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_SERVICE_DIR = Path(__file__).resolve().parent.parent.parent


def _new_uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def _pre_merge_container() -> Iterator[object]:
    """A dedicated (NOT shared with other integration tests) TimescaleDB container.

    Isolated from the session-scoped ``pg_container`` in ``conftest.py``
    because this test needs to control the Alembic revision precisely
    (stop at 045, seed duplicates, then upgrade through 047) rather than
    starting from an already-fully-migrated, empty database.
    """
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        dbname="market_data_db",
        username="postgres",
        password="postgres",
    ) as container:
        yield container


def _alembic_config(asyncpg_url: str):
    from alembic.config import Config

    os.environ["ALEMBIC_URL"] = asyncpg_url
    cfg = Config(str(_SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVICE_DIR / "alembic"))
    return cfg


async def _seed_duplicate_fixture(asyncpg_url: str, ids: dict[str, str]) -> None:
    """Seed a placeholder/canonical NFLX duplicate pair + representative child rows."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(asyncpg_url, echo=False)
    async with engine.begin() as conn:
        # One shared Security (mirrors the real incident: same company).
        await conn.execute(
            text("INSERT INTO securities (id, name) VALUES (:id, 'Netflix Inc')"),
            {"id": ids["security"]},
        )

        # The STALE placeholder row (exchange='', created first).
        await conn.execute(
            text(
                "INSERT INTO instruments "
                "(id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, "
                " last_fundamentals_ingest_at, created_at) "
                "VALUES (:id, :sec, 'NFLX', '', false, false, true, '2026-03-31T00:00:00Z', "
                "'2026-07-15T00:00:00Z')"
            ),
            {"id": ids["placeholder"], "sec": ids["security"]},
        )
        # The FRESH canonical row (exchange='US', created second).
        await conn.execute(
            text(
                "INSERT INTO instruments "
                "(id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, "
                " last_fundamentals_ingest_at, created_at) "
                "VALUES (:id, :sec, 'NFLX', 'US', true, true, true, '2026-07-22T00:00:00Z', "
                "'2026-07-16T00:00:00Z')"
            ),
            {"id": ids["canonical"], "sec": ids["security"]},
        )

        # A fundamentals-section row UNIQUE to the placeholder (a period the
        # canonical row does NOT have yet) — MUST be reassigned, not lost.
        await conn.execute(
            text(
                "INSERT INTO income_statements (id, instrument_id, period_type, period_end_date, data) "
                "VALUES (:id, :iid, 'quarterly', '2025-12-31', '{}'::jsonb)"
            ),
            {"id": _new_uuid(), "iid": ids["placeholder"]},
        )
        # A fundamentals-section row that CONFLICTS (same period already on
        # canonical) — MUST be dropped, not duplicated. Bound as a
        # timezone-AWARE ``datetime`` (explicit ``tzinfo=UTC``), not a bare
        # ``datetime.date``: asyncpg encodes a bare ``date`` against a
        # ``timestamptz`` column using the client's LOCAL timezone, silently
        # shifting midnight to the previous day in any timezone behind UTC.
        # A ``datetime`` that already carries ``tzinfo=UTC`` is unambiguous
        # and round-trips exactly (also avoids asyncpg's stricter type
        # requirement that rejects a plain ``str`` bound against a
        # ``timestamptz`` param, which a SQL-side ``CAST`` does not relax).
        conflicting_period = datetime(2026, 3, 31, tzinfo=UTC)
        await conn.execute(
            text(
                "INSERT INTO income_statements (id, instrument_id, period_type, period_end_date, data) "
                "VALUES (:id, :iid, 'quarterly', :period, '{\"stale\": true}'::jsonb)"
            ),
            {"id": _new_uuid(), "iid": ids["placeholder"], "period": conflicting_period},
        )
        await conn.execute(
            text(
                "INSERT INTO income_statements (id, instrument_id, period_type, period_end_date, data) "
                "VALUES (:id, :iid, 'quarterly', :period, '{\"fresh\": true}'::jsonb)"
            ),
            {"id": _new_uuid(), "iid": ids["canonical"], "period": conflicting_period},
        )

        # instrument_fundamentals_snapshot: single-row-per-instrument table.
        # Only the placeholder has one — MUST be reassigned to the canonical
        # row (which has none yet).
        await conn.execute(
            text("INSERT INTO instrument_fundamentals_snapshot (instrument_id, eps_ttm) VALUES (:iid, 1.23)"),
            {"iid": ids["placeholder"]},
        )

        # quotes: single-row-per-instrument, BOTH have one — placeholder's
        # MUST be dropped (canonical's is fresher / kept as-is).
        await conn.execute(
            text("INSERT INTO quotes (instrument_id, last) VALUES (:iid, 100.00)"),
            {"iid": ids["placeholder"]},
        )
        await conn.execute(
            text("INSERT INTO quotes (instrument_id, last) VALUES (:iid, 500.00)"),
            {"iid": ids["canonical"]},
        )

        # fundamental_metrics: natural key (instrument_id, as_of_date, metric,
        # period_type) — placeholder has a metric the canonical lacks.
        await conn.execute(
            text(
                "INSERT INTO fundamental_metrics (id, instrument_id, as_of_date, metric, value_numeric) "
                "VALUES (:id, :iid, '2025-12-31', 'eps', 1.23)"
            ),
            {"id": _new_uuid(), "iid": ids["placeholder"]},
        )

        # ── ohlcv_bars: TimescaleDB hypertable, PK (instrument_id, timeframe,
        # bar_date). The migration reassigns instrument_id only (never the
        # partition key bar_date). Placeholder has one UNIQUE bar (reassign) and
        # one CONFLICTING bar (same PK on canonical → drop the loser's).
        bar_unique = datetime(2026, 3, 30, tzinfo=UTC)
        bar_conflict = datetime(2026, 7, 21, tzinfo=UTC)
        for iid, bar_date, close in (
            (ids["placeholder"], bar_unique, 100.0),  # unique to placeholder → reassign
            (ids["placeholder"], bar_conflict, 111.0),  # conflicts with canonical → drop
            (ids["canonical"], bar_conflict, 555.0),  # canonical's winner bar → kept
        ):
            await conn.execute(
                text(
                    "INSERT INTO ohlcv_bars (instrument_id, timeframe, bar_date, open, high, low, close, volume) "
                    "VALUES (:iid, '1d', :bd, :c, :c, :c, :c, 0)"
                ),
                {"iid": iid, "bd": bar_date, "c": close},
            )

        # ── insider_transactions: natural key (instrument_id, filer_name,
        # transaction_date, transaction_type, shares) — placeholder-unique row.
        await conn.execute(
            text(
                "INSERT INTO insider_transactions "
                "(id, instrument_id, filer_name, transaction_date, transaction_type, shares) "
                "VALUES (:id, :iid, 'Jane CEO', '2026-03-15', 'BUY', 100)"
            ),
            {"id": _new_uuid(), "iid": ids["placeholder"]},
        )

        # ── earnings_calendar: unique (instrument_id, report_date) — placeholder-only.
        await conn.execute(
            text("INSERT INTO earnings_calendar (id, instrument_id, report_date) VALUES (:id, :iid, '2026-04-20')"),
            {"id": _new_uuid(), "iid": ids["placeholder"]},
        )

        # ── company_profiles: unique on instrument_id — placeholder-only → reassign.
        await conn.execute(
            text("INSERT INTO company_profiles (id, instrument_id, cik) VALUES (:id, :iid, '0001065280')"),
            {"id": _new_uuid(), "iid": ids["placeholder"]},
        )

        # ── THIRD NFLX loser row (exchange='CC', oldest fundamentals) — proves
        # the 3+-duplicate multi-loser path merges every loser into ONE winner.
        await conn.execute(
            text(
                "INSERT INTO instruments "
                "(id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, "
                " last_fundamentals_ingest_at, created_at) "
                "VALUES (:id, :sec, 'NFLX', 'CC', false, false, true, '2026-01-31T00:00:00Z', "
                "'2026-07-14T00:00:00Z')"
            ),
            {"id": ids["third"], "sec": ids["security"]},
        )
        # A fundamentals row unique to the third loser (different period again).
        await conn.execute(
            text(
                "INSERT INTO income_statements (id, instrument_id, period_type, period_end_date, data) "
                "VALUES (:id, :iid, 'quarterly', '2025-09-30', '{}'::jsonb)"
            ),
            {"id": _new_uuid(), "iid": ids["third"]},
        )

        # ── SECOND independent duplicate group (AMD): placeholder '' + real 'US'.
        # Proves the migration walks MULTIPLE groups in a single pass.
        await conn.execute(
            text(
                "INSERT INTO instruments (id, security_id, symbol, exchange, has_fundamentals, created_at) "
                "VALUES (:id, :sec, 'AMD', '', true, '2026-07-15T00:00:00Z')"
            ),
            {"id": ids["amd_placeholder"], "sec": ids["security"]},
        )
        await conn.execute(
            text(
                "INSERT INTO instruments (id, security_id, symbol, exchange, has_fundamentals, created_at) "
                "VALUES (:id, :sec, 'AMD', 'US', true, '2026-07-16T00:00:00Z')"
            ),
            {"id": ids["amd_canonical"], "sec": ids["security"]},
        )
        await conn.execute(
            text("INSERT INTO quotes (instrument_id, last) VALUES (:iid, 42.00)"),
            {"iid": ids["amd_placeholder"]},
        )

        # ── A NON-duplicate instrument (TSLA): the ONLY row for its symbol, so
        # the migration must leave it (and its children) completely untouched.
        await conn.execute(
            text(
                "INSERT INTO instruments (id, security_id, symbol, exchange, has_fundamentals, created_at) "
                "VALUES (:id, :sec, 'TSLA', 'US', true, '2026-07-01T00:00:00Z')"
            ),
            {"id": ids["solo"], "sec": ids["security"]},
        )
        await conn.execute(
            text("INSERT INTO quotes (instrument_id, last) VALUES (:iid, 250.00)"),
            {"iid": ids["solo"]},
        )
    await engine.dispose()


@pytest.fixture(scope="module")
def _merged_db(_pre_merge_container: object) -> dict[str, str]:
    """Run 045 -> seed duplicates -> run through 047, all synchronously.

    Returns the instrument ids used by the fixture so the test can assert on
    them, plus the asyncpg URL for read-only assertions.
    """
    from alembic import command

    raw_url = _pre_merge_container.get_connection_url()  # type: ignore[attr-defined]
    asyncpg_url = raw_url.replace("postgresql://", "postgresql+asyncpg://").replace("psycopg2", "asyncpg")

    ids = {
        "security": _new_uuid(),
        # NFLX group: placeholder + third loser + canonical winner (3-way merge).
        "placeholder": _new_uuid(),
        "third": _new_uuid(),
        "canonical": _new_uuid(),
        # Second independent duplicate group (AMD): proves multi-group in one run.
        "amd_placeholder": _new_uuid(),
        "amd_canonical": _new_uuid(),
        # A NON-duplicate instrument (TSLA): must be left completely untouched.
        "solo": _new_uuid(),
    }

    cfg = _alembic_config(asyncpg_url)
    try:
        command.upgrade(cfg, "045")
    finally:
        os.environ.pop("ALEMBIC_URL", None)

    # Seed BEFORE the merge migration runs so it has real duplicate data to
    # repair — this is the crux of the test (see module docstring).
    asyncio.run(_seed_duplicate_fixture(asyncpg_url, ids))

    cfg = _alembic_config(asyncpg_url)
    try:
        command.upgrade(cfg, "047")
    finally:
        os.environ.pop("ALEMBIC_URL", None)

    return {**ids, "asyncpg_url": asyncpg_url}


async def test_merge_migration_repairs_seeded_duplicate_and_guard_prevents_recurrence(
    _merged_db: dict[str, str],
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine

    canonical_id = _merged_db["canonical"]
    security_id = _merged_db["security"]
    engine = create_async_engine(_merged_db["asyncpg_url"], echo=False)

    async with engine.begin() as conn:
        # ── Assertion 1: exactly one NFLX instrument survives, and it is the
        # real-exchange (canonical) row.
        rows = (await conn.execute(text("SELECT id, exchange FROM instruments WHERE symbol = 'NFLX'"))).all()
        assert len(rows) == 1, f"expected exactly 1 surviving NFLX row, got {rows}"
        # asyncpg returns native uuid.UUID objects for ``uuid`` columns even
        # when the raw SQL text() path bypasses the ORM's ``as_uuid=False``
        # type decorator — normalize both sides to str for comparison.
        assert str(rows[0].id) == canonical_id
        assert rows[0].exchange == "US"

        # ── Assertion 2: the placeholder's unique fundamentals period was
        # reassigned (not lost) — 2025-12-31 quarterly now belongs to canonical.
        reassigned = (
            await conn.execute(
                text(
                    "SELECT instrument_id FROM income_statements "
                    "WHERE period_type = 'quarterly' AND period_end_date = '2025-12-31'"
                )
            )
        ).all()
        assert len(reassigned) == 1
        assert str(reassigned[0].instrument_id) == canonical_id

        # ── Assertion 3: the conflicting period (2026-03-31) kept ONLY the
        # canonical's row — no duplicate, no data loss of the canonical value.
        conflict_rows = (
            await conn.execute(
                text(
                    "SELECT instrument_id, data FROM income_statements "
                    "WHERE period_type = 'quarterly' AND period_end_date = '2026-03-31'"
                )
            )
        ).all()
        assert len(conflict_rows) == 1
        assert str(conflict_rows[0].instrument_id) == canonical_id
        assert conflict_rows[0].data == {"fresh": True}

        # ── Assertion 4: the placeholder's snapshot was reassigned since the
        # canonical had none.
        snap = (await conn.execute(text("SELECT instrument_id, eps_ttm FROM instrument_fundamentals_snapshot"))).all()
        assert len(snap) == 1
        assert str(snap[0].instrument_id) == canonical_id
        assert float(snap[0].eps_ttm) == pytest.approx(1.23)

        # ── Assertion 5: the NFLX canonical kept only its own (fresher) quote;
        # both the placeholder's conflicting quote and the third loser had none.
        # (Scope by instrument_id — quotes also holds AMD/TSLA rows now.)
        nflx_quotes = (
            await conn.execute(text("SELECT last FROM quotes WHERE instrument_id = :iid"), {"iid": canonical_id})
        ).all()
        assert len(nflx_quotes) == 1
        assert float(nflx_quotes[0].last) == pytest.approx(500.00)

        # ── Assertion 6: the placeholder-only metric was reassigned.
        metric_rows = (await conn.execute(text("SELECT instrument_id FROM fundamental_metrics"))).all()
        assert len(metric_rows) == 1
        assert str(metric_rows[0].instrument_id) == canonical_id

        # ── Assertion 6b: THIRD-loser path — its unique 2025-09-30 fundamentals
        # period was also reassigned to the single winner (3-way merge worked).
        third_reassigned = (
            await conn.execute(
                text(
                    "SELECT instrument_id FROM income_statements "
                    "WHERE period_type = 'quarterly' AND period_end_date = '2025-09-30'"
                )
            )
        ).all()
        assert len(third_reassigned) == 1
        assert str(third_reassigned[0].instrument_id) == canonical_id

        # ── Assertion 6c: ohlcv_bars — the placeholder's UNIQUE bar was
        # reassigned; the CONFLICTING bar dropped in favour of the canonical's
        # (kept the winner's close), so exactly 2 NFLX bars remain, both on the
        # canonical, and the conflict date carries the canonical's value.
        nflx_bars = (
            await conn.execute(
                text("SELECT bar_date, close FROM ohlcv_bars WHERE instrument_id = :iid ORDER BY bar_date"),
                {"iid": canonical_id},
            )
        ).all()
        assert len(nflx_bars) == 2
        assert float(nflx_bars[0].close) == pytest.approx(100.0)  # reassigned unique bar
        assert float(nflx_bars[1].close) == pytest.approx(555.0)  # canonical won the conflict
        # No bars left pointing at any deleted loser.
        orphan_bars = (
            await conn.execute(
                text("SELECT count(*) AS c FROM ohlcv_bars WHERE instrument_id <> :iid"), {"iid": canonical_id}
            )
        ).one()
        assert orphan_bars.c == 0

        # ── Assertion 6d: insider_transactions / earnings_calendar /
        # company_profiles (placeholder-only rows) were all reassigned.
        for table in ("insider_transactions", "earnings_calendar", "company_profiles"):
            rows_t = (await conn.execute(text(f"SELECT instrument_id FROM {table}"))).all()  # noqa: S608 -- fixed table names
            assert len(rows_t) == 1, f"{table} lost/duplicated a reassigned row"
            assert str(rows_t[0].instrument_id) == canonical_id, f"{table} not reassigned to winner"

        # ── Assertion 7: SECOND group (AMD) also merged to its real-exchange
        # winner, and the placeholder's quote was reassigned (canonical had none).
        amd_rows = (await conn.execute(text("SELECT id, exchange FROM instruments WHERE symbol = 'AMD'"))).all()
        assert len(amd_rows) == 1
        assert str(amd_rows[0].id) == _merged_db["amd_canonical"]
        amd_quotes = (
            await conn.execute(
                text("SELECT last FROM quotes WHERE instrument_id = :iid"), {"iid": _merged_db["amd_canonical"]}
            )
        ).all()
        assert len(amd_quotes) == 1
        assert float(amd_quotes[0].last) == pytest.approx(42.00)

        # ── Assertion 8: the NON-duplicate instrument (TSLA) is untouched —
        # same id, same single quote, nothing merged or deleted.
        tsla_rows = (await conn.execute(text("SELECT id FROM instruments WHERE symbol = 'TSLA'"))).all()
        assert len(tsla_rows) == 1
        assert str(tsla_rows[0].id) == _merged_db["solo"]
        tsla_quotes = (
            await conn.execute(text("SELECT last FROM quotes WHERE instrument_id = :iid"), {"iid": _merged_db["solo"]})
        ).all()
        assert len(tsla_quotes) == 1
        assert float(tsla_quotes[0].last) == pytest.approx(250.00)

    # ── Assertion 9 (migration 047): a SECOND placeholder-exchange row for
    # the SAME symbol is now rejected at the DB level. Migration 046 already
    # deleted the original placeholder row, so the FIRST post-merge insert
    # of ``exchange=''`` for NFLX legitimately succeeds (there is nothing
    # left to conflict with) — the guard only bites on the second one.
    async with engine.begin() as conn1:
        await conn1.execute(
            text("INSERT INTO instruments (id, security_id, symbol, exchange) VALUES (:id, :sec, 'NFLX', '')"),
            {"id": _new_uuid(), "sec": security_id},
        )

    async with engine.connect() as conn2:
        with pytest.raises(IntegrityError):
            await conn2.execute(
                text("INSERT INTO instruments (id, security_id, symbol, exchange) VALUES (:id, :sec, 'NFLX', '')"),
                {"id": _new_uuid(), "sec": security_id},
            )

    await engine.dispose()
