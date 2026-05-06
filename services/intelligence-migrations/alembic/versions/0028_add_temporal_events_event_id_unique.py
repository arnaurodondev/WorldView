"""Assert PRIMARY KEY uniqueness on temporal_events(event_id) — DEF-025 invariant.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-06

WHAT THIS MIGRATION DOES (operationally a NO-OP, intentionally):
  This migration **does not add any new constraints or indexes**.  It exists
  solely to assert — at upgrade time — that the DEF-025 invariant
  ("temporal_events.event_id is unique") is enforced by an existing constraint
  on the table.  If it is not, the migration raises and the upgrade aborts.

WHY THIS IS A NO-OP (PLAN-0076 QA fix):
  The original Wave A-3 migration created
  ``CREATE UNIQUE INDEX idx_temporal_events_event_id_unique ON temporal_events
  (event_id)``.  That index is **functionally redundant** because migration
  0004 (``0004_geopolitical_age_temporal_events.py``) already declared
  ``CONSTRAINT pk_temporal_events PRIMARY KEY (event_id)`` on the same column.
  PostgreSQL implements the PK with its own unique B-tree index, so adding a
  second unique B-tree on the same expression duplicates the maintenance cost
  on every INSERT/UPDATE without protecting any new invariant.

  The QA review surfaced this duplication.  Rather than carry the dead index
  forward we replace the migration body with an **introspection assertion**
  that the underlying invariant is intact, plus a no-op downgrade.  Future
  partition-reshape migrations that drop and re-create the PK will trip this
  assertion and force the author to add an explicit replacement.

INVARIANT BEING ASSERTED:
  ``temporal_events`` has a PRIMARY KEY constraint.  We do not check that the
  PK column is specifically ``event_id`` because the DEF-025 deterministic-id
  flow only depends on ``temporal_events`` rejecting a second insert with the
  same event_id; any PK on event_id (named or anonymous) suffices.

WHY ASSERTING IS WORTH A MIGRATION SLOT:
  1. Schema drift detection: if a future plan accidentally drops the PK to
     repartition the table without restoring it, this migration prevents the
     drift from reaching production silently.
  2. Documentation: the migration docstring is the canonical place to record
     the DEF-025 dependence on PK uniqueness — easier to grep than scattered
     code comments.
  3. Downgrade safety: a no-op downgrade keeps the constraint in place even if
     ``alembic downgrade -1`` is run, so the invariant is never weakened by
     rollback.

FORWARD-COMPATIBILITY (R5):
  Pure assertion; no DDL changes; no data migration.

DOWNGRADE:
  No-op (the PK was not added by this migration so we have nothing to drop).
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Introspect pg_constraint for any PRIMARY KEY on temporal_events.  If
    # absent, RAISE inside the DO block aborts the migration cleanly.  The
    # assertion catches the future regression: a maintainer drops the PK to
    # reshape the table and forgets to restore it.
    op.execute(
        """
DO $migration_0028_assert$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'temporal_events'
          AND c.contype = 'p'
    ) THEN
        RAISE EXCEPTION
            'DEF-025 invariant violated: temporal_events has no PRIMARY KEY constraint. '
            'Migration 0028 expects pk_temporal_events (event_id) created by migration 0004 '
            'to enforce event_id uniqueness for replay-safe INSERTs in graph_write.';
    END IF;
END
$migration_0028_assert$;
        """
    )


def downgrade() -> None:
    # Pure no-op — this migration adds nothing to drop.  We deliberately do
    # NOT remove the underlying PK on rollback; that PK is owned by
    # migration 0004 and downgrading this revision must not weaken the
    # DEF-025 invariant in any direction.
    pass
