"""llm_replay_jobs table for the admin replay endpoint (PLAN-0055 C-4).

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-30

A row represents one replay job: re-score every article in ``[since, until]``
with a specific ``(model_id, prompt_version)``. The replay worker (Wave C-4
T-C-4-03) picks PENDING rows with ``FOR UPDATE SKIP LOCKED``, marks RUNNING,
then iterates articles in batches of ``NLP_LLM_REPLAY_BATCH_SIZE``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0014"
down_revision: str = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_replay_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("score_types", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("total_articles", sa.Integer(), nullable=True),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="ck_llm_replay_status",
        ),
    )
    # Worker query: SELECT ... WHERE status='PENDING' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
    op.create_index(
        "ix_llm_replay_pending",
        "llm_replay_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_llm_replay_pending", table_name="llm_replay_jobs")
    op.drop_table("llm_replay_jobs")
