"""Source-level guards for migration 043 (PLAN-0056 A1 prediction deeper streams).

WHY THIS TEST EXISTS:
  Migration 043 creates the four deeper-stream prediction tables + adds
  ``prediction_markets.event_id``. Several invariants MUST hold together and a
  live DB is not available in CI, so these textual guards pin them at the
  script level (same pattern as ``test_migration_039_unique_isin_exchange.py``):

    * the revision chain (043 → 042, R32);
    * BP-019/032: each hypertable is created AFTER its table exists, with
      ``migrate_data => true``;
    * the two hypertables (prices, trades) are created; OI + events are NOT;
    * ``downgrade`` reverses every ``upgrade`` object (drops the 4 tables + the
      added column).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _load_migration_source() -> str:
    here = Path(__file__).resolve()
    repo_root = here
    while repo_root.name != "market-data" and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    mig = repo_root / "alembic" / "versions" / "043_prediction_deeper_streams.py"
    return mig.read_text(encoding="utf-8")


def test_migration_043_revision_chain() -> None:
    """043 must follow 042 (R32 — chained from verified head)."""
    src = _load_migration_source()
    assert 'revision: str = "043"' in src
    assert 'down_revision: str = "042"' in src


def test_upgrade_creates_four_new_tables() -> None:
    src = _load_migration_source()
    for table in (
        "prediction_market_prices",
        "prediction_market_trades",
        "prediction_market_oi",
        "prediction_events",
    ):
        assert f'op.create_table(\n        "{table}"' in src, f"missing create_table for {table}"


def test_upgrade_adds_event_id_column() -> None:
    """ALTER prediction_markets ADD event_id (nullable)."""
    src = _load_migration_source()
    assert 'op.add_column(\n        "prediction_markets"' in src
    assert '"event_id"' in src


def test_prices_and_trades_are_hypertables_after_table() -> None:
    """BP-019/032: create_hypertable runs AFTER the table + with migrate_data=>true."""
    src = _load_migration_source()
    for table, time_col in (
        ("prediction_market_prices", "window_start_ts"),
        ("prediction_market_trades", "ts"),
    ):
        create_pos = src.index(f'op.create_table(\n        "{table}"')
        # The hypertable SQL literal names the table as ``'<table>',``; assert it
        # comes AFTER the create_table for that table.
        hyper_pos = src.index(f"'{table}',", create_pos)
        assert create_pos < hyper_pos, f"hypertable for {table} created before its table"
        assert "migrate_data => true" in src
        assert time_col in src


def test_oi_and_events_are_not_hypertables() -> None:
    """OI (daily) and events must NOT be converted to hypertables.

    There are exactly two create_hypertable calls (prices + trades); neither
    OI nor events is ever passed as a hypertable target.
    """
    src = _load_migration_source()
    assert src.count("create_hypertable(") == 2
    assert "'prediction_market_oi'," not in src
    assert "'prediction_events'," not in src


def test_interval_and_side_are_varchar_not_enum() -> None:
    """BP-007: interval / side are VARCHAR (String), never a PG enum."""
    src = _load_migration_source()
    assert 'sa.Column("interval", sa.String(4)' in src
    assert 'sa.Column("side", sa.String(8)' in src
    assert "sa.Enum" not in src
    assert "ENUM" not in src


def test_downgrade_reverses_upgrade() -> None:
    """Downgrade drops the 4 tables + the added column."""
    src = _load_migration_source()
    down = src.split("def downgrade")[1]
    assert 'op.drop_column("prediction_markets", "event_id")' in down
    for table in (
        "prediction_market_prices",
        "prediction_market_trades",
        "prediction_market_oi",
        "prediction_events",
    ):
        assert f'op.drop_table("{table}")' in down
