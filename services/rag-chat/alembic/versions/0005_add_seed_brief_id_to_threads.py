"""Add seed_brief_id column to threads table (PLAN-0066 Wave D T-W10-D-01).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-08

WHY seed_brief_id: when a user clicks "Discuss in chat" on a morning brief, the
new POST /v1/briefings/chat/discuss endpoint creates a thread pre-seeded with the
brief context. The seed_brief_id FK records which brief seeded the thread, enabling:
  - The RetrievalOrchestrator to inject brief citations as high-trust items
  - The frontend to display "Started from [date] brief" in the thread header
  - Future analytics on brief → conversation conversion rates

WHY ON DELETE SET NULL: if the source brief row is deleted (e.g. pruned by a
retention job), the thread continues to exist and can still be used — we just
lose the seed reference. SET NULL is safer than CASCADE (which would delete the
thread) or RESTRICT (which would prevent brief deletion).

BP-126 compliance: seed_brief_id is nullable — no server_default needed.
R10 compliance: no id column affected — this migration only adds a FK column.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add seed_brief_id as a nullable FK to user_briefs(id).
    # ON DELETE SET NULL: brief deletion does not cascade to thread rows.
    #
    # WHY raw SQL via op.execute (not op.add_column): the rag-chat DDL alignment
    # test (tests/unit/infrastructure/test_ddl_alignment.py) parses migration files
    # with a regex over CREATE TABLE / ALTER TABLE statements. ``op.add_column``
    # is a Python API call that the regex does not match, so the new column would
    # be silently invisible to the alignment guard and the ORM-vs-DDL test would
    # fail with "ORM columns missing from DDL". Migration 0002 establishes the
    # raw-SQL convention in this codebase; we follow it here.
    op.execute(
        "ALTER TABLE threads ADD COLUMN IF NOT EXISTS seed_brief_id UUID "
        "REFERENCES user_briefs(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE threads DROP COLUMN IF EXISTS seed_brief_id")
