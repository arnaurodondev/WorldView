"""Add nullable tenant_id to entity_mentions for tenant isolation (F-009).

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-24

entity_mentions reveals which entities a tenant watches — this needs tenant
isolation even though articles themselves are platform-global (public news).

Operations:
  1. ADD COLUMN tenant_id UUID (nullable) to entity_mentions
  2. CREATE INDEX idx_entity_mentions_tenant_entity ON (tenant_id, resolved_entity_id)

Nullable so legacy rows (NULL tenant_id) work with IS NULL fallback in queries.
Zero-downtime: nullable column add does not rewrite the table.

Downgrade:
  - DROP INDEX + DROP COLUMN (safe; no data loss beyond tenant_id values).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable tenant_id column — no server_default needed (nullable, BP-126)
    op.add_column(
        "entity_mentions",
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2. Composite index for tenant-scoped entity article queries (F-009 Option B)
    op.execute("""
        CREATE INDEX idx_entity_mentions_tenant_entity
        ON entity_mentions (tenant_id, resolved_entity_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entity_mentions_tenant_entity")
    op.drop_column("entity_mentions", "tenant_id")
