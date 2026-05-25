"""Fix polarity column defaults from 'positive' to 'neutral' — F-018.

Revision ID: 0042
Revises: 0041
Create Date: 2026-05-22

WHY THIS MIGRATION EXISTS:
  The ``relation_evidence_raw.polarity`` and ``claims.polarity`` columns were
  created with ``DEFAULT 'positive'``.  This is semantically wrong: the default
  should be "neutral" (polarity unknown) not "positive" (polarity asserted).

  The bias caused 9,454 of 9,465 ``relation_evidence_raw`` rows to carry
  polarity='positive', making the contradiction-detection subsystem (which
  requires polarity variation: positive vs negative) structurally inoperative.

  Application code (commit b031fccb) already defaults to "neutral" when polarity
  is absent from the extraction payload.  This migration aligns the database
  server-default with that application-level intent so that:
    (a) Any row inserted without an explicit polarity value gets 'neutral'.
    (b) The contradiction-detection pipeline can distinguish genuinely-positive
        relations from unclassified ones, enabling accurate conflict scoring.

  Application-layer code defaults (RawRelation dataclass, port signature,
  repository helper) are also updated in the same commit to 'neutral'.

FORWARD-COMPATIBILITY (R5):
  ``ALTER COLUMN … SET DEFAULT`` only affects future inserts — existing rows
  are NOT modified.  This change is fully additive and rollback-safe.

IDEMPOTENCY:
  Altering a column default is idempotent: running upgrade() twice leaves the
  column in the same state as running it once.
"""

from __future__ import annotations

from alembic import op

revision: str = "0042"
down_revision: str = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change polarity column server-defaults from 'positive' to 'neutral'."""
    # relation_evidence_raw — hot-path staging table for extracted relations
    op.alter_column(
        "relation_evidence_raw",
        "polarity",
        server_default="neutral",
    )

    # claims — structured claim assertions; same polarity semantics apply
    op.alter_column(
        "claims",
        "polarity",
        server_default="neutral",
    )


def downgrade() -> None:
    """Restore polarity column server-defaults to the original 'positive'."""
    op.alter_column(
        "relation_evidence_raw",
        "polarity",
        server_default="positive",
    )

    op.alter_column(
        "claims",
        "polarity",
        server_default="positive",
    )
