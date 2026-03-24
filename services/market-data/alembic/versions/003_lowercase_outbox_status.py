"""Migrate outbox and failed-task status values to canonical lowercase.

Revision ID: 003
Revises: 002
Create Date: 2026-03-23

Standardises status column values across outbox_events and failed_tasks
tables to match the canonical values defined in STANDARDS.md §3.5:
  pending | processing | delivered | dead_letter

Previous non-canonical values:
  PENDING    → pending
  PROCESSING → processing
  DISPATCHED → delivered
  DEAD_LETTER→ dead_letter
  FAILED     → dead_letter
  DEAD       → dead_letter  (failed_tasks only)
"""

from __future__ import annotations

from alembic import op


def upgrade() -> None:
    # outbox_events
    op.execute("UPDATE outbox_events SET status = 'pending'     WHERE status = 'PENDING'")
    op.execute("UPDATE outbox_events SET status = 'processing'  WHERE status = 'PROCESSING'")
    op.execute("UPDATE outbox_events SET status = 'delivered'   WHERE status = 'DISPATCHED'")
    op.execute("UPDATE outbox_events SET status = 'dead_letter' WHERE status IN ('DEAD_LETTER', 'FAILED')")

    # failed_tasks
    op.execute("UPDATE failed_tasks SET status = 'pending'     WHERE status = 'PENDING'")
    op.execute("UPDATE failed_tasks SET status = 'processing'  WHERE status = 'PROCESSING'")
    op.execute("UPDATE failed_tasks SET status = 'dead_letter' WHERE status IN ('DEAD', 'DEAD_LETTER', 'FAILED')")


def downgrade() -> None:
    op.execute("UPDATE outbox_events SET status = 'PENDING'     WHERE status = 'pending'")
    op.execute("UPDATE outbox_events SET status = 'PROCESSING'  WHERE status = 'processing'")
    op.execute("UPDATE outbox_events SET status = 'DISPATCHED'  WHERE status = 'delivered'")
    op.execute("UPDATE outbox_events SET status = 'DEAD_LETTER' WHERE status = 'dead_letter'")

    op.execute("UPDATE failed_tasks SET status = 'PENDING'      WHERE status = 'pending'")
    op.execute("UPDATE failed_tasks SET status = 'DEAD'         WHERE status = 'dead_letter'")
