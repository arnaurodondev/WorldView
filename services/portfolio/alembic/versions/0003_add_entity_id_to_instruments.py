"""Add entity_id to instruments table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "instruments",
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_instruments_entity_id",
        "instruments",
        ["entity_id"],
        unique=False,
        postgresql_where=sa.text("entity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_instruments_entity_id", table_name="instruments")
    op.drop_column("instruments", "entity_id")
