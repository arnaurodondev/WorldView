"""Source-level guards for migration 044 (PLAN-0056 QA — event_id index + retention).

WHY THIS TEST EXISTS:
  Migration 044 adds a partial index on ``prediction_markets.event_id`` (FIX 3)
  and registers 180-day retention policies on the two prediction hypertables
  (FIX 4). A live DB is not available in CI, so these textual guards pin the
  invariants at the script level (same pattern as
  ``test_migration_043_prediction_deeper_streams.py``):

    * the revision chain (044 → 043, R32);
    * a PARTIAL index (``WHERE event_id IS NOT NULL``) on the event_id column;
    * retention policies are GUARDED behind a timescaledb-extension check so a
      plain-Postgres DB is a no-op (never fails the migration);
    * ``downgrade`` reverses both objects (removes the policies + drops the index).
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
    mig = repo_root / "alembic" / "versions" / "044_prediction_markets_event_id_index.py"
    return mig.read_text(encoding="utf-8")


def test_migration_044_revision_chain() -> None:
    """044 must follow 043 (R32 — chained from verified head)."""
    src = _load_migration_source()
    assert 'revision: str = "044"' in src
    assert 'down_revision: str = "043"' in src


def test_upgrade_creates_partial_event_id_index() -> None:
    """Partial index on prediction_markets.event_id WHERE event_id IS NOT NULL."""
    src = _load_migration_source()
    assert 'op.create_index(\n        "ix_prediction_markets_event_id"' in src
    assert '"prediction_markets"' in src
    assert 'postgresql_where=sa.text("event_id IS NOT NULL")' in src


def test_retention_is_guarded_behind_timescaledb_extension() -> None:
    """add_retention_policy must only run when timescaledb is installed."""
    src = _load_migration_source()
    upgrade = src.split("def upgrade")[1].split("def downgrade")[0]
    assert "add_retention_policy(" in upgrade
    assert "extname = 'timescaledb'" in upgrade
    assert "if_not_exists => true" in upgrade
    # Both prediction hypertables get a policy (named in the retention constant);
    # OI / events / snapshots do not.
    assert '_RETENTION_TABLES = ("prediction_market_trades", "prediction_market_prices")' in src
    assert "prediction_market_oi" not in src
    assert "prediction_market_snapshots" not in src


def test_downgrade_reverses_upgrade() -> None:
    """Downgrade removes the retention policies (guarded) and drops the index."""
    src = _load_migration_source()
    down = src.split("def downgrade")[1]
    assert "remove_retention_policy(" in down
    assert "extname = 'timescaledb'" in down
    assert 'op.drop_index("ix_prediction_markets_event_id"' in down
