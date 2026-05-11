"""Add 'noise' status to provisional_entity_queue CHECK constraint.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-05

Changes:
  provisional_entity_queue:
    - ADD CONSTRAINT ck_provisional_status CHECK (status IN (..., 'noise'))

WHY:
  PLAN-0072 T-72-1-01 introduces a two-layer noise pre-filter in
  ProvisionalEnrichmentWorker. Rows that fail the blocklist (Layer 1) or
  the cheap LLM classifier (Layer 2) are transitioned to 'noise' — a new
  terminal status equivalent to 'failed' but with a semantically distinct
  meaning (the mention text was never a real entity, not a processing error).

  Without this constraint the 'noise' UPDATE would succeed silently but the
  DB would not enforce the valid-status invariant, making ad-hoc queries
  and future code changes less safe.

  The status column is bare VARCHAR(20) with no CHECK constraint today
  (migration 0001 created it as NOT NULL DEFAULT 'pending'). This migration
  adds enforcement retroactively. On a fresh-start cluster all existing rows
  are in {pending, processing, resolved, failed} — none will violate the
  new constraint.

FORWARD-COMPATIBILITY (R5):
  Additive constraint. New code writes 'noise'; old code that only writes
  {pending, processing, resolved, failed} is unaffected.

DOWNGRADE:
  Drop the constraint. Existing 'noise' rows remain; they will be
  re-processed as 'pending' on the next worker cycle unless also cleaned up
  manually (safe since noise rows are truly noise and re-processing simply
  re-marks them noise).
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE provisional_entity_queue
    ADD CONSTRAINT ck_provisional_status
    CHECK (status IN ('pending', 'processing', 'resolved', 'failed', 'noise'))
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE provisional_entity_queue
    DROP CONSTRAINT IF EXISTS ck_provisional_status
""")
