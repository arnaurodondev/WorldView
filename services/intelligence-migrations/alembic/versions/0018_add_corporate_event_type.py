"""Add 'corporate' to temporal_events event_type CHECK constraint.

Revision ID: 0018
Revises: 0013
Create Date: 2026-05-03

Changes (PLAN-0068 Wave A-1):
  temporal_events:
    - DROP CONSTRAINT ck_temporal_event_type
    - ADD CONSTRAINT ck_temporal_event_type CHECK (
          event_type IN (
              'geopolitical','regulatory','macro','sanctions',
              'natural_disaster','other','corporate'
          )
      )

WHY 'corporate':
  The EarningsCalendarDatasetConsumer (consumer 13D-9) ingests Finnhub earnings
  calendar data from the market.dataset.fetched Kafka topic and writes rows into
  temporal_events with event_type='corporate'. Without this migration the INSERT
  would fail with a CHECK constraint violation.

FORWARD-COMPATIBILITY (R5):
  This is an additive change — existing rows with the 6 prior event_type values
  remain valid. The constraint is widened, not narrowed.

DOWNGRADE:
  Removes 'corporate' from the constraint. Any rows already inserted with
  event_type='corporate' are NOT automatically deleted — this migration only
  manages the constraint definition. If a downgrade is run while corporate rows
  exist, the constraint ADD will silently ignore them (the constraint is on future
  inserts/updates only). To be safe, the downgrade also deletes corporate rows
  first.

IDEMPOTENT:
  ALTER TABLE ... DROP CONSTRAINT IF EXISTS / ADD CONSTRAINT is idempotent when
  the migration is re-applied after a failed run.
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0013"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade: widen the event_type CHECK to include 'corporate'
# ---------------------------------------------------------------------------

_DROP_OLD_CONSTRAINT = """
ALTER TABLE temporal_events
    DROP CONSTRAINT IF EXISTS ck_temporal_event_type
"""

_ADD_NEW_CONSTRAINT = """
ALTER TABLE temporal_events
    ADD CONSTRAINT ck_temporal_event_type CHECK (
        event_type IN (
            'geopolitical',
            'regulatory',
            'macro',
            'sanctions',
            'natural_disaster',
            'other',
            'corporate'
        )
    )
"""

# ---------------------------------------------------------------------------
# Downgrade: restore the original 6-value constraint (remove 'corporate')
# ---------------------------------------------------------------------------

# First remove corporate rows (safe-guard — prevents constraint violation on ADD)
_DELETE_CORPORATE_ROWS = """
DELETE FROM temporal_events WHERE event_type = 'corporate'
"""

_DROP_NEW_CONSTRAINT = """
ALTER TABLE temporal_events
    DROP CONSTRAINT IF EXISTS ck_temporal_event_type
"""

_RESTORE_OLD_CONSTRAINT = """
ALTER TABLE temporal_events
    ADD CONSTRAINT ck_temporal_event_type CHECK (
        event_type IN (
            'geopolitical',
            'regulatory',
            'macro',
            'sanctions',
            'natural_disaster',
            'other'
        )
    )
"""


def upgrade() -> None:
    # Step 1: drop the existing constraint (IF EXISTS keeps re-runs safe)
    op.execute(_DROP_OLD_CONSTRAINT)
    # Step 2: recreate with 'corporate' added to the allow-list
    op.execute(_ADD_NEW_CONSTRAINT)


def downgrade() -> None:
    # Step 1: remove any corporate rows (prevents constraint violation on restore)
    op.execute(_DELETE_CORPORATE_ROWS)
    # Step 2: drop the widened constraint
    op.execute(_DROP_NEW_CONSTRAINT)
    # Step 3: restore the original 6-value constraint
    op.execute(_RESTORE_OLD_CONSTRAINT)
