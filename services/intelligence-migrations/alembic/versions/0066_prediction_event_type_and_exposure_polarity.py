"""Add 'prediction' event_type + exposure polarity columns — PLAN-0056 Wave C1.

Revision ID: 0066
Revises: 0065
Create Date: 2026-07-10

Changes (PLAN-0056 Sub-Plan C, task T-C-1-01 / PRD-0033):
  temporal_events:
    - DROP CONSTRAINT ck_temporal_event_type
    - ADD CONSTRAINT ck_temporal_event_type CHECK (
          event_type IN (
              'geopolitical','regulatory','macro','sanctions',
              'natural_disaster','other','corporate','prediction'
          )
      )
  entity_event_exposures:
    - ADD COLUMN polarity            VARCHAR(20)      NULL
    - ADD COLUMN polarity_confidence DOUBLE PRECISION NULL
    - ADD CONSTRAINT ck_exposure_polarity CHECK (
          polarity IN ('bullish','bearish','neutral') OR polarity IS NULL
      )

WHY 'prediction':
  Sub-Plan C activates prediction-market data as first-class temporal events: the
  KG ingests prediction-market events (e.g. Polymarket/Kalshi resolution windows)
  into ``temporal_events`` with event_type='prediction'. Without this migration the
  INSERT would fail the CHECK constraint. This migration is the schema foundation
  (the KG-side ``EventType.PREDICTION`` and exposure polarity land on top of it).

WHY polarity / polarity_confidence (entity_event_exposures):
  Prediction events carry a directional signal for each exposed entity — a market
  resolving one way is bullish for entity A and bearish for entity B. The
  ``polarity`` column ('bullish'|'bearish'|'neutral') records that direction and
  ``polarity_confidence`` its confidence. Both are NULLABLE with NO default so
  existing earnings/corporate exposures keep NULL polarity (they are non-directional
  today) — this is a forward-compatible additive change (R5/R11/BP-007).

BP-007 (no PG enum):
  polarity is a VARCHAR(20) + CHECK, never a Postgres enum — enums are painful to
  widen and BP-007 forbids them for domain-value columns.

FORWARD-COMPATIBILITY (R5):
  Both schema changes are additive. The widened event_type CHECK keeps all prior
  values valid; the two new columns are nullable with no default so no existing row
  is invalidated and no backfill is required.

DOWNGRADE:
  Drops the two columns and restores the pre-0066 event_type CHECK (without
  'prediction'). Deletes any event_type='prediction' rows first so restoring the
  narrower constraint cannot fail on existing prediction events.

IDEMPOTENT:
  ALTER TABLE ... DROP CONSTRAINT IF EXISTS / ADD COLUMN IF NOT EXISTS is safe to
  re-apply after a partially-failed run.
"""

from __future__ import annotations

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade: widen the event_type CHECK to include 'prediction' + add polarity cols
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
            'corporate',
            'prediction'
        )
    )
"""

# Two nullable, no-default columns — existing exposures keep NULL polarity.
_ADD_POLARITY_COLUMNS = """
ALTER TABLE entity_event_exposures
    ADD COLUMN IF NOT EXISTS polarity VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS polarity_confidence DOUBLE PRECISION NULL
"""

# VARCHAR + CHECK (BP-007, no PG enum). NULL is allowed (non-directional exposures).
_ADD_POLARITY_CHECK = """
ALTER TABLE entity_event_exposures
    DROP CONSTRAINT IF EXISTS ck_exposure_polarity;
ALTER TABLE entity_event_exposures
    ADD CONSTRAINT ck_exposure_polarity CHECK (
        polarity IN ('bullish', 'bearish', 'neutral') OR polarity IS NULL
    )
"""

# ---------------------------------------------------------------------------
# Downgrade: drop columns + restore the pre-0066 event_type constraint
# ---------------------------------------------------------------------------

_DROP_POLARITY_CHECK = """
ALTER TABLE entity_event_exposures
    DROP CONSTRAINT IF EXISTS ck_exposure_polarity
"""

_DROP_POLARITY_COLUMNS = """
ALTER TABLE entity_event_exposures
    DROP COLUMN IF EXISTS polarity_confidence,
    DROP COLUMN IF EXISTS polarity
"""

# Remove prediction rows first (safe-guard — prevents constraint violation on ADD).
_DELETE_PREDICTION_ROWS = """
DELETE FROM temporal_events WHERE event_type = 'prediction'
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
            'other',
            'corporate'
        )
    )
"""


def upgrade() -> None:
    # Step 1: widen the event_type CHECK to accept 'prediction'.
    op.execute(_DROP_OLD_CONSTRAINT)
    op.execute(_ADD_NEW_CONSTRAINT)
    # Step 2: add the two nullable polarity columns + their CHECK.
    op.execute(_ADD_POLARITY_COLUMNS)
    op.execute(_ADD_POLARITY_CHECK)


def downgrade() -> None:
    # Step 1: drop the polarity CHECK + columns.
    op.execute(_DROP_POLARITY_CHECK)
    op.execute(_DROP_POLARITY_COLUMNS)
    # Step 2: remove any prediction rows (prevents constraint violation on restore).
    op.execute(_DELETE_PREDICTION_ROWS)
    # Step 3: drop the widened constraint and restore the pre-0066 allow-list.
    op.execute(_DROP_NEW_CONSTRAINT)
    op.execute(_RESTORE_OLD_CONSTRAINT)
