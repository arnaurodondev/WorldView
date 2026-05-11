"""Add chat_audit_log table for per-turn observability (E-12).

This table stores one row per tool call plus one summary row per request turn.
It enables post-hoc analysis of:
  - Which tools were called and whether they succeeded
  - Per-tool latency distribution
  - Answer fingerprinting (SHA-256 hash, not full text) for dedup analysis
  - Total pipeline latency and iteration count per turn

WHY BIGSERIAL primary key (not UUID): this is an append-only audit table with
high write volume. BIGSERIAL gives predictable sequential I/O on the write path
and cheaper index scans on the read path (analytics queries). The turn_id column
(UUID) links rows to the application-level request.

WHY answer_hash (not full answer): storing the full LLM answer would be large
and privacy-sensitive. SHA-256 is sufficient for deduplication analysis and
detecting if the same answer is returned for semantically different queries.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("tool_success", sa.Boolean(), nullable=True),
        sa.Column("tool_latency_ms", sa.Integer(), nullable=True),
        sa.Column("entity_name", sa.Text(), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=True),
        sa.Column("answer_hash", sa.Text(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("iteration_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_audit_log_turn_id", "chat_audit_log", ["turn_id"])
    op.create_index("ix_chat_audit_log_thread_id", "chat_audit_log", ["thread_id"])
    op.create_index("ix_chat_audit_log_user_id", "chat_audit_log", ["user_id"])
    op.create_index("ix_chat_audit_log_created_at", "chat_audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_audit_log_created_at", "chat_audit_log")
    op.drop_index("ix_chat_audit_log_user_id", "chat_audit_log")
    op.drop_index("ix_chat_audit_log_thread_id", "chat_audit_log")
    op.drop_index("ix_chat_audit_log_turn_id", "chat_audit_log")
    op.drop_table("chat_audit_log")
