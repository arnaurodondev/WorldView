"""Add ner_model_id to entity_mentions for NER model version tracking (PLAN-0031 B-1).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20

Adds a nullable ``ner_model_id`` column (VARCHAR 100) to ``entity_mentions``
so that every NER extraction is tagged with the GLiNER model version that
produced it.  ``server_default='unknown'`` ensures existing rows and any
inserts that omit the column receive a safe sentinel value (BP-126).

PRD reference: PLAN-0031 §B-1 (Pipeline Reliability Hardening)
ORM model: nlp_pipeline.infrastructure.nlp_db.models.EntityMentionModel
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entity_mentions",
        sa.Column("ner_model_id", sa.String(100), nullable=True, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("entity_mentions", "ner_model_id")
