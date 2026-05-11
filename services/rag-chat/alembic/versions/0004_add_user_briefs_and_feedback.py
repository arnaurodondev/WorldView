"""Add user_briefs and brief_feedback tables (PLAN-0066 Wave A T-W10-A-01).

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-08

Creates two tables in rag_chat_db to persist generated briefs and user feedback:

  user_briefs table (13 columns):
    id              UUID PK — app-generated UUIDv7 (Hard Rule R10, no DB default)
    user_id         UUID NOT NULL
    tenant_id       UUID NOT NULL
    brief_type      VARCHAR(20) NOT NULL — e.g. 'morning', 'entity'
    entity_id       UUID nullable — present for entity-scoped brief types
    generated_at    TIMESTAMPTZ NOT NULL — UTC generation timestamp (R11)
    headline        TEXT NOT NULL — primary heading shown in the brief card
    lead            TEXT nullable — optional introductory paragraph
    sections_json   JSONB NOT NULL DEFAULT '[]' — serialised list[BriefSection]
    citations_json  JSONB NOT NULL DEFAULT '[]' — serialised list[BriefCitation]
    confidence      FLOAT NOT NULL DEFAULT 1.0 — composite confidence score
    source_version  VARCHAR(10) NOT NULL DEFAULT 'v2' — schema version tag

  brief_feedback table (8 columns):
    id              UUID PK — app-generated UUIDv7 (Hard Rule R10, no DB default)
    brief_id        UUID NOT NULL REFERENCES user_briefs(id) ON DELETE CASCADE
    user_id         UUID NOT NULL
    scope           VARCHAR(10) NOT NULL — e.g. 'brief', 'section', 'bullet'
    section_idx     SMALLINT nullable — which section (None = brief-level feedback)
    bullet_idx      SMALLINT nullable — which bullet (None = section-level feedback)
    reaction        VARCHAR(20) NOT NULL — e.g. 'thumbs_up', 'thumbs_down'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()

Indexes (user_briefs):
  ix_user_briefs_user_date   — (user_id, generated_at DESC) for per-user history
  ix_user_briefs_tenant_date — (tenant_id, generated_at DESC) for tenant scans

Indexes (brief_feedback):
  ix_brief_feedback_brief_id — (brief_id) for FK lookups and feedback listing
  ix_brief_feedback_user     — (user_id, created_at DESC) for user feedback history

BP-126 compliance: all NOT NULL columns that need server defaults have one.
R10 compliance: id columns have NO server_default — UUIDv7 is generated in app.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_briefs ---------------------------------------------------------
    op.create_table(
        "user_briefs",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            # No server_default — ID is app-generated UUIDv7 (R10)
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("brief_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("lead", sa.Text(), nullable=True),
        sa.Column(
            "sections_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "citations_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "source_version",
            sa.String(10),
            nullable=False,
            server_default="v2",
        ),
    )
    op.create_index(
        "ix_user_briefs_user_date",
        "user_briefs",
        ["user_id", sa.text("generated_at DESC")],
    )
    op.create_index(
        "ix_user_briefs_tenant_date",
        "user_briefs",
        ["tenant_id", sa.text("generated_at DESC")],
    )

    # --- brief_feedback -------------------------------------------------------
    op.create_table(
        "brief_feedback",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            # No server_default — ID is app-generated UUIDv7 (R10)
        ),
        sa.Column(
            "brief_id",
            sa.UUID(),
            sa.ForeignKey("user_briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("section_idx", sa.SmallInteger(), nullable=True),
        sa.Column("bullet_idx", sa.SmallInteger(), nullable=True),
        sa.Column("reaction", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_brief_feedback_brief_id",
        "brief_feedback",
        ["brief_id"],
    )
    op.create_index(
        "ix_brief_feedback_user",
        "brief_feedback",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # Drop brief_feedback first — it has a FK pointing to user_briefs
    op.drop_index("ix_brief_feedback_user", table_name="brief_feedback")
    op.drop_index("ix_brief_feedback_brief_id", table_name="brief_feedback")
    op.drop_table("brief_feedback")

    op.drop_index("ix_user_briefs_tenant_date", table_name="user_briefs")
    op.drop_index("ix_user_briefs_user_date", table_name="user_briefs")
    op.drop_table("user_briefs")
