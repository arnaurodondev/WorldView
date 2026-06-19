"""Durable per-worker last-success store so the skip-guard survives restarts.

Revision ID: 040
Revises: 039
Create Date: 2026-06-18

PLAN-0089 L-3 ops follow-up (audit 2026-06-16-prd0089-l3-computed-metrics-ops
Lens 2 / §5.2).

WHY THIS TABLE EXISTS:
  The computed-metrics refresh loop (``app.py::_computed_metrics_refresh_loop``)
  used an *in-process* ``last_success_at`` local variable for its 20-hour
  skip-guard. On every container restart that state was wiped to ``None``, so
  the guard was a no-op against the exact scenario it was written for (a
  double-run inside the same 24h window after a restart). It also meant the
  liveness signal did not survive a deploy.

  This single-row-per-worker table records the last successful completion
  timestamp durably. The loop reads it at startup to seed the guard and writes
  it after every successful run. The Prometheus liveness gauge is also seeded
  from it on boot so a freshly-restarted pod reports an accurate
  "last success" age immediately rather than ``0``/absent.

SCHEMA:
  * ``worker_name``    TEXT PRIMARY KEY — stable worker identifier
                       (e.g. ``computed_metrics_backfill``).
  * ``last_success_at`` TIMESTAMPTZ NOT NULL — UTC completion time of the last
                       successful run.
  * ``updated_at``     TIMESTAMPTZ NOT NULL — row maintenance stamp.

FORWARD-COMPAT (R11): purely additive — a new table with defaults. No existing
column is removed or renamed. Idempotent ``IF NOT EXISTS`` so re-applying on a
volume that already has the table is a no-op.

DOWNGRADE: drop the table (it is a derived operational cache; losing it only
resets the skip-guard to "no prior run", which is safe — the next run recreates
the row).
"""

from __future__ import annotations

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``worker_runs`` durable last-success table (idempotent)."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_runs (
            worker_name     TEXT PRIMARY KEY,
            last_success_at TIMESTAMPTZ NOT NULL,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    """Drop the ``worker_runs`` table."""
    op.execute("DROP TABLE IF EXISTS worker_runs")
