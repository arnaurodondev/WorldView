"""Add alert_preferences and entity_suppressions tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "alert_type", name="uq_alert_preferences_user_type"),
    )
    op.create_index("ix_alert_preferences_user_id", "alert_preferences", ["user_id"])

    op.create_table(
        "entity_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entity_id", name="uq_entity_suppressions_user_entity"),
    )
    op.create_index("ix_entity_suppressions_user_id", "entity_suppressions", ["user_id"])
    op.create_index("ix_entity_suppressions_entity_id", "entity_suppressions", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_suppressions_entity_id", table_name="entity_suppressions")
    op.drop_index("ix_entity_suppressions_user_id", table_name="entity_suppressions")
    op.drop_table("entity_suppressions")
    op.drop_index("ix_alert_preferences_user_id", table_name="alert_preferences")
    op.drop_table("alert_preferences")
