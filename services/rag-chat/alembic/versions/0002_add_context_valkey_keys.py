"""Add context_valkey_key and summary_valkey_key nullable columns to messages.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-07

Adds two nullable TEXT columns to the messages table for the 3-layer
context management system (PRD-0016 §6.4).  Existing rows receive NULL
values — fully backward-compatible.

  context_valkey_key  — Valkey key for cached retrieval chunks, e.g.
                        s8:ctx:chunks:{thread_id}:{turn_num}  (TTL 4h)
  summary_valkey_key  — Valkey key for the async turn summary, e.g.
                        s8:ctx:summary:{thread_id}:{turn_num} (TTL 24h)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS context_valkey_key TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS summary_valkey_key TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS context_valkey_key")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS summary_valkey_key")
