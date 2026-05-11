"""Add processing_path column to routing_decisions; defensive re-add of final_routing_tier.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-30

PLAN-0057 Wave A-1 (T-A-1-01) — closes audit finding F-CRIT-06.

Two changes:
  1. **processing_path** (genuinely new) — text column persisting the
     ``ProcessingPath`` enum value chosen by Block 6 (suppression gate).
     Possible values: ``HALT`` | ``SECTION_EMBEDDINGS_ONLY`` | ``FULL_PIPELINE``.
     Nullable (legacy rows) with CHECK constraint.

  2. **final_routing_tier** (defensive re-add) — already declared in
     ``0001_create_nlp_schema.py`` and on ``RoutingDecisionModel``. Some
     deployments dropped it manually before this migration ran (audit observed
     "column does not exist" on a production DB). Use ``ADD COLUMN IF NOT
     EXISTS`` so this migration is safe regardless of drift state.

Both columns are nullable, so the migration is forward-safe (BP-126) and
requires no table rewrite.
"""

from __future__ import annotations

from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive re-add of final_routing_tier. Idempotent if already present.
    op.execute("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS final_routing_tier TEXT")

    # New: processing_path
    op.execute("ALTER TABLE routing_decisions ADD COLUMN IF NOT EXISTS processing_path TEXT")

    # CHECK constraints (lower-case enum values match StrEnum string values)
    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_processing_path_chk")
    op.execute(
        "ALTER TABLE routing_decisions "
        "ADD CONSTRAINT routing_decisions_processing_path_chk "
        "CHECK (processing_path IS NULL OR processing_path IN "
        "('full_pipeline','section_embeddings_only','halt'))"
    )

    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_final_tier_chk")
    op.execute(
        "ALTER TABLE routing_decisions "
        "ADD CONSTRAINT routing_decisions_final_tier_chk "
        "CHECK (final_routing_tier IS NULL OR final_routing_tier IN "
        "('deep','medium','light','suppress'))"
    )

    # Partial index for tier-distribution analytics (only ~20-30% of rows are
    # downgrade-affected, so partial index keeps the index small and the
    # majority of inserts pay no maintenance cost).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_routing_final_tier_decided_at "
        "ON routing_decisions (final_routing_tier, decided_at) "
        "WHERE final_routing_tier IS NOT NULL"
    )


def downgrade() -> None:
    # Tear down in reverse order. Note: we deliberately do NOT drop
    # final_routing_tier — it was part of the 0001 baseline contract; dropping
    # it here would leave 0001-only deployments without the column.
    op.execute("DROP INDEX IF EXISTS idx_routing_final_tier_decided_at")
    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_processing_path_chk")
    op.execute("ALTER TABLE routing_decisions DROP CONSTRAINT IF EXISTS routing_decisions_final_tier_chk")
    op.execute("ALTER TABLE routing_decisions DROP COLUMN IF EXISTS processing_path")
