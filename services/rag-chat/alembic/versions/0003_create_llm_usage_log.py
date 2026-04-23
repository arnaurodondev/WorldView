"""Create llm_usage_log table in rag_chat_db (PLAN-0033 T-B-1-03).

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22

Creates the ``llm_usage_log`` table in rag_chat_db to track every LLM call
made by the RAG Chat service (LLMProviderChain streaming completions).

Table schema (15 columns, 2 extra vs nlp-pipeline version):
  log_id             UUID PK — app-generated UUIDv7 (Hard Rule 6)
  model_id           VARCHAR(200) NOT NULL
  provider           VARCHAR(50)  NOT NULL
  capability         VARCHAR(50)  NOT NULL
  service_name       VARCHAR(50)  NOT NULL DEFAULT 'rag-chat'
  tenant_id          UUID nullable
  tokens_in          INT  NOT NULL DEFAULT 0
  tokens_out         INT  NOT NULL DEFAULT 0
  estimated_cost_usd FLOAT NOT NULL DEFAULT 0.0
  latency_ms         INT  NOT NULL DEFAULT 0
  success            BOOLEAN NOT NULL DEFAULT true
  error_code         VARCHAR(50) nullable
  session_id         UUID nullable  — RAG session when call was made
  chat_thread_id     UUID nullable  — chat thread when call was made
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()

Indexes:
  idx_rag_llm_usage_period   — (created_at DESC)
  idx_rag_llm_usage_provider — (provider, created_at DESC)
  idx_rag_llm_usage_session  — partial on (session_id) WHERE session_id IS NOT NULL

BP-126 compliance: all NOT NULL columns have server_default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_log",
        sa.Column(
            "log_id",
            sa.UUID(),
            primary_key=True,
            # No server_default — ID is app-generated UUIDv7 (Hard Rule 6 / R10)
        ),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("capability", sa.String(50), nullable=False),
        sa.Column(
            "service_name",
            sa.String(50),
            nullable=False,
            server_default="rag-chat",
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "estimated_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("chat_thread_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_rag_llm_usage_period",
        "llm_usage_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_rag_llm_usage_provider",
        "llm_usage_log",
        ["provider", sa.text("created_at DESC")],
    )
    # Partial index — only index rows with a non-null session_id
    op.execute(
        """
        CREATE INDEX idx_rag_llm_usage_session
        ON llm_usage_log (session_id)
        WHERE session_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rag_llm_usage_session")
    op.drop_index("idx_rag_llm_usage_provider", table_name="llm_usage_log")
    op.drop_index("idx_rag_llm_usage_period", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
