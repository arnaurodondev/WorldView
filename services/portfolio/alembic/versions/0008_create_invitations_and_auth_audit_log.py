"""Create invitations and auth_audit_log tables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-12

Implements PLAN-0025 Wave C — PRD-0025 §6.4.
- invitations: B2B invite schema stub (no endpoints in this PRD)
- auth_audit_log: records provisioning events (USER_CREATED, ACCOUNT_LINKED, etc.)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── invitations ───────────────────────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_invitations_role"),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_invitations_tenant_email", "invitations", ["tenant_id", "email"])
    op.create_index(
        "idx_invitations_expires_at",
        "invitations",
        [sa.text("expires_at DESC")],
    )

    # ── auth_audit_log ────────────────────────────────────────────────────────
    op.create_table(
        "auth_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("sub", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("ip_address", sa.Text, nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_auth_audit_sub", "auth_audit_log", ["sub", sa.text("created_at DESC")])
    op.create_index(
        "idx_auth_audit_user",
        "auth_audit_log",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "idx_auth_audit_event_type",
        "auth_audit_log",
        ["event_type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # auth_audit_log
    op.drop_index("idx_auth_audit_event_type", table_name="auth_audit_log")
    op.drop_index("idx_auth_audit_user", table_name="auth_audit_log")
    op.drop_index("idx_auth_audit_sub", table_name="auth_audit_log")
    op.drop_table("auth_audit_log")

    # invitations
    op.drop_index("idx_invitations_expires_at", table_name="invitations")
    op.drop_index("idx_invitations_tenant_email", table_name="invitations")
    op.drop_table("invitations")
