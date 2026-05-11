"""Add ``dispatched_at`` column to ``outbox_events`` for schema unification.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-09

PLAN-0087 #9 / qa-beta-data-platform F-003 — Outbox schema unification.

Background:
    The market-ingestion service's ``outbox_events`` table tracks Kafka
    dispatch by toggling ``status='published'`` and stamping ``published_at``.
    Every other service in the platform exposes a ``dispatched_at`` column
    instead — and that's the column that ``docs/STANDARDS.md`` §3.4
    declares canonical.

    The audit (F-003) flagged the practical fallout: SQL-only operational
    tooling (replay scripts, dashboards, retention queries) that filters by
    ``dispatched_at IS NULL`` to find still-pending rows fails silently on
    this service. ``status`` alone gives no per-row dispatch timestamp; if
    you ``TRUNCATE`` (or archive) by ``status='published'`` you destroy
    your replay window in one shot.

What this migration does:
    1. Adds ``dispatched_at TIMESTAMPTZ`` as nullable (forward-compat per
       R5/R11 — existing writers continue to work without modification).
    2. Back-fills existing dispatched rows by copying ``published_at``
       into ``dispatched_at`` so historical visibility is preserved.

Why we don't drop ``published_at``:
    Removing the column would be a breaking schema change (R5 violation)
    and the application's ``OutboxRepository.mark_published`` writes to it.
    Until both columns are aligned by a follow-up that also updates the
    repository, ``dispatched_at`` is a parallel mirror — populated by a
    later migration or a code change writing both, whichever ships first.
    For this hotfix wave we only add the column + backfill so cross-service
    tooling stops missing rows.

Forward-compat (R5):
    Adding a nullable column with no default is forward-compatible.

R32 — revision number ``0013`` chains after head ``0012`` from the
filesystem (``ls services/market-ingestion/alembic/versions/`` 2026-05-09).
"""

from __future__ import annotations

from alembic import op

# Alembic identifiers — chains after 0012 to keep the linear history.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column. ``IF NOT EXISTS`` makes the migration safely
    # idempotent across local-dev DBs that may have been hot-patched.
    op.execute(
        """
        ALTER TABLE outbox_events
        ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ
        """
    )

    # 2. Backfill: every row that was previously marked as published carries
    # a ``published_at`` timestamp — mirror it into ``dispatched_at`` so
    # historical replay tooling is not blind to the past dispatch window.
    op.execute(
        """
        UPDATE outbox_events
        SET dispatched_at = published_at
        WHERE dispatched_at IS NULL
          AND published_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE outbox_events
        DROP COLUMN IF EXISTS dispatched_at
        """
    )
