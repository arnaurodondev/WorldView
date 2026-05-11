"""Add evidence_text column to relation_evidence_raw.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-03

Changes:
  relation_evidence_raw:
    - ADD COLUMN evidence_text TEXT NULL

WHY:
  SummaryWorker (13C) needs evidence text to generate LLM summaries.
  relation_evidence (the immutable partitioned table) was always empty because
  insert_immutable() had zero callers — no promotion step was ever implemented.
  The evidence_text captured from the NLP enrichment pipeline (via RawRelation)
  was silently dropped because insert_raw() had no evidence_text parameter.

  Fix: store evidence_text directly in relation_evidence_raw so that SummaryWorker
  can query it via get_raw_for_relation_id() without requiring a promotion step.

FORWARD-COMPATIBILITY (R5):
  Additive nullable column — no existing rows are affected.

DOWNGRADE:
  Drop the column; any stored evidence_text is lost (acceptable — it can be
  re-ingested from Kafka replay or NLP re-enrichment).
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE relation_evidence_raw
    ADD COLUMN IF NOT EXISTS evidence_text TEXT
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE relation_evidence_raw
    DROP COLUMN IF EXISTS evidence_text
""")
