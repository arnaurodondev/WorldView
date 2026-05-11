"""Add resolution_outcome columns to entity_mentions and backfill (PLAN-0033 T-B-1-01).

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22

Adds three columns to ``entity_mentions`` for UnresolvedResolutionWorker tracking:

  resolution_outcome      VARCHAR(20)   — current lifecycle state of the mention
                          server_default='unresolved'; backfilled to 'auto_resolved'
                          for rows with a resolved_entity_id.
  resolution_noise_reason VARCHAR(200)  — LLM-provided reason when classified as noise
  resolution_processed_at TIMESTAMPTZ  — UTC timestamp when worker last processed it

Also creates a partial index on (created_at ASC) WHERE resolution_outcome='unresolved'
to support efficient worker polling with FOR UPDATE SKIP LOCKED.

BP-126 compliance: all NOT NULL columns have server_default.
Downtime: zero — all changes are additive with server defaults.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_INDEX_NAME = "idx_entity_mentions_unresolved"


def upgrade() -> None:
    # Step 1 — add the three new columns (all nullable or with server_default)
    op.add_column(
        "entity_mentions",
        sa.Column(
            "resolution_outcome",
            sa.String(20),
            nullable=False,
            server_default="unresolved",
        ),
    )
    op.add_column(
        "entity_mentions",
        sa.Column("resolution_noise_reason", sa.String(200), nullable=True),
    )
    op.add_column(
        "entity_mentions",
        sa.Column(
            "resolution_processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Step 2 — backfill: rows that already have a resolved_entity_id were
    # auto-resolved by the Block 9 cascade; mark them accordingly.
    op.execute(
        """
        UPDATE entity_mentions
        SET resolution_outcome = 'auto_resolved'
        WHERE resolved_entity_id IS NOT NULL
        """
    )

    # Step 3 — partial index for efficient worker polling
    op.execute(
        f"""
        CREATE INDEX {_INDEX_NAME}
        ON entity_mentions (created_at ASC)
        WHERE resolution_outcome = 'unresolved'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    op.drop_column("entity_mentions", "resolution_processed_at")
    op.drop_column("entity_mentions", "resolution_noise_reason")
    op.drop_column("entity_mentions", "resolution_outcome")
