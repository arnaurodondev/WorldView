"""Source-level guards for migration 049 (retention-pruner index fix).

WHY THIS TEST EXISTS:
  Live investigation on 2026-07-25 found the ``ingestion_events`` retention
  pruner (``libs/messaging/kafka/maintenance/table_retention.py``, added
  after the 2026-07-18 disk-full outage) fails its very first pass every
  time against production's ~25M-row / 7.4 GB ``ingestion_events`` table:
  its ``DELETE ... WHERE occurred_at < :cutoff ORDER BY occurred_at LIMIT
  :batch`` has no usable index (migration 001 only indexed ``id``,
  ``event_id``, and ``(content_sha256, event_type)``), so it forces a full
  table sort and blows ``statement_timeout`` on every attempt
  (``table_retention_loop_error`` in the dispatcher logs). Migration 049
  adds the missing ``occurred_at`` index so the pruner can actually drain
  the backlog and this outage class does not recur.

  A live DB is not available in CI, so (same pattern as
  ``test_migration_044_prediction_markets_event_id_index.py``) these are
  textual guards pinning the invariants at the script level:

    * the revision chain (049 -> 048);
    * the index is built CONCURRENTLY (no ACCESS EXCLUSIVE lock on a live,
      high-write idempotency table);
    * CONCURRENTLY runs inside an autocommit block (required by Postgres —
      it cannot run inside a transaction);
    * downgrade drops the index, also CONCURRENTLY and idempotently.
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
    mig = repo_root / "alembic" / "versions" / "049_ingestion_events_occurred_at_index.py"
    return mig.read_text(encoding="utf-8")


def test_migration_049_revision_chain() -> None:
    """049 must follow 048 (chained from the verified head)."""
    src = _load_migration_source()
    assert 'revision = "049"' in src
    assert 'down_revision = "048"' in src


def test_upgrade_creates_index_concurrently_in_autocommit_block() -> None:
    """occurred_at index must be built CONCURRENTLY inside an autocommit block."""
    src = _load_migration_source()
    upgrade = src.split("def upgrade")[1].split("def downgrade")[0]
    assert "op.get_context().autocommit_block()" in upgrade
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ingestion_events_occurred_at" in upgrade
    assert "ON ingestion_events (occurred_at)" in upgrade


def test_downgrade_drops_index_concurrently_and_idempotently() -> None:
    """Downgrade must drop the index CONCURRENTLY and tolerate it being absent."""
    src = _load_migration_source()
    downgrade = src.split("def downgrade")[1]
    assert "op.get_context().autocommit_block()" in downgrade
    assert "DROP INDEX CONCURRENTLY IF EXISTS ix_ingestion_events_occurred_at" in downgrade
