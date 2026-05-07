"""add entity_mentions jsonb to chunks

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-07

PLAN-0078 Wave A — adds a denormalised JSONB column to the ``chunks`` table
that stores GLiNER mention metadata (entity_id, entity_type, char positions,
gliner_score, raw_text) for GIN-indexed query-time entity filtering.

The GIN index uses ``jsonb_path_ops`` to enable efficient containment
queries (``@>``) such as:
    WHERE entity_mentions @> '[{"entity_id": "<uuid>"}]'

Naming disambiguity: there is already a table called ``entity_mentions``
(which stores individual named-entity mention rows).  This migration adds a
*column* called ``entity_mentions`` on the ``chunks`` table — a denormalised
copy of resolved mention metadata for faster bulk GIN lookup.

The column is ``NOT NULL DEFAULT '[]'`` so existing rows get an empty JSONB
array immediately; the backfill script
(``nlp_pipeline.workers.backfill_entity_mentions``) populates non-empty
arrays for historical chunks by querying the join table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column(
            "entity_mentions",
            JSONB,
            nullable=False,
            server_default="[]",
        ),
    )
    # GIN index with jsonb_path_ops for efficient @> containment queries.
    # jsonb_path_ops supports @> and @? but not the ->> key extraction
    # operators (those stay on the default jsonb_ops).  All entity-filter
    # queries use @> (containment), so jsonb_path_ops is the right choice.
    op.create_index(
        "ix_chunks_entity_mentions_gin",
        "chunks",
        ["entity_mentions"],
        postgresql_using="gin",
        postgresql_ops={"entity_mentions": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_entity_mentions_gin", table_name="chunks")
    op.drop_column("chunks", "entity_mentions")
