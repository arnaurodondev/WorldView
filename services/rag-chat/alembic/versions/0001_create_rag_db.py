"""Create rag_db initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-04-06

Creates the complete rag_db schema for S8 RAG-Chat service.
ORM models: rag_chat.infrastructure.db.models (BP-008: must stay in sync).
PRD reference: PRD-0015 §6.4
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── threads — conversation container ──────────────────────────────────────
    op.execute("""
        CREATE TABLE threads (
            thread_id   UUID        PRIMARY KEY,
            tenant_id   UUID        NOT NULL,
            user_id     UUID        NOT NULL,
            title       TEXT,
            entity_ids  UUID[]      NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL,
            last_msg_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ
        )
    """)

    # Partial indexes — only active (non-archived) threads
    op.execute("""
        CREATE INDEX ix_threads_user_active
            ON threads(user_id, tenant_id, last_msg_at DESC)
            WHERE archived_at IS NULL
    """)
    op.execute("""
        CREATE INDEX ix_threads_tenant_active
            ON threads(tenant_id, last_msg_at DESC)
            WHERE archived_at IS NULL
    """)

    # ── messages — individual turns ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE messages (
            message_id        UUID        PRIMARY KEY,
            thread_id         UUID        NOT NULL
                                          REFERENCES threads(thread_id) ON DELETE CASCADE,
            role              VARCHAR(20) NOT NULL
                                          CHECK (role IN ('user', 'assistant')),
            content           TEXT        NOT NULL,
            intent            VARCHAR(50),
            resolved_entities JSONB,
            retrieval_plan    JSONB,
            citations         JSONB,
            contradiction_refs JSONB,
            provider          VARCHAR(50),
            model             VARCHAR(100),
            token_count_in    INT,
            token_count_out   INT,
            latency_ms        INT,
            created_at        TIMESTAMPTZ NOT NULL
        )
    """)

    op.execute("""
        CREATE INDEX ix_messages_thread_created
            ON messages(thread_id, created_at ASC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_thread_created")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP INDEX IF EXISTS ix_threads_tenant_active")
    op.execute("DROP INDEX IF EXISTS ix_threads_user_active")
    op.execute("DROP TABLE IF EXISTS threads")
