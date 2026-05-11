"""Add external_id and role columns to users table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-12

Implements PLAN-0025 Wave C — PRD-0025 §6.4 B2B-ready user schema.
- external_id: nullable TEXT (Zitadel subject); unique partial index (NOT NULL rows only)
- role: NOT NULL VARCHAR(20) with CHECK + server_default='owner' (BP-126 compliant)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # external_id: nullable — existing rows get NULL (forward-compatible)
    op.add_column("users", sa.Column("external_id", sa.Text, nullable=True))

    # role: NOT NULL with server_default so existing rows get 'owner' (BP-126)
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'owner'"),
        ),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('owner', 'admin', 'member')",
    )

    # Unique partial index — only indexes non-NULL external_id rows
    op.create_index(
        "idx_users_external_id",
        "users",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_external_id", table_name="users")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
    op.drop_column("users", "external_id")
