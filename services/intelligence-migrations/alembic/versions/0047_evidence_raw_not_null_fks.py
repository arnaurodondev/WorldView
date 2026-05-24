"""relation_evidence_raw.claim_id + chunk_id NOT NULL + chunk_id index.

Revision ID: 0047
Revises: 0046
Create Date: 2026-05-23

PLAN-0093 Wave B-3 T-B-3-01.

WHY THIS MIGRATION EXISTS:
  Every evidence row should link back to a real ``claims`` row and a real
  ``chunks`` row so the relation → evidence → claim → chunk → document
  provenance chain is intact (F-DB-008).  Today both columns are nullable
  and ~20 % of evidence rows have NULL claim_id (writer was inserting
  evidence before the claim_id was captured from the claims insert).

WHAT IT DOES:
  Per the PLAN-0093 "Pre-Prod Simplifications" preamble (no data to
  preserve), TRUNCATE relation_evidence_raw, then flip both columns NOT
  NULL and add an index on chunk_id to make joins to nlp_db.chunks cheap.

  Note on FKs:
    * ``claim_id`` cannot be backed by a DB-level FK because ``claims`` is
      range-partitioned by ``created_at`` and its PK is
      ``(claim_id, created_at)`` — adding a UNIQUE constraint on just
      ``claim_id`` is not supported on a partitioned table without
      including the partition key.  Application code (the enriched_consumer
      writer updated in T-B-3-02) is now responsible for passing a real
      claim_id.  The NOT NULL constraint catches forgetting it at insert
      time.
    * ``chunk_id`` references nlp_db.chunks (cross-database) — also no
      DB-level FK possible.  Same app-level invariant applies.

DOWNGRADE:
  Drops the index, returns both columns to nullable.  Data is not
  restored.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """TRUNCATE legacy data + add NOT NULL + chunk_id index."""
    op.execute("TRUNCATE TABLE relation_evidence_raw CASCADE")

    op.alter_column("relation_evidence_raw", "claim_id", nullable=False)
    op.alter_column("relation_evidence_raw", "chunk_id", nullable=False)

    # Index for joins to nlp_db.chunks on chunk_id.
    op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_raw_chunk_id " "ON relation_evidence_raw (chunk_id)")


def downgrade() -> None:
    """Drop the index + restore nullable columns."""
    op.execute("DROP INDEX IF EXISTS ix_evidence_raw_chunk_id")
    op.alter_column(
        "relation_evidence_raw",
        "chunk_id",
        nullable=True,
        existing_type=sa.dialects.postgresql.UUID(),
    )
    op.alter_column(
        "relation_evidence_raw",
        "claim_id",
        nullable=True,
        existing_type=sa.dialects.postgresql.UUID(),
    )
